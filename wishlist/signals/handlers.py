"""
    Manage signal handlers here
"""

import logging

from django.dispatch import receiver
from django.db.models.signals import post_save
from xmodule.modulestore.django import SignalHandler


log = logging.getLogger(__name__)
