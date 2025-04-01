"""
    Manage signal handlers here
"""

import logging

from django.dispatch import receiver
from django.db.models.signals import post_save
from xmodule.modulestore.django import SignalHandler

from ..models import EnhancedCourse

log = logging.getLogger(__name__)


@receiver(SignalHandler.course_published)
def course_publish_signal_handler(sender, course_key, **kwargs):
    """
    Receives publishing signal and update it into course manage
    """
    course, created = EnhancedCourse.objects.get_or_create(course_id=course_key)


@receiver(SignalHandler.course_deleted)
def _listen_for_course_delete(sender, course_key, **kwargs):  # pylint: disable=unused-argument
    """
    Catches the signal that a course has been deleted from Studio and
    invalidates the corresponding Course cache entry if one exists.
    """
    EnhancedCourse.objects.filter(course_id=course_key).delete()
