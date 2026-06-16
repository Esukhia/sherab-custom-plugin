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
    if not hasattr(settings, "GROQ_API_KEY"):
        settings.GROQ_API_KEY = ""
    if not hasattr(settings, "GROQ_MODEL"):
        settings.GROQ_MODEL = "llama-3.3-70b-versatile"
    if not hasattr(settings, "AI_COURSE_CREATOR_MAX_UPLOAD_BYTES"):
        settings.AI_COURSE_CREATOR_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
