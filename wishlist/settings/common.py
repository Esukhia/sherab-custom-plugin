"""
Common Pluggable Django App settings

Handling of environment variables, see: https://django-environ.readthedocs.io/en/latest/
to convert .env to yml see: https://django-environ.readthedocs.io/en/latest/tips.html#docker-style-file-based-variables
"""

from path import Path as path
import environ
import os
from django.conf import settings
from datetime import datetime

# path to this file.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))


APP_ROOT = path(__file__).abspath().dirname().dirname()  # /blah/blah/blah/.../example_grades
REPO_ROOT = APP_ROOT.dirname()  # /blah/blah/blah/.../example-digital-learning-openedx
TEMPLATES_DIR = APP_ROOT / "templates"


def plugin_settings(settings):
    """
    Injects local settings into django settings

    see: https://stackoverflow.com/questions/56129708/how-to-force-redirect-uri-to-use-https-with-python-social-app
    """

    # settings.SOCIAL_AUTH_REDIRECT_IS_HTTPS = True
    # SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    # Wishlist specific settings
    settings.WISHLIST_RATE_LIMIT = getattr(settings, "WISHLIST_RATE_LIMIT", "100/hour")

    # JWT settings
    settings.JWT_AUTH = getattr(settings, "JWT_AUTH", {})
    settings.JWT_AUTH.update(
        {
            "JWT_VERIFY_EXPIRATION": True,
            "JWT_EXPIRATION_DELTA": datetime.timedelta(days=7),
            "JWT_ALLOW_REFRESH": True,
            "JWT_REFRESH_EXPIRATION_DELTA": datetime.timedelta(days=7),
        }
    )

    # REST Framework settings
    settings.REST_FRAMEWORK = getattr(settings, "REST_FRAMEWORK", {})
    settings.REST_FRAMEWORK.update(
        {
            "DEFAULT_AUTHENTICATION_CLASSES": [
                "rest_framework_jwt.authentication.JSONWebTokenAuthentication",
                "rest_framework.authentication.SessionAuthentication",
                "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
            ],
            "DEFAULT_PERMISSION_CLASSES": [
                "rest_framework.permissions.IsAuthenticated",
            ],
            "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
            "DEFAULT_VERSION": "v1",
            "ALLOWED_VERSIONS": ["v1"],
            "VERSION_PARAM": "version",
        }
    )

    # CORS settings
    settings.CORS_ALLOW_CREDENTIALS = True
    settings.CORS_ORIGIN_WHITELIST = getattr(settings, "CORS_ORIGIN_WHITELIST", [])
    settings.CORS_ALLOW_HEADERS = list(getattr(settings, "CORS_ALLOW_HEADERS", []))
    settings.CORS_ALLOW_HEADERS.extend(
        [
            "accept",
            "accept-encoding",
            "authorization",
            "content-type",
            "origin",
            "user-agent",
            "x-csrftoken",
            "x-requested-with",
        ]
    )
