"""
Models for course_partnerships

If you make changes to this model, be sure to create an appropriate migration
file and check it in at the same time as your model changes. To do that,

1. Go to the edx-platform dir
2. ./manage.py lms makemigrations --settings=production 
3. ./manage.py lms migrate --settings=production
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from ckeditor.fields import RichTextField
from model_utils.models import TimeStampedModel

from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from .validators import validate_bannner_extension


class Partner(TimeStampedModel):
    """
    Model for store schools and partners details
    """

    name = models.CharField(
        max_length=1024,
        db_index=True,
    )
    slug = models.SlugField(
        max_length=1024,
        db_index=True,
    )
    logo = models.ImageField(
        "logo",
        upload_to="partner/",
        help_text=_(
            "Upload only image file with .png, .jpeg, .jpg extension. Recommended image size: W 240px * H 340px"
        ),
        validators=[validate_bannner_extension],
    )
    banner = models.ImageField(
        "Banner",
        blank=True,
        null=True,
        upload_to="partner/",
        help_text=_("Upload only image file with .png, .jpeg, .jpg extension."),
        validators=[validate_bannner_extension],
    )
    content = RichTextField("Description", null=True, blank=True)
    activate_school_admin = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    class Meta:
        app_label = "course_partnerships"
        verbose_name = "Schools and Partners"
        verbose_name_plural = "Schools and Partners"


class Center(TimeStampedModel):
    """
    Model for store Center details
    """

    partner = models.ForeignKey(Partner, db_index=True, on_delete=models.CASCADE)
    name = models.CharField(
        max_length=1024,
        db_index=True,
    )
    slug = models.SlugField(
        max_length=1024,
        db_index=True,
    )
    logo = models.ImageField(
        "logo",
        upload_to="center/",
        help_text=_(
            "Upload only image file with .png, .jpeg, .jpg extension. Recommended image size: W 240px * H 340px"
        ),
        validators=[validate_bannner_extension],
    )
    banner = models.ImageField(
        "Banner",
        blank=True,
        null=True,
        upload_to="center/",
        help_text=_("Upload only image file with .png, .jpeg, .jpg extension."),
        validators=[validate_bannner_extension],
    )
    content = RichTextField("Description", null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        app_label = "course_partnerships"
        verbose_name = "Centers"
        verbose_name_plural = "Centers"


class Category(TimeStampedModel):
    """
    Model for store course categories details
    """

    name = models.CharField(max_length=100)
    partner = models.ForeignKey(Partner, null=True, blank=True, db_index=True, on_delete=models.CASCADE)
    show_on_homepage = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    class Meta:
        app_label = "course_partnerships"
        verbose_name = "Course Categories"
        verbose_name_plural = "Course Categories"


class EnhancedCourse(TimeStampedModel):
    """
    Model for store course releted extra details
    """

    course = models.OneToOneField(
        CourseOverview,
        db_constraint=False,
        db_index=True,
        on_delete=models.CASCADE,
    )
    partner = models.ForeignKey(Partner, null=True, blank=True, db_index=True, on_delete=models.SET(""))
    center = models.ForeignKey(Center, null=True, blank=True, db_index=True, on_delete=models.SET(""))
    category = models.ForeignKey(Category, null=True, blank=True, db_index=True, on_delete=models.SET(""))

    class Meta:
        app_label = "course_partnerships"

    def __str__(self):
        return f"{self.course_id}"

    @classmethod
    def create_or_update(cls, course_id):
        """
        Create or update course detailss.
        """
        course, created = cls.objects.get_or_create(course_id=course_id)
        course.save()
