from rest_framework import serializers

from course_partnerships.models import PartnerOrganizationMapping


class PartnerOrganizationMappingSerializer(serializers.ModelSerializer):
    """
    Serializer for Partner-Organization mappings.

    Serializes:
        - partner_name (str): The name of the partner
        - logo (str): Fully-qualified URL to the partner's logo
        - organization (str): The short_name of the associated organization
    """

    partner_name = serializers.CharField(source="partner.name")
    logo = serializers.SerializerMethodField()
    organization = serializers.CharField(source="organization.short_name")

    class Meta:
        model = PartnerOrganizationMapping
        fields = ["partner_name", "logo", "organization"]

    def get_logo(self, obj):
        """
        Returns the fully-qualified URL for the partner's logo.

        Args:
            obj (PartnerOrganizationMapping): The current mapping instance.

        Returns:
            str or None: Fully-qualified logo URL if available, else None.
        """
        request = self.context.get("request")
        if obj.partner.logo and hasattr(obj.partner.logo, "url"):
            return request.build_absolute_uri(obj.partner.logo.url)
        return None
