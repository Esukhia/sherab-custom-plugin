import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatSession",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now, editable=False, verbose_name="created"
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now, editable=False, verbose_name="modified"
                    ),
                ),
                ("course_id", models.CharField(db_index=True, max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("generated", "Course generated"),
                            ("applied", "Applied to course"),
                        ],
                        default="active",
                        max_length=20,
                    ),
                ),
                ("course_json", models.JSONField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_course_sessions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Chat Session",
                "verbose_name_plural": "Chat Sessions",
                "unique_together": {("user", "course_id")},
            },
        ),
        migrations.CreateModel(
            name="UploadedMaterial",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now, editable=False, verbose_name="created"
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now, editable=False, verbose_name="modified"
                    ),
                ),
                (
                    "source_type",
                    models.CharField(
                        choices=[("file", "Uploaded file"), ("link", "Link"), ("text", "Pasted text")],
                        default="file",
                        max_length=16,
                    ),
                ),
                ("name", models.CharField(help_text="Original filename, URL, or a short label.", max_length=512)),
                ("extracted_text", models.TextField(blank=True, default="")),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="materials",
                        to="ai_course_creator.chatsession",
                    ),
                ),
            ],
            options={
                "verbose_name": "Uploaded Material",
                "verbose_name_plural": "Uploaded Materials",
                "ordering": ["created", "id"],
            },
        ),
        migrations.CreateModel(
            name="ChatMessage",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now, editable=False, verbose_name="created"
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now, editable=False, verbose_name="modified"
                    ),
                ),
                ("role", models.CharField(choices=[("user", "User"), ("assistant", "Assistant")], max_length=16)),
                ("content", models.TextField()),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="ai_course_creator.chatsession",
                    ),
                ),
            ],
            options={
                "verbose_name": "Chat Message",
                "verbose_name_plural": "Chat Messages",
                "ordering": ["created", "id"],
            },
        ),
    ]
