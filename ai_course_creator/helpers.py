"""
Helper functions for the Sherab AI course-creator views.

Kept out of ``views.py`` so that module holds only the API views. These cover
SSE formatting, session lookup, feature/limit settings, and the shared
course-key + author-permission guard used by the course-mutating endpoints.
"""

import json

from rest_framework import status
from rest_framework.response import Response

from .models import ChatSession


def sse(payload):
    """Format a dict as a Server-Sent Events ``data:`` frame."""
    return f"data: {json.dumps(payload)}\n\n"


def get_or_create_session(user, course_id):
    """Fetch or create the conversation for a (user, course)."""
    session, _created = ChatSession.objects.get_or_create(user=user, course_id=course_id)
    return session


def require_course_author(user, course_id):
    """
    Validate ``course_id`` and that ``user`` may author that course.

    Returns ``(course_key, None)`` on success, or ``(None, Response)`` carrying
    the appropriate error response when the id is malformed or the user lacks
    author access. Callers do ``key, error = require_course_author(...); if
    error: return error``.
    """
    from opaque_keys import InvalidKeyError  # pylint: disable=import-outside-toplevel
    from opaque_keys.edx.keys import CourseKey  # pylint: disable=import-outside-toplevel

    from .services import course_builder  # pylint: disable=import-outside-toplevel

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
    from django.conf import settings  # pylint: disable=import-outside-toplevel

    return bool(getattr(settings, "AI_COURSE_CREATOR_ENABLED", True))


def max_upload_bytes():
    """The maximum accepted size (bytes) for an uploaded material."""
    from django.conf import settings  # pylint: disable=import-outside-toplevel

    return getattr(settings, "AI_COURSE_CREATOR_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
