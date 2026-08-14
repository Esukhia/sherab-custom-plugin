import logging

from common.djangoapps.edxmako.shortcuts import render_to_response
from django.db.models import Count
from django.http import Http404
from django.views.generic import View
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny

from .models import *
from .serializers import PartnerOrganizationMappingSerializer, PartnerSerializer

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
        course_creators = CourseCreator.objects.filter(partner=partner)
        context = {
            "partner": partner,
            "centers": centers,
            "categories": categories,
            "partner_courses": partner_courses,
            "course_creators": course_creators,
        }
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


class PublicPartnerListAPIView(ListAPIView):
    """
    Base class for the public partner listing endpoints.

    Both endpoints below are read by anonymous clients (the homepage carousel
    and the mobile app) and both are expected to return their whole list as a
    bare JSON array, so the shared settings live here:

    - authentication is skipped entirely rather than attempted and failed;
    - anonymous access is granted explicitly, so a future change to the
      platform-wide permission default can't silently lock these down;
    - the platform-wide pagination default is disabled, which would otherwise
      cap responses at PAGE_SIZE and wrap them in a
      {count, next, previous, results} envelope that no client here expects.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    pagination_class = None


class PartnerListAPIView(PublicPartnerListAPIView):
    """
    API endpoint to retrieve partner-organization mappings.

    Each entry in the response corresponds to a unique pair of:
        - Partner (name + logo)
        - Organization (short_name)

    Only mappings marked with `show_in_mobile_app=True` are returned.

    Method:
        GET

    Example Response (200 OK):
        [
            {
                "partner_name": "Partner Name",
                "logo": "https://yourdomain.com/../partner_logo.png",
                "organization": "org1"
            },
            ...
        ]
    """

    serializer_class = PartnerOrganizationMappingSerializer
    queryset = PartnerOrganizationMapping.objects.filter(show_in_mobile_app=True)


class PartnerHomepageListAPIView(PublicPartnerListAPIView):
    """
    API endpoint to retrieve all partners, for display on the homepage
    schools-and-partners carousel. Unlike PartnerListAPIView, this is not
    filtered by `show_in_mobile_app` — it mirrors the old homepage template's
    `Partner.objects.all()` behavior, since the homepage carousel and the
    mobile app's partner list serve different purposes and audiences.

    Method:
        GET

    Example Response (200 OK):
        [
            {
                "partner_name": "Partner Name",
                "logo": "https://yourdomain.com/../partner_logo.png",
                "slug": "partner-slug"
            },
            ...
        ]
    """

    serializer_class = PartnerSerializer

    # Explicit ordering keeps the carousel stable: an unordered queryset lets
    # the database return rows in any order, which can reshuffle the logos
    # between requests.
    queryset = Partner.objects.order_by("name")
