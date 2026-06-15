from django.contrib import admin

from .models import ChatMessage, ChatSession, UploadedMaterial


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ("role", "content", "created")
    can_delete = False


class UploadedMaterialInline(admin.TabularInline):
    model = UploadedMaterial
    extra = 0
    readonly_fields = ("source_type", "name", "created")
    can_delete = False


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "course_id", "status", "modified")
    list_filter = ("status",)
    search_fields = ("user__username", "course_id")
    readonly_fields = ("created", "modified")
    inlines = (ChatMessageInline, UploadedMaterialInline)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "created")
    list_filter = ("role",)
    search_fields = ("content",)


@admin.register(UploadedMaterial)
class UploadedMaterialAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "source_type", "name", "created")
    list_filter = ("source_type",)
    search_fields = ("name",)
