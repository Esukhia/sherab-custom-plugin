from rest_framework import serializers

from course_partnerships.models import Partner, PartnerOrganizationMapping


class LogoUrlMixin:
    """
    Shared resolution of a partner logo ImageField to a fully-qualified URL.

    Used by every serializer that exposes a partner logo, so the null-handling
    and absolute-URL rules stay identical across endpoints.
    """

    def logo_url(self, logo):
        """
        Return a fully-qualified URL for the given logo, or None if unset.

        Args:
            logo (ImageFieldFile or None): The logo field to resolve.

        Returns:
            str or None: Fully-qualified logo URL if available, else None.
        """
        if not logo or not hasattr(logo, "url"):
            return None

        request = self.context.get("request")
        # Storage backends that serve from an external host (e.g. S3) already
        # return an absolute URL, in which case build_absolute_uri is a no-op.
        return request.build_absolute_uri(logo.url) if request else logo.url


class PartnerSerializer(LogoUrlMixin, serializers.ModelSerializer):
    """
    Serializer for partners, used for full (unfiltered) partner listings such
    as the homepage schools-and-partners carousel.

    Serializes:
        - partner_name (str): The partner's name
        - logo (str): Fully-qualified URL to the partner's logo
        - slug (str): The partner's slug, used to link to its school page (/schools/<slug>/)
    """

    partner_name = serializers.CharField(source="name")
    logo = serializers.SerializerMethodField()

    class Meta:
        model = Partner
        fields = ["partner_name", "logo", "slug"]

    def get_logo(self, obj):
        """
        Returns the fully-qualified URL for the partner's logo.

        Args:
            obj (Partner): Partner instance

        Returns:
            str or None: Fully-qualified logo URL if available, else None
        """
        return self.logo_url(obj.logo)


class PartnerOrganizationMappingSerializer(LogoUrlMixin, serializers.ModelSerializer):
    """
    Serializer for Partner-Organization mappings.

    Serializes:
        - partner_name (str): Display name if provided, otherwise default partner name
        - logo (str): Fully-qualified URL to the partner's logo
        - organization (str): The short_name of the associated organization
    """

    partner_name = serializers.SerializerMethodField()
    logo = serializers.SerializerMethodField()
    organization = serializers.CharField(source="organization.short_name")

    class Meta:
        model = PartnerOrganizationMapping
        fields = ["partner_name", "logo", "organization"]

    def get_partner_name(self, obj):
        """
        Return the custom display_name if present, otherwise default partner name.

        Args:
            obj (PartnerOrganizationMapping): Mapping instance

        Returns:
            str: Display name
        """
        return obj.display_name or obj.partner.name

    def get_logo(self, obj):
        """
        Returns the fully-qualified URL for the partner's logo.

        Args:
            obj (PartnerOrganizationMapping): Mapping instance

        Returns:
            str or None: Fully-qualified logo URL if available, else None
        """
        return self.logo_url(obj.partner.logo)
