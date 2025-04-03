"""
API Views for Wishlist functionality with enhanced mobile authentication
"""
from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from rest_framework.exceptions import ValidationError, NotFound
from rest_framework_jwt.authentication import JSONWebTokenAuthentication
from rest_framework.authentication import OAuth2Authentication
from rest_framework_jwt.settings import api_settings
from opaque_keys.edx.keys import CourseKey
from opaque_keys import InvalidKeyError
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from .models import Wishlist

# Constants for error messages and codes
ERROR_CODES = {
    "missing_course_id": "Course ID is required",
    "invalid_course_id_format": "Invalid course ID format",
    "course_not_found": "Course not found",
    "course_not_in_wishlist": "Course not found in wishlist",
}


class MobileAPIRateThrottle(UserRateThrottle):
    """
    Throttle for mobile API requests
    """

    rate = getattr(settings, "WISHLIST_RATE_LIMIT", "100/hour")


class WishlistAPIView(APIView):
    """
    Wishlist API endpoints for Open edX.

    Endpoints:
        GET /api/v1/wishlist/
            - List all wishlisted courses for the authenticated user
            - Returns: List of course objects with details

        POST /api/v1/wishlist/
            - Add a course to wishlist
            - Required data: {"course_id": "course-v1:edX+DemoX+Demo_Course"}
            - Returns: Created wishlist item details

        DELETE /api/v1/wishlist/{course_id}/
            - Remove a course from wishlist
            - Returns: 204 No Content on success

    Authentication:
        - JWT token required
        - OAuth2 supported
        - Rate limited to 100 requests per hour
    """

    authentication_classes = (JSONWebTokenAuthentication, OAuth2Authentication)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (MobileAPIRateThrottle,)

    def get_course_or_404(self, course_id):
        """
        Helper method to get course or raise 404
        """
        try:
            course_key = CourseKey.from_string(course_id)
            return CourseOverview.get_from_id(course_key)
        except (InvalidKeyError, CourseOverview.DoesNotExist):
            raise NotFound(f"Course with id {course_id} not found")

    def dispatch(self, request, *args, **kwargs):
        """
        Add security headers to response
        """
        response = super().dispatch(request, *args, **kwargs)
        response["X-Frame-Options"] = "DENY"
        response["X-Content-Type-Options"] = "nosniff"
        response["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response["Content-Security-Policy"] = "default-src 'self'"

        # Handle CORS properly
        origin = request.headers.get("Origin")
        if origin in getattr(settings, "CORS_ORIGIN_WHITELIST", []):
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"

        return response

    def get(self, request):
        """
        Get all wishlisted courses for the current user

        Returns:
            Response with list of wishlisted courses
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

        Request Body:
            course_id: string (required) - The ID of the course to add

        Returns:
            Response with created wishlist entry or error message
        """
        course_id = request.data.get("course_id")
        if not course_id:
            raise ValidationError(ERROR_CODES["missing_course_id"])

        try:
            course = self.get_course_or_404(course_id)
        except InvalidKeyError:
            raise ValidationError(ERROR_CODES["invalid_course_id_format"])

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

        Args:
            course_id: string - The ID of the course to remove

        Returns:
            Response with success or error message
        """
        try:
            course_key = CourseKey.from_string(course_id)
        except InvalidKeyError:
            raise ValidationError(ERROR_CODES["invalid_course_id_format"])

        deleted, _ = Wishlist.objects.filter(user=request.user, course_id=course_key).delete()

        if deleted:
            return Response({"code": "course_removed"}, status=status.HTTP_204_NO_CONTENT)
        raise NotFound(ERROR_CODES["course_not_in_wishlist"])

    def options(self, request, *args, **kwargs):
        """
        Handle OPTIONS requests for CORS preflight
        """
        response = Response()
        response["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response
