"""
Defines the URL routes for this app.
"""

from django.conf import settings
from django.urls import path, re_path
from django.conf.urls import include

from .views import *

app_name = "wishlist"


urlpatterns = [
    path("wishlist/change-status/", WishListChangeView.as_view(), name="change-wishlist-status"),
    path("wishlist/", wishlist_view, name="wishlist-view"),
]
