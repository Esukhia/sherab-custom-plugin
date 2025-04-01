from django.contrib import admin
from .models import *


class PartnerAdmin(admin.ModelAdmin):
    list_display = ["name", "activate_school_admin"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ("name",)}


class CenterAdmin(admin.ModelAdmin):
    list_display = ["name", "partner"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ("name",)}


class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "partner", "show_on_homepage"]
    search_fields = ["name"]
    raw_id_fields = ["partner"]


class EnhancedCourseAdmin(admin.ModelAdmin):
    list_display = ["course", "partner", "center", "category"]
    search_fields = ["course_id"]
    raw_id_fields = ["course", "partner", "center", "category"]


admin.site.register(Partner, PartnerAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(EnhancedCourse, EnhancedCourseAdmin)
admin.site.register(Center, CenterAdmin)
