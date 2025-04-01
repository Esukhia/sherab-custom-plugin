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
from model_utils.models import TimeStampedModel

from course_partnerships.models import Partner


class ExtendedUserProfile(TimeStampedModel):
    user = models.OneToOneField(
        User, unique=True, db_index=True, related_name="extended_profile", on_delete=models.CASCADE
    )
    partner = models.ForeignKey(
        Partner,
        null=True,
        blank=True,
        db_index=True,
        on_delete=models.SET_NULL,
        related_name="admins",
        help_text=_("The partner organization this user is an admin of."),
    )

    class Meta:
        verbose_name = "Extended User Profile"
        verbose_name_plural = "Extended User Profile"

    def __str__(self):
        return self.user.username
