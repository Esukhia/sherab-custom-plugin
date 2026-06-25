"""
API endpoints for the Sherab AI course-creator chatbot (Studio / CMS side).

Endpoints (mounted under the app namespace, see urls.py):
    POST  api/ai-course-creator/chat/             -> stream an assistant reply (SSE)
    POST  api/ai-course-creator/upload/           -> add a material (file / link / text)
    POST  api/ai-course-creator/generate/         -> generate + write the course (SSE)
    GET   api/ai-course-creator/session/          -> fetch the session (resume)
    GET   api/ai-course-creator/section-content/  -> read one section's content tree
    POST  api/ai-course-creator/section-chat/     -> stream a per-section editor reply (SSE)
    POST  api/ai-course-creator/apply-section/    -> apply the latest proposed section edits

Auth: JWT (sent by the authoring MFE) or session. All endpoints require an
authenticated user, and course-mutating actions additionally check course
author access.
"""

import logging

from django.http import StreamingHttpResponse
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .helpers import (
    feature_enabled,
    get_or_create_session,
    max_upload_bytes,
    require_course_author,
    sse,
)
from .models import ChatMessage, ChatSession, UploadedMaterial
from .serializers import ChatSessionSerializer
from .services import course_builder, generator, materials, section_editor
from .services.llm_client import (
    SECTION_CHAT_MAX_TOKENS,
    LLMError,
    LLMNotConfigured,
    extract_course_json,
    extract_phase_marker,
    extract_section_edits,
    stream_reply,
    strip_course_json,
)

log = logging.getLogger(__name__)

AUTHENTICATION_CLASSES = (JwtAuthentication, SessionAuthentication)


