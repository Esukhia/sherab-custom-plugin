from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_course_creator", "0002_utf8mb4"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="current_phase",
            field=models.PositiveSmallIntegerField(default=1),
        ),
    ]
