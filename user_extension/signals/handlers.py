"""
    Manage signal handlers here
"""

import logging

from django.dispatch import receiver
from django.db.models.signals import post_save
from django.contrib.auth.models import User
from xmodule.modulestore.django import SignalHandler
from ..models import ExtendedUserProfile

log = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def sync_extended_profile(sender, instance, created, **kwargs):
    """
    On new user creation create object for ExtendedUserProfile
    """
    if created:
        ExtendedUserProfile.objects.create(user=instance)