class ChatView(APIView):
    """Stream the assistant's next reply for a (user, course) conversation."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    @staticmethod
    def _recompute_phase(session):
        """
        Reset ``current_phase`` to the highest phase marker still present in the
        surviving assistant messages (default 1). Used after an edit truncates
        the conversation so the phase indicator can't stay ahead of the content.
        """
        highest = 1
        for message in session.messages.filter(role=ChatMessage.Role.ASSISTANT):
            phase = extract_phase_marker(message.content)
            if phase and phase > highest:
                highest = phase
        if session.current_phase != highest:
            session.current_phase = highest
            session.save(update_fields=["current_phase", "modified"])

    def post(self, request):
        course_id = request.data.get("course_id")
        message_text = (request.data.get("message") or "").strip()
        edit_message_id = request.data.get("edit_message_id")
        if not course_id:
            return Response({"error": "course_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        _course_key, error = require_course_author(request.user, course_id)
        if error:
            return error

        session = get_or_create_session(request.user, course_id)

        # Edit & resend: the creator changed an earlier message. Drop that message
        # and everything after it (the stale assistant reply and any later turns),
        # then re-ask from that point with the new text. Phase is recomputed from
        # the surviving assistant messages so the indicator rolls back correctly.
        if edit_message_id is not None:
            if not message_text:
                return Response(
                    {"error": "An edited message cannot be empty."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                target = session.messages.get(pk=edit_message_id, role=ChatMessage.Role.USER)
            except ChatMessage.DoesNotExist:
                return Response(
                    {"error": "That message no longer exists."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            # ids are monotonic with creation order, so >= the target drops it and
            # everything after it in one shot.
            session.messages.filter(pk__gte=target.pk).delete()
            self._recompute_phase(session)

        # Persist the user's turn (an empty message is allowed for the very first
        # "open the chat" call, which just triggers Sherab's greeting).
        user_message = None
        if message_text:
            user_message = ChatMessage.objects.create(
                session=session, role=ChatMessage.Role.USER, content=message_text
            )

        history = [
            {"role": m.role, "content": m.content}
            for m in session.messages.all()
        ]
        if not history:
            # Kick off the conversation: a neutral opener so Sherab gives its
            # Phase-1 greeting per the skill.
            history = [{"role": "user", "content": "Let's start creating my course."}]

        # Chat only needs to know *which* materials exist (names), so Sherab can
        # acknowledge them. The full extracted text is sent only at generation
        # time — see services/generator.py — which keeps chat requests small.
        materials_context = materials.build_names_summary(session.materials.all())

        def event_stream():
            # Emit the persisted user-message id up front so the client can tag
            # (and later edit) the message even if the stream then errors out and
            # never reaches the closing "done" frame.
            if user_message is not None:
                yield sse({"type": "meta", "userMessageId": user_message.id})

            collected = []
            try:
                for chunk in stream_reply(history, materials_context):
                    collected.append(chunk)
                    yield sse({"type": "token", "text": chunk})
            except (LLMNotConfigured, LLMError) as exc:
                yield sse({"type": "error", "error": str(exc)})
                return
            except Exception:  # pylint: disable=broad-except
                log.exception("ai_course_creator: chat stream failed")
                yield sse({"type": "error", "error": "The assistant ran into a problem."})
                return

            full_text = "".join(collected)
            course_json = extract_course_json(full_text)
            new_phase = extract_phase_marker(full_text)
            assistant_message = None
            try:
                # Persist the assistant turn (full text, incl. any COURSE_JSON block).
                assistant_message = ChatMessage.objects.create(
                    session=session, role=ChatMessage.Role.ASSISTANT, content=full_text
                )
                update_fields = ["modified"]
                if course_json:
                    session.course_json = course_json
                    session.status = ChatSession.Status.GENERATED
                    update_fields += ["course_json", "status"]
                if new_phase and new_phase > session.current_phase:
                    session.current_phase = new_phase
                    update_fields.append("current_phase")
                if len(update_fields) > 1:
                    session.save(update_fields=update_fields)
            except Exception:  # pylint: disable=broad-except
                # Don't let a persistence hiccup kill the stream the user already saw.
                log.exception("ai_course_creator: failed to persist assistant message")

            yield sse({
                "type": "done",
                "hasCourseJson": bool(course_json),
                "currentPhase": session.current_phase,
                "userMessageId": user_message.id if user_message else None,
                "assistantMessageId": assistant_message.id if assistant_message else None,
            })

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # disable nginx buffering for SSE
        return response


class SectionContentView(APIView):
    """Return one section's (chapter's) current content tree for the editor sidebar."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        course_id = request.query_params.get("course_id")
        section_locator = request.query_params.get("section_locator")
        if not course_id or not section_locator:
            return Response(
                {"error": "course_id and section_locator are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            tree = section_editor.read_section(course_id, request.user, section_locator)
        except section_editor.SectionEditError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(tree)


class SectionChatView(APIView):
    """Stream the per-section editor's next reply for a (user, course, section)."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        course_id = request.data.get("course_id")
        section_locator = request.data.get("section_locator")
        message_text = (request.data.get("message") or "").strip()
        edit_message_id = request.data.get("edit_message_id")
        if not course_id or not section_locator:
            return Response(
                {"error": "course_id and section_locator are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Read the current section content up front: it both seeds the model's
        # awareness of what's there and validates the locator/permission before
        # we open a streaming response (errors are easier to surface as JSON).
        try:
            section_tree = section_editor.read_section(course_id, request.user, section_locator)
        except section_editor.SectionEditError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        session = _get_or_create_session(request.user, course_id, section_locator=section_locator)

        # Edit & resend: drop the edited message and everything after it.
        if edit_message_id is not None:
            if not message_text:
                return Response(
                    {"error": "An edited message cannot be empty."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                target = session.messages.get(pk=edit_message_id, role=ChatMessage.Role.USER)
            except ChatMessage.DoesNotExist:
                return Response(
                    {"error": "That message no longer exists."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            session.messages.filter(pk__gte=target.pk).delete()

        user_message = None
        if message_text:
            user_message = ChatMessage.objects.create(
                session=session, role=ChatMessage.Role.USER, content=message_text
            )

        history = [
            {"role": m.role, "content": m.content}
            for m in session.messages.all()
        ]
        if not history:
            history = [{"role": "user", "content": "Let's improve this section."}]

        # The current section content is injected as context on the last user
        # turn (like the materials digest), re-read each turn so the model always
        # references live usage keys.
        section_context = (
            "[Current section content (JSON tree with usageKeys). Reference only these "
            f"usageKeys when proposing edits:\n{json.dumps(section_tree)}\n]"
        )

        def event_stream():
            if user_message is not None:
                yield _sse({"type": "meta", "userMessageId": user_message.id})

            collected = []
            try:
                for chunk in stream_reply(
                    history,
                    materials_context=section_context,
                    skill_name="skill_section_editor",
                    max_tokens=SECTION_CHAT_MAX_TOKENS,
                ):
                    collected.append(chunk)
                    yield _sse({"type": "token", "text": chunk})
            except (LLMNotConfigured, LLMError) as exc:
                yield _sse({"type": "error", "error": str(exc)})
                return
            except Exception:  # pylint: disable=broad-except
                log.exception("ai_course_creator: section chat stream failed")
                yield _sse({"type": "error", "error": "The assistant ran into a problem."})
                return

            full_text = "".join(collected)
            can_apply = bool(extract_section_edits(full_text))
            assistant_message = None
            try:
                assistant_message = ChatMessage.objects.create(
                    session=session, role=ChatMessage.Role.ASSISTANT, content=full_text
                )
            except Exception:  # pylint: disable=broad-except
                log.exception("ai_course_creator: failed to persist section assistant message")

            yield _sse({
                "type": "done",
                "canApply": can_apply,
                "userMessageId": user_message.id if user_message else None,
                "assistantMessageId": assistant_message.id if assistant_message else None,
            })

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # disable nginx buffering for SSE
        return response


class ApplySectionView(APIView):
    """Apply the most recently proposed section edits for a (user, course, section)."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        course_id = request.data.get("course_id")
        section_locator = request.data.get("section_locator")
        if not course_id or not section_locator:
            return Response(
                {"error": "course_id and section_locator are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            session = ChatSession.objects.get(
                user=request.user, course_id=course_id, section_locator=section_locator
            )
        except ChatSession.DoesNotExist:
            return Response(
                {"error": "No conversation to apply yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Use the most recent assistant message that carries a SECTION_EDITS block.
        edits = None
        for message in session.messages.filter(
            role=ChatMessage.Role.ASSISTANT
        ).order_by("-created", "-id"):
            edits = extract_section_edits(message.content)
            if edits is not None:
                break
        if edits is None:
            return Response(
                {"error": "There are no proposed changes to apply."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            summary = section_editor.apply_section_edits(
                course_id, request.user, section_locator, edits
            )
        except section_editor.SectionEditError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:  # pylint: disable=broad-except
            log.exception("ai_course_creator: apply section edits failed")
            return Response(
                {"error": "Could not apply the changes. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            "sectionName": summary.get("sectionName", ""),
            "counts": {
                "updated": summary.get("updated", 0),
                "created": summary.get("created", 0),
                "deleted": summary.get("deleted", 0),
                "reordered": summary.get("reordered", 0),
            },
            "rejected": summary.get("rejected", []),
            "errors": summary.get("errors", []),
        })


class UploadMaterialView(APIView):
    """Accept a material (file upload, link, or pasted text) and extract its text."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        course_id = request.data.get("course_id")
        if not course_id:
            return Response({"error": "course_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        _course_key, error = require_course_author(request.user, course_id)
        if error:
            return error

        session = get_or_create_session(request.user, course_id)
        uploaded = request.FILES.get("file")
        url = (request.data.get("url") or "").strip()

        try:
            if uploaded:
                max_bytes = max_upload_bytes()
                if uploaded.size and uploaded.size > max_bytes:
                    return Response(
                        {"error": "File is too large."}, status=status.HTTP_400_BAD_REQUEST
                    )
                extracted = materials.extract_from_upload(uploaded.name, uploaded)
                material = UploadedMaterial.objects.create(
                    session=session,
                    source_type=UploadedMaterial.SourceType.FILE,
                    name=uploaded.name,
                    extracted_text=extracted,
                )
            elif url:
                extracted = materials.extract_from_url(url)
                material = UploadedMaterial.objects.create(
                    session=session,
                    source_type=UploadedMaterial.SourceType.LINK,
                    name=url,
                    extracted_text=extracted,
                )
            else:
                return Response(
                    {"error": "Provide a file or url."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:  # pylint: disable=broad-except
            log.exception("ai_course_creator: material upload failed")
            return Response(
                {"error": "Could not read that material."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "id": material.id,
                "name": material.name,
                "sourceType": material.source_type,
                "chars": len(material.extracted_text or ""),
            },
            status=status.HTTP_201_CREATED,
        )


class GenerateCourseView(APIView):
    """
    Generate the full course (structure + content) and write it into the course
    outline as draft blocks, streaming progress over SSE.

    Flow: generate skeleton -> per-section content -> store outline -> write to
    the modulestore (draft). The generated outline is cached on the session so a
    failed *write* can be retried without re-paying for generation. A failed
    write rolls back any partial structure (see course_builder).
    """

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        if not feature_enabled():
            return Response(
                {"error": "The AI course creator is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )

        course_id = request.data.get("course_id")
        if not course_id:
            return Response({"error": "course_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        _course_key, error = require_course_author(request.user, course_id)
        if error:
            return error

        session = get_or_create_session(request.user, course_id)
        user = request.user

        def _set_status(generation_status, error=""):
            session.generation_status = generation_status
            session.generation_error = error
            session.save(update_fields=["generation_status", "generation_error", "modified"])

        def event_stream():
            # 1. Generate (skeleton + per-section content).
            _set_status(ChatSession.GenerationStatus.GENERATING)
            course = None
            try:
                for event in generator.iter_generate(session):
                    if event["type"] == "progress":
                        yield sse({"type": "progress", "message": event["message"]})
                    elif event["type"] == "outline":
                        course = event["course"]
            except (LLMNotConfigured, LLMError, generator.GenerationError) as exc:
                _set_status(ChatSession.GenerationStatus.FAILED, str(exc))
                yield sse({"type": "error", "error": str(exc)})
                return
            except Exception:  # pylint: disable=broad-except
                log.exception("ai_course_creator: generation failed")
                msg = "Sherab couldn't generate the course. Please try again."
                _set_status(ChatSession.GenerationStatus.FAILED, msg)
                yield sse({"type": "error", "error": msg})
                return

            if not course:
                msg = "Sherab couldn't generate the course. Please try again."
                _set_status(ChatSession.GenerationStatus.FAILED, msg)
                yield sse({"type": "error", "error": msg})
                return

            # Cache the generated outline so a write-only retry is free.
            session.course_json = course
            session.status = ChatSession.Status.GENERATED
            session.save(update_fields=["course_json", "status", "modified"])

            # If a previous run already wrote sections, clear them first so a
            # retry/regenerate never duplicates content.
            if session.created_section_locators:
                course_builder.delete_sections(
                    course_id, user, session.created_section_locators
                )
                session.created_section_locators = []
                session.save(update_fields=["created_section_locators", "modified"])

            # 2. Write to the course outline (draft).
            _set_status(ChatSession.GenerationStatus.WRITING)
            yield sse({"type": "progress", "message": "Adding everything to your course outline…"})
            try:
                result = course_builder.apply_course_json(course_id, user, course)
            except course_builder.CourseBuildError as exc:
                _set_status(ChatSession.GenerationStatus.FAILED, str(exc))
                yield sse({"type": "error", "error": str(exc)})
                return
            except Exception:  # pylint: disable=broad-except
                log.exception("ai_course_creator: write failed")
                msg = "Could not add the course to the outline. Please try again."
                _set_status(ChatSession.GenerationStatus.FAILED, msg)
                yield sse({"type": "error", "error": msg})
                return

            session.created_section_locators = result.get("sectionLocators") or []
            session.status = ChatSession.Status.APPLIED
            session.generation_status = ChatSession.GenerationStatus.DONE
            session.generation_error = ""
            session.save(update_fields=[
                "created_section_locators", "status", "generation_status",
                "generation_error", "modified",
            ])
            yield sse({"type": "done", "counts": result.get("counts", {})})

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # disable nginx buffering for SSE
        return response


class SessionView(APIView):
    """Return the existing conversation for a course so the modal can resume."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        course_id = request.query_params.get("course_id")
        if not course_id:
            return Response({"error": "course_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        session = get_or_create_session(request.user, course_id)
        return Response(ChatSessionSerializer(session).data)

    def delete(self, request):
        """
        Reset a conversation: delete the session (and its messages + materials).

        Scoped to a single ``section_locator`` so resetting one section's editor
        thread (or the creator thread, section_locator="") never wipes the others.
        """
        course_id = request.query_params.get("course_id") or request.data.get("course_id")
        if not course_id:
            return Response({"error": "course_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        section_locator = (
            request.query_params.get("section_locator")
            or request.data.get("section_locator")
            or ""
        )
        ChatSession.objects.filter(
            user=request.user, course_id=course_id, section_locator=section_locator
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MaterialDetailView(APIView):
    """Delete a single uploaded material."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def delete(self, request, pk):
        # Scope to the requesting user's own sessions.
        deleted, _ = UploadedMaterial.objects.filter(
            pk=pk, session__user=request.user
        ).delete()
        if not deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConfigView(APIView):
    """Expose the feature flag so the Studio outline can show/hide the launch button."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response({"enabled": feature_enabled()})
