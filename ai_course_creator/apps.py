"""
AI Course Creator (Sherab chatbot) - App Configuration.

This Studio-side (CMS) app powers a conversational AI assistant that helps
course creators design a course and then generates the real course structure
(sections / subsections / units / components) for them.
"""

import logging

from django.apps import AppConfig

from edx_django_utils.plugins import PluginSettings, PluginURLs
from openedx.core.djangoapps.plugins.constants import ProjectType, SettingsType

log = logging.getLogger(__name__)


class AiCourseCreatorConfig(AppConfig):
    name = "ai_course_creator"
    label = "ai_course_creator"

    # Title shown for this app's models group in the Django admin.
    verbose_name = "AI Course Creator"

    # This is a Studio-only feature, so it is registered for the CMS project
    # type only. See: course_partnerships/apps.py for the LMS equivalent.
    # https://edx.readthedocs.io/projects/edx-django-utils/en/latest/edx_django_utils.plugins.html
    plugin_app = {
        PluginURLs.CONFIG: {
            ProjectType.CMS: {
                PluginURLs.NAMESPACE: name,
                PluginURLs.REGEX: "^",
                PluginURLs.RELATIVE_PATH: "urls",
            }
        },
        PluginSettings.CONFIG: {
            ProjectType.CMS: {
                SettingsType.PRODUCTION: {PluginSettings.RELATIVE_PATH: "settings.production"},
                SettingsType.COMMON: {PluginSettings.RELATIVE_PATH: "settings.common"},
            }
        },
    }

    def ready(self):
        log.debug("{label} is ready.".format(label=self.label))
