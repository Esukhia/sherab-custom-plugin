"""
Common Pluggable Django App settings for ai_course_creator.
"""

import os


def plugin_settings(settings):
    """
    Injects AI Course Creator settings into the Django settings object.

    The Gemini credentials are normally injected into CMS settings from the
    Tutor ``config.yml`` via the ``configuration_plugin`` patch. We fall back to
    environment variables / sensible defaults so the app also works in tests and
    in environments where the patch is not applied.
    """
    settings.GROQ_API_KEY = getattr(
        settings, "GROQ_API_KEY", os.environ.get("GROQ_API_KEY", "")
    )
    settings.GROQ_MODEL = getattr(
        settings, "GROQ_MODEL", os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    )

    # Hard limits for uploaded course materials (bytes). 25 MB by default.
    settings.AI_COURSE_CREATOR_MAX_UPLOAD_BYTES = getattr(
        settings, "AI_COURSE_CREATOR_MAX_UPLOAD_BYTES", 25 * 1024 * 1024
    )
