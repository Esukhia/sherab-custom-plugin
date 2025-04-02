"""
JWT settings for mobile API authentication
"""

from datetime import timedelta

JWT_AUTH = {
    "JWT_EXPIRATION_DELTA": timedelta(days=7),
    "JWT_REFRESH_EXPIRATION_DELTA": timedelta(days=30),
    "JWT_ALLOW_REFRESH": True,
    "JWT_REFRESH_TOKEN_REUSE": False,
    "JWT_AUTH_HEADER_PREFIX": "Bearer",
    "JWT_AUTH_COOKIE": None,
    "JWT_RESPONSE_PAYLOAD_HANDLER": "wishlist.utils.jwt_response_handler",
}
