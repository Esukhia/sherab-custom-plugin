"""
Common Pluggable Django App settings for ai_course_creator.
"""

import os


def plugin_settings(settings):
    """
    Injects AI Course Creator settings into the Django settings object.

    The Gemini credentials (``GEMINI_API_KEY`` / ``GEMINI_MODEL``) are normally
    injected into CMS settings from Tutor ``config.yml`` via the
    ``configuration_plugin`` patch. We fall back to environment variables /
    sensible defaults so the app also works in tests and in environments where
    the patch is not applied.
    """
    settings.GEMINI_API_KEY = getattr(
        settings, "GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", "")
    )
    settings.GEMINI_MODEL = getattr(
        settings, "GEMINI_MODEL", os.environ.get("GEMINI_MODEL", "gemini-1.5-pro")
    )

    # Hard limits for uploaded course materials (bytes). 25 MB by default.
    settings.AI_COURSE_CREATOR_MAX_UPLOAD_BYTES = getattr(
        settings, "AI_COURSE_CREATOR_MAX_UPLOAD_BYTES", 25 * 1024 * 1024
    )

    # Max characters of uploaded-material text sent to the model per request, to
    # stay within the LLM's per-request token budget (~16k chars ≈ 4k tokens).
    settings.AI_COURSE_CREATOR_MAX_CONTEXT_CHARS = getattr(
        settings, "AI_COURSE_CREATOR_MAX_CONTEXT_CHARS", 16_000
    )

    # Master on/off switch for the Sherab AI course-creator. When False, the
    # Studio launch button is hidden. The button is only ever shown on an empty
    # course outline regardless of this flag.
    settings.AI_COURSE_CREATOR_ENABLED = getattr(
        settings,
        "AI_COURSE_CREATOR_ENABLED",
        os.environ.get("AI_COURSE_CREATOR_ENABLED", "true").lower() != "false",
    )
