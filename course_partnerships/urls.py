"""
Defines the URL routes for this app.
"""

from django.conf import settings
from django.urls import path, re_path
from django.conf.urls import include

from .views import *

app_name = "course_partnerships"


urlpatterns = [
    path("schools/<slug:slug>/", PartnerDetailView.as_view(), name="partner-detail"),
    path("schools/<slug:partner_slug>/<slug:center_slug>/", CenterDetailView.as_view(), name="center-detail"),
]
