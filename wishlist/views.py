import logging
from django.db import transaction
from django.conf import settings
from django.views.generic import View
from django.utils.decorators import method_decorator
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.utils.translation import gettext as _
from django.contrib.auth.decorators import login_required
from .models import Wishlist

log = logging.getLogger(__name__)


class WishListChangeView(View):
    """
    View for Partner Details
    """

    def post(self, request):
        # Get the user
        user = request.user

        # Ensure the user is authenticated
        if not user.is_authenticated:
            return HttpResponseForbidden()

        action = request.POST.get("wishlist_action")
        if "course_id" not in request.POST:
            return HttpResponseBadRequest(_("Course id not specified"))

        try:
            # Lazy imports to avoid initialization issues
            from opaque_keys.edx.keys import CourseKey
            from openedx.core.djangoapps.content.course_overviews.models import CourseOverview

            course_key = CourseKey.from_string(request.POST.get("course_id"))
            course = CourseOverview.get_from_id(course_key)
        except Exception as e:
            log.warning(
                "User %s tried to %s with invalid course id: %s",
                user.username,
                action,
                request.POST.get("course_id"),
            )
            return HttpResponseBadRequest(_("Invalid course id"))

        if action == "add":
            wishlist_item, created = Wishlist.objects.get_or_create(user=request.user, course=course)

            if created:
                response_msg = _("Course {} added to your wishlist.".format(course.display_name))
            else:
                response_msg = _("Course {} is already in your wishlist.".format(course.display_name))
        elif action == "remove":
            Wishlist.objects.filter(user=request.user, course=course).delete()
            response_msg = _("Course {} removed from your wishlist.".format(course.display_name))

        return HttpResponse(response_msg)


@login_required
def wishlist_view(request):
    # Lazy import to avoid initialization issues
    from common.djangoapps.edxmako.shortcuts import render_to_response

    # Fetch all wishlisted courses for the logged-in user
    wishlisted_courses = Wishlist.objects.filter(user=request.user).select_related("course")

    context = {
        "wishlisted_courses": wishlisted_courses,
    }

    return render_to_response("wishlist/wishlist.html", context)
