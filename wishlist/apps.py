"""
Wishlist - App Configuration
"""

import logging

from django.apps import AppConfig

log = logging.getLogger(__name__)


class WishlistConfig(AppConfig):
    name = "wishlist"
    label = "wishlist"
    verbose_name = "Course Wishlist"

    plugin_app = {
        "url_config": {
            "lms.djangoapp": {
                "namespace": name,
                "regex": "^",
                "relative_path": "urls",
            }
        },
        "settings_config": {
            "lms.djangoapp": {
                "common": {"relative_path": "settings.common"},
            }
        },
    }

    def ready(self):
        """
        Connect signal handlers and perform any necessary initialization.
        """
        from django.conf import settings
        
        # Only proceed if Django is fully configured
        if not settings.configured:
            return

        try:
            # Only import signals if we're in LMS context
            if getattr(settings, 'SERVICE_VARIANT', None) == 'lms':
                from .signals import handlers
                log.info(f"{self.label} is ready with signals connected.")
        except ImportError as e:
            log.warning(f"Could not import signal handlers for {self.label}: {str(e)}")
        except Exception as e:
            log.exception(f"Error initializing {self.label}: {str(e)}")
