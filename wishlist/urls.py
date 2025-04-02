"""
Defines the URL routes for this app.
"""

from django.conf import settings
from django.urls import path, re_path
from django.conf.urls import include
from rest_framework_jwt.views import obtain_jwt_token, refresh_jwt_token, verify_jwt_token

from .views import *
from .api import WishlistAPIView

app_name = "wishlist"

# API URL patterns for mobile app
api_urlpatterns = [
    # JWT Authentication endpoints
    path("auth/token/", obtain_jwt_token, name="token_obtain"),
    path("auth/token/refresh/", refresh_jwt_token, name="token_refresh"),
    path("auth/token/verify/", verify_jwt_token, name="token_verify"),
    # Wishlist endpoints
    path("wishlist/", WishlistAPIView.as_view(), name="wishlist-api"),
    path("wishlist/<str:course_id>/", WishlistAPIView.as_view(), name="wishlist-api-detail"),
]

# Web interface URL patterns
web_urlpatterns = [
    path("wishlist/change-status/", WishListChangeView.as_view(), name="change-wishlist-status"),
    path("wishlist/", wishlist_view, name="wishlist-view"),
]

# Combine all patterns
urlpatterns = web_urlpatterns + [
    path("api/v1/", include((api_urlpatterns, "api"), namespace="v1")),
]
