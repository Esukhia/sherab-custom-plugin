"""
API endpoints for the Sherab AI course-creator chatbot (Studio / CMS side).

Endpoints (mounted under the app namespace, see urls.py):
    POST  api/ai-course-creator/chat/      -> stream an assistant reply (SSE)
    POST  api/ai-course-creator/upload/    -> add a material (file / link / text)
    POST  api/ai-course-creator/apply/     -> build course structure from the outline
    GET   api/ai-course-creator/session/   -> fetch the session (resume)

Auth: JWT (sent by the authoring MFE) or session. All endpoints require an
authenticated user, and course-mutating actions additionally check course
author access.
"""

import json
import logging

from django.http import StreamingHttpResponse
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ChatMessage, ChatSession, UploadedMaterial
from .serializers import ChatSessionSerializer
from .services import course_builder, materials
from .services.llm_client import (
    LLMError,
    LLMNotConfigured,
    extract_course_json,
    extract_phase_marker,
    stream_reply,
    strip_course_json,
)

log = logging.getLogger(__name__)

AUTHENTICATION_CLASSES = (JwtAuthentication, SessionAuthentication)


def _sse(payload):
    """Format a dict as a Server-Sent Events ``data:`` frame."""
    return f"data: {json.dumps(payload)}\n\n"


def _get_or_create_session(user, course_id):
    session, _created = ChatSession.objects.get_or_create(user=user, course_id=course_id)
    return session


class ChatView(APIView):
    """Stream the assistant's next reply for a (user, course) conversation."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        course_id = request.data.get("course_id")
        message_text = (request.data.get("message") or "").strip()
        if not course_id:
            return Response({"error": "course_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        session = _get_or_create_session(request.user, course_id)

        # Persist the user's turn (an empty message is allowed for the very first
        # "open the chat" call, which just triggers Sherab's greeting).
        if message_text:
            ChatMessage.objects.create(
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

        materials_context = materials.build_context(session.materials.all())

        def event_stream():
            collected = []
            try:
                for chunk in stream_reply(history, materials_context):
                    collected.append(chunk)
                    yield _sse({"type": "token", "text": chunk})
            except (LLMNotConfigured, LLMError) as exc:
                yield _sse({"type": "error", "error": str(exc)})
                return
            except Exception:  # pylint: disable=broad-except
                log.exception("ai_course_creator: chat stream failed")
                yield _sse({"type": "error", "error": "The assistant ran into a problem."})
                return

            full_text = "".join(collected)
            course_json = extract_course_json(full_text)
            new_phase = extract_phase_marker(full_text)
            try:
                # Persist the assistant turn (full text, incl. any COURSE_JSON block).
                ChatMessage.objects.create(
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

            yield _sse({"type": "done", "hasCourseJson": bool(course_json), "currentPhase": session.current_phase})

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # disable nginx buffering for SSE
        return response


class UploadMaterialView(APIView):
    """Accept a material (file upload, link, or pasted text) and extract its text."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        course_id = request.data.get("course_id")
        if not course_id:
            return Response({"error": "course_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        session = _get_or_create_session(request.user, course_id)
        uploaded = request.FILES.get("file")
        url = (request.data.get("url") or "").strip()
        text = (request.data.get("text") or "").strip()

        try:
            if uploaded:
                max_bytes = _max_upload_bytes()
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
            elif text:
                material = UploadedMaterial.objects.create(
                    session=session,
                    source_type=UploadedMaterial.SourceType.TEXT,
                    name=(text[:60] + "…") if len(text) > 60 else text,
                    extracted_text=text,
                )
            else:
                return Response(
                    {"error": "Provide a file, url, or text."},
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


class ApplyOutlineView(APIView):
    """Build the real course structure from the generated outline."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        course_id = request.data.get("course_id")
        if not course_id:
            return Response({"error": "course_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        session = _get_or_create_session(request.user, course_id)
        course_json = request.data.get("course_json") or session.course_json
        if not course_json:
            return Response(
                {"error": "No generated outline is available yet."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = course_builder.apply_course_json(course_id, request.user, course_json)
        except course_builder.CourseBuildError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:  # pylint: disable=broad-except
            log.exception("ai_course_creator: apply outline failed")
            return Response(
                {"error": "Could not build the course structure."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        session.course_json = course_json
        session.status = ChatSession.Status.APPLIED
        session.save(update_fields=["course_json", "status", "modified"])
        return Response(result, status=status.HTTP_200_OK)


class SessionView(APIView):
    """Return the existing conversation for a course so the modal can resume."""

    authentication_classes = AUTHENTICATION_CLASSES
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        course_id = request.query_params.get("course_id")
        if not course_id:
            return Response({"error": "course_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        session = _get_or_create_session(request.user, course_id)
        return Response(ChatSessionSerializer(session).data)

    def delete(self, request):
        """Reset the conversation: delete the session (and its messages + materials)."""
        course_id = request.query_params.get("course_id") or request.data.get("course_id")
        if not course_id:
            return Response({"error": "course_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        ChatSession.objects.filter(user=request.user, course_id=course_id).delete()
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


def _max_upload_bytes():
    from django.conf import settings

    return getattr(settings, "AI_COURSE_CREATOR_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
