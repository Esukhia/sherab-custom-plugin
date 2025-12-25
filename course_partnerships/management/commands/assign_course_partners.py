from django.core.management.base import BaseCommand
from organizations.models import OrganizationCourse

from course_partnerships.models import EnhancedCourse, PartnerOrganizationMapping


class Command(BaseCommand):
    """
    Command to auto-assign partners to courses based on organization mappings.

    Example usage:
        ./manage.py assign_course_partners
    """
    help = "Auto-assign partners to courses based on organization mappings"

    def handle(self, *args, **options):
        courses_updated = 0

        # Get all EnhancedCourses without partners
        courses = EnhancedCourse.objects.filter(partner__isnull=True)

        for enhanced_course in courses:
            try:
                # Get organization for this course
                org_course = OrganizationCourse.objects.filter(course_id=str(enhanced_course.course_id)).first()

                if org_course:
                    # Find partner mapping
                    mapping = PartnerOrganizationMapping.objects.filter(organization=org_course.organization).first()

                    if mapping:
                        enhanced_course.partner = mapping.partner
                        enhanced_course.save()
                        courses_updated += 1
                        self.stdout.write(
                            self.style.SUCCESS(f"Assigned {mapping.partner.name} to {enhanced_course.course_id}")
                        )
            except Exception as e:  # pylint: disable=broad-exception-caught
                self.stdout.write(self.style.ERROR(f"Error processing {enhanced_course.course_id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Successfully updated {courses_updated} courses"))
