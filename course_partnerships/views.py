import logging
from django.views.generic import View
from django.db.models import Count
from django.conf import settings
from django.utils.decorators import method_decorator
from django.http import Http404
from common.djangoapps.util.json_request import JsonResponse
from common.djangoapps.edxmako.shortcuts import render_to_response
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview

from .models import *

log = logging.getLogger(__name__)


class PartnerDetailView(View):
    """
    View for Partner Details
    """

    def get(self, request, slug):
        try:
            partner = Partner.objects.get(slug=slug)
        except Exception as e:
            raise Http404

        centers = Center.objects.filter(partner=partner)
        category_ids = CourseOverview.objects.filter(enhancedcourse__partner=partner).values_list(
            "enhancedcourse__category", flat=True
        )
        categories = (
            Category.objects.filter(id__in=category_ids)
            .annotate(num_courses=Count("enhancedcourse"))
            .filter(num_courses__gt=0)
        )
        partner_courses = CourseOverview.objects.filter(enhancedcourse__partner=partner)
        context = {"partner": partner, "centers": centers, "categories": categories, "partner_courses": partner_courses}
        return render_to_response("course_partnerships/partner-details.html", context)


class CenterDetailView(View):
    """
    View for Center Details
    """

    def get(self, request, partner_slug, center_slug):
        try:
            partner = Partner.objects.get(slug=partner_slug)
        except Exception as e:
            raise Http404

        try:
            center = Center.objects.get(partner=partner, slug=center_slug)
        except Exception as e:
            raise Http404

        category_ids = CourseOverview.objects.filter(enhancedcourse__partner=partner).values_list(
            "enhancedcourse__category", flat=True
        )
        categories = (
            Category.objects.filter(id__in=category_ids)
            .annotate(num_courses=Count("enhancedcourse"))
            .filter(num_courses__gt=0)
        )
        context = {"partner": partner, "center": center, "categories": categories}
        return render_to_response("course_partnerships/center-details.html", context)
