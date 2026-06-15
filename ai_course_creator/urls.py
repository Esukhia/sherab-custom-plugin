"""
URL routes for the AI course-creator chatbot (CMS).

Mounted at the site root (REGEX "^") via the plugin config in apps.py, so the
absolute paths are e.g. ``/api/ai-course-creator/chat/`` on the Studio host.
"""

from django.urls import path

from .views import (
    ApplyOutlineView,
    ChatView,
    MaterialDetailView,
    SessionView,
    UploadMaterialView,
)

app_name = "ai_course_creator"

urlpatterns = [
    path("api/ai-course-creator/chat/", ChatView.as_view(), name="chat"),
    path("api/ai-course-creator/upload/", UploadMaterialView.as_view(), name="upload"),
    path("api/ai-course-creator/material/<int:pk>/", MaterialDetailView.as_view(), name="material-detail"),
    path("api/ai-course-creator/apply/", ApplyOutlineView.as_view(), name="apply"),
    path("api/ai-course-creator/session/", SessionView.as_view(), name="session"),
]
