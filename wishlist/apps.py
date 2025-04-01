"""
Wishlist - App Configuration
"""

import logging

from django.apps import AppConfig

from edx_django_utils.plugins import PluginSettings, PluginURLs
from openedx.core.djangoapps.plugins.constants import ProjectType, SettingsType

log = logging.getLogger(__name__)


class WishlistConfig(AppConfig):
    name = "wishlist"
    label = "wishlist"

    # This is the text that appears in the Django admin console in all caps
    # as the title box encapsulating all Django app models that are registered
    # in admin.py.
    verbose_name = "Course Wishlist"

    # See: https://edx.readthedocs.io/projects/edx-django-utils/en/latest/edx_django_utils.plugins.html
    plugin_app = {
        PluginURLs.CONFIG: {
            ProjectType.LMS: {
                PluginURLs.NAMESPACE: name,
                PluginURLs.REGEX: "^",
                PluginURLs.RELATIVE_PATH: "urls",
            }
        },
        PluginSettings.CONFIG: {
            ProjectType.LMS: {
                # uncomment these to activate
                SettingsType.PRODUCTION: {PluginSettings.RELATIVE_PATH: "settings.production"},
                SettingsType.COMMON: {PluginSettings.RELATIVE_PATH: "settings.common"},
            }
        },
    }

    def ready(self):
        from .signals import handlers

        log.debug("{label} is ready.".format(label=self.label))
