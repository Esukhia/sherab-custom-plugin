from rest_framework import serializers

from .models import ChatMessage, ChatSession, UploadedMaterial
from .services.llm_client import (
    extract_section_edits,
    strip_course_json,
    strip_phase_marker,
    strip_section_edits,
)


class ChatMessageSerializer(serializers.ModelSerializer):
    """Serialize a chat message, hiding embedded COURSE_JSON / SECTION_EDITS from the client."""

    content = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "created"]

    def get_content(self, obj):
        if obj.role == ChatMessage.Role.ASSISTANT:
            return strip_section_edits(strip_phase_marker(strip_course_json(obj.content)))
        return obj.content


class UploadedMaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedMaterial
        fields = ["id", "source_type", "name", "created"]


class ChatSessionSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)
    materials = UploadedMaterialSerializer(many=True, read_only=True)
    has_course_json = serializers.SerializerMethodField()
    can_apply = serializers.SerializerMethodField()

    class Meta:
        model = ChatSession
        fields = [
            "id", "course_id", "section_locator", "status", "messages", "materials",
            "has_course_json", "can_apply", "current_phase",
            "generation_status", "generation_error",
        ]

    def get_has_course_json(self, obj):
        return bool(obj.course_json)

    def get_can_apply(self, obj):
        """True if the latest assistant message carries an applyable SECTION_EDITS block."""
        for message in obj.messages.all().order_by("-created", "-id"):
            if message.role == ChatMessage.Role.ASSISTANT:
                return extract_section_edits(message.content) is not None
        return False
