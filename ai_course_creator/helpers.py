"""
Helper functions for the Sherab AI course-creator views.

Kept out of ``views.py`` so that module holds only the API views. These cover
SSE formatting, session lookup, feature/limit settings, and the shared
course-key + author-permission guard used by the course-mutating endpoints.
"""

import json

from django.conf import settings
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from rest_framework import status
from rest_framework.response import Response

from .models import ChatMessage, ChatSession
from .services import course_builder


def sse(payload):
    """Format a dict as a Server-Sent Events ``data:`` frame."""
    return f"data: {json.dumps(payload)}\n\n"


def get_or_create_session(user, course_id, section_locator=""):
    """Fetch or create the conversation for a (user, course[, section])."""
    session, _created = ChatSession.objects.get_or_create(
        user=user, course_id=course_id, section_locator=section_locator
    )
    return session


def truncate_for_edit(session, edit_message_id, message_text):
    """
    Edit-and-resend: validate the edited user message, then drop it and every
    message after it. ids are monotonic with creation order, so ``>= target``
    removes the stale assistant reply and any later turns in one shot.

    Returns ``(target, None)`` on success, or ``(None, Response)`` carrying the
    appropriate error when the new text is empty or the message is gone. Callers
    do ``target, error = truncate_for_edit(...); if error: return error``.
    """
    if not message_text:
        return None, Response(
            {"error": "An edited message cannot be empty."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        target = session.messages.get(pk=edit_message_id, role=ChatMessage.Role.USER)
    except ChatMessage.DoesNotExist:
        return None, Response(
            {"error": "That message no longer exists."},
            status=status.HTTP_404_NOT_FOUND,
        )
    session.messages.filter(pk__gte=target.pk).delete()
    return target, None


def require_course_author(user, course_id):
    """
    Validate ``course_id`` and that ``user`` may author that course.

    Returns ``(course_key, None)`` on success, or ``(None, Response)`` carrying
    the appropriate error response when the id is malformed or the user lacks
    author access. Callers do ``key, error = require_course_author(...); if
    error: return error``.
    """
    try:
        course_key = CourseKey.from_string(course_id)
    except InvalidKeyError:
        return None, Response({"error": "Invalid course id."}, status=status.HTTP_400_BAD_REQUEST)

    if not course_builder.user_can_author(user, course_key):
        return None, Response(
            {"error": "You do not have permission to edit this course."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return course_key, None


def feature_enabled():
    """True when the AI course creator is enabled in settings."""
    return bool(getattr(settings, "AI_COURSE_CREATOR_ENABLED", True))


def max_upload_bytes():
    """The maximum accepted size (bytes) for an uploaded material."""
    return getattr(settings, "AI_COURSE_CREATOR_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
