"""
API Views for Wishlist functionality with enhanced mobile authentication
"""

from datetime import timedelta
from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from rest_framework_jwt.authentication import JSONWebTokenAuthentication
from rest_framework.authentication import OAuth2Authentication
from rest_framework_jwt.settings import api_settings
from opaque_keys.edx.keys import CourseKey
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from .models import Wishlist


class MobileAPIRateThrottle(UserRateThrottle):
    """
    Throttle for mobile API requests
    """

    rate = "100/hour"


class WishlistAPIView(APIView):
    """
    API View for handling wishlist operations with enhanced mobile support
    """

    authentication_classes = (JSONWebTokenAuthentication, OAuth2Authentication)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (MobileAPIRateThrottle,)

    def dispatch(self, request, *args, **kwargs):
        """
        Add security headers to response
        """
        response = super().dispatch(request, *args, **kwargs)
        response["X-Frame-Options"] = "DENY"
        response["X-Content-Type-Options"] = "nosniff"
        response["Access-Control-Allow-Origin"] = settings.CORS_ORIGIN_WHITELIST
        return response

    def get(self, request):
        """
        Get all wishlisted courses for the current user
        """
        wishlisted_courses = Wishlist.objects.filter(user=request.user).select_related("course")
        response_data = [
            {
                "course_id": str(item.course.id),
                "course_name": item.course.display_name,
                "course_image_url": item.course.course_image_url,
                "course_org": item.course.org,
                "created": item.created.isoformat(),
            }
            for item in wishlisted_courses
        ]
        return Response(response_data)

    def post(self, request):
        """
        Add a course to wishlist
        """
        course_id = request.data.get("course_id")
        if not course_id:
            return Response(
                {"error": "Course ID is required", "code": "missing_course_id"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            course_key = CourseKey.from_string(course_id)
            course = CourseOverview.get_from_id(course_key)
        except Exception as e:
            return Response(
                {"error": "Invalid course ID", "code": "invalid_course_id"}, status=status.HTTP_400_BAD_REQUEST
            )

        wishlist_item, created = Wishlist.objects.get_or_create(user=request.user, course=course)

        response_data = {
            "course_id": str(course.id),
            "course_name": course.display_name,
            "created": created,
            "message": "Course added to wishlist" if created else "Course already in wishlist",
            "code": "course_added" if created else "course_exists",
        }
        return Response(response_data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, course_id):
        """
        Remove a course from wishlist
        """
        try:
            course_key = CourseKey.from_string(course_id)
            deleted, _ = Wishlist.objects.filter(user=request.user, course_id=course_key).delete()

            if deleted:
                return Response({"code": "course_removed"}, status=status.HTTP_204_NO_CONTENT)
            return Response(
                {"error": "Course not found in wishlist", "code": "course_not_found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": "Invalid course ID", "code": "invalid_course_id"}, status=status.HTTP_400_BAD_REQUEST
            )
