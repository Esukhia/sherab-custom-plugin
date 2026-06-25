from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_course_creator", "0004_generation_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="section_locator",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
        migrations.AlterUniqueTogether(
            name="chatsession",
            unique_together={("user", "course_id", "section_locator")},
        ),
    ]
