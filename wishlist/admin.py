from django.contrib import admin
from .models import *


class WishlistAdmin(admin.ModelAdmin):
    list_display = ["user", "course"]
    search_fields = ["user__username", "user__email"]


admin.site.register(Wishlist, WishlistAdmin)
