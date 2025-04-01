import os

from django.core.exceptions import ValidationError


def validate_bannner_extension(value):
    """
    Validate image file with extenstions
    """
    ext = os.path.splitext(value.name)[1]
    valid_extensions = [".png", ".jpg", ".jpeg"]
    if not ext.lower() in valid_extensions:
        raise ValidationError("Unsupported file extension.")


def validate_video_extension(value):
    """
    Validate video file with .mp4 extensions
    """
    ext = os.path.splitext(value.name)[1]
    valid_extensions = [".mp4"]
    if not ext.lower() in valid_extensions:
        raise ValidationError("Unsupported file extension.")
