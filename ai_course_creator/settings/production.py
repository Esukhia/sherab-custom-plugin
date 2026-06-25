"""
Production Pluggable Django App settings for ai_course_creator.
"""


def plugin_settings(settings):
    """
    Injects production settings into the Django settings object.

    The Gemini credentials (``GEMINI_API_KEY`` / ``GEMINI_MODEL``) are rendered
    into the CMS production settings from Tutor ``config.yml`` by the
    ``configuration_plugin`` patch, so there is nothing to override here beyond
    making sure the attributes exist.
    """
    if not hasattr(settings, "GEMINI_API_KEY"):
        settings.GEMINI_API_KEY = ""
    if not hasattr(settings, "GEMINI_MODEL"):
        settings.GEMINI_MODEL = "gemini-1.5-pro"
    if not hasattr(settings, "AI_COURSE_CREATOR_MAX_UPLOAD_BYTES"):
        settings.AI_COURSE_CREATOR_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
    if not hasattr(settings, "AI_COURSE_CREATOR_ENABLED"):
        settings.AI_COURSE_CREATOR_ENABLED = True
