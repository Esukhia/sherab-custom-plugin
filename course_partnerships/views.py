import logging

from common.djangoapps.edxmako.shortcuts import render_to_response
from django.db.models import Count
from django.http import Http404
from django.views.generic import View
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import *
from .serializers import PartnerOrganizationMappingSerializer

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


class PartnerListAPIView(APIView):
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

    # This API is intended for public access, so no authentication is required.
    authentication_classes = []

    def get(self, request):
        """
        Handles GET requests to retrieve visible partner-organization mappings.

        Args:
            request (HttpRequest): The incoming HTTP request.

        Returns:
            Response: A list of serialized mappings.
        """
        mappings = PartnerOrganizationMapping.objects.filter(show_in_mobile_app=True)
        serializer = PartnerOrganizationMappingSerializer(mappings, many=True, context={"request": request})
        return Response(serializer.data)
