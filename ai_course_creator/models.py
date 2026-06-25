"""
Models for ai_course_creator.

If you make changes to these models, create an appropriate migration file and
check it in at the same time. To do that:

1. Go to the edx-platform dir
2. ./manage.py cms makemigrations ai_course_creator --settings=production
3. ./manage.py cms migrate --settings=production
"""

from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

User = get_user_model()


class ChatSession(TimeStampedModel):
    """
    One AI course-design conversation, tied to a (user, course) pair.

    A creator opens the chatbot from an empty course outline; the conversation
    they have with "Sherab" is stored here so the modal can resume, and the
    final generated outline JSON is cached on ``course_json``.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        GENERATED = "generated", _("Course generated")
        APPLIED = "applied", _("Applied to course")

    class GenerationStatus(models.TextChoices):
        IDLE = "idle", _("Idle")
        GENERATING = "generating", _("Generating content")
        WRITING = "writing", _("Writing to course")
        DONE = "done", _("Done")
        FAILED = "failed", _("Failed")

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="ai_course_sessions",
    )
    # Stored as a string (course key) rather than a FK because the course may
    # not yet have a CourseOverview row when the session starts.
    course_id = models.CharField(max_length=255, db_index=True)
    # Empty for the whole-course creator flow. For the per-section editor it
    # holds the chapter (section) usage key, so each section gets its own
    # conversation. Part of the uniqueness key below.
    section_locator = models.CharField(max_length=255, db_index=True, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    # The full generated course outline (assembled by the generator service).
    course_json = models.JSONField(null=True, blank=True)
    # Current display phase (1–4): 1=Learner, 2=Transformation, 3=Assessment, 4=Generate
    current_phase = models.PositiveSmallIntegerField(default=1)
    # Course-generation lifecycle (separate from the chat ``status`` above).
    generation_status = models.CharField(
        max_length=20,
        choices=GenerationStatus.choices,
        default=GenerationStatus.IDLE,
    )
    # Last generation error message (surfaced to the UI for the retry path).
    generation_error = models.TextField(blank=True, default="")
    # Usage-key strings of the chapters created in the last write, for rollback
    # and to detect a course that already has Sherab-built content.
    created_section_locators = models.JSONField(null=True, blank=True, default=list)

    class Meta:
        app_label = "ai_course_creator"
        verbose_name = "Chat Session"
        verbose_name_plural = "Chat Sessions"
        # One session per user+course+section. The creator flow uses an empty
        # section_locator; each per-section editor conversation uses the
        # chapter's usage key.
        unique_together = ("user", "course_id", "section_locator")

    def __str__(self):
        return f"{self.user.username} · {self.course_id}"


class ChatMessage(TimeStampedModel):
    """A single message in a :class:`ChatSession`."""

    class Role(models.TextChoices):
        USER = "user", _("User")
        ASSISTANT = "assistant", _("Assistant")

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="messages",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()

    class Meta:
        app_label = "ai_course_creator"
        verbose_name = "Chat Message"
        verbose_name_plural = "Chat Messages"
        ordering = ["created", "id"]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"


class UploadedMaterial(TimeStampedModel):
    """
    A piece of raw course material the creator shared during Phase 3.

    Files are parsed to plain text on upload (``extracted_text``); the binary is
    not retained. Pasted text and links are stored the same way.
    """

    class SourceType(models.TextChoices):
        FILE = "file", _("Uploaded file")
        LINK = "link", _("Link")
        TEXT = "text", _("Pasted text")

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="materials",
    )
    source_type = models.CharField(
        max_length=16,
        choices=SourceType.choices,
        default=SourceType.FILE,
    )
    name = models.CharField(max_length=512, help_text=_("Original filename, URL, or a short label."))
    extracted_text = models.TextField(blank=True, default="")

    class Meta:
        app_label = "ai_course_creator"
        verbose_name = "Uploaded Material"
        verbose_name_plural = "Uploaded Materials"
        ordering = ["created", "id"]

    def __str__(self):
        return f"{self.get_source_type_display()}: {self.name}"
