"""
Convert free-text columns to utf8mb4 so emoji (👋, 🎥, …) can be stored.

The Sherab persona and generated content are full of 4-byte emoji. The default
MySQL charset on Open edX is 3-byte ``utf8``, which rejects them with
"Incorrect string value". This migration widens the relevant columns to
``utf8mb4`` on MySQL; it is a no-op on other backends (e.g. SQLite in tests).
"""

from django.db import migrations

UTF8MB4 = "utf8mb4"
COLLATION = "utf8mb4_unicode_ci"

# (table, column, column definition) tuples to convert.
COLUMNS = [
    ("ai_course_creator_chatmessage", "content", "LONGTEXT"),
    ("ai_course_creator_uploadedmaterial", "extracted_text", "LONGTEXT"),
    ("ai_course_creator_uploadedmaterial", "name", "VARCHAR(512)"),
]


def to_utf8mb4(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table, column, definition in COLUMNS:
            cursor.execute(
                f"ALTER TABLE {table} MODIFY {column} {definition} "
                f"CHARACTER SET {UTF8MB4} COLLATE {COLLATION} NOT NULL"
            )


def noop_reverse(apps, schema_editor):
    # We intentionally do not convert back to utf8 (would lose data / serve no purpose).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("ai_course_creator", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(to_utf8mb4, noop_reverse),
    ]
