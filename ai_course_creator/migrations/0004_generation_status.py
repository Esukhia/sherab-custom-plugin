from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_course_creator", "0003_chatsession_current_phase"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="generation_status",
            field=models.CharField(
                choices=[
                    ("idle", "Idle"),
                    ("generating", "Generating content"),
                    ("writing", "Writing to course"),
                    ("done", "Done"),
                    ("failed", "Failed"),
                ],
                default="idle",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="chatsession",
            name="generation_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="chatsession",
            name="created_section_locators",
            field=models.JSONField(blank=True, default=list, null=True),
        ),
    ]
