from rest_framework import serializers

from .models import ChatMessage, ChatSession, UploadedMaterial
from .services.llm_client import strip_course_json, strip_phase_marker


class ChatMessageSerializer(serializers.ModelSerializer):
    """Serialize a chat message, hiding any embedded COURSE_JSON from the client."""

    content = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "created"]

    def get_content(self, obj):
        if obj.role == ChatMessage.Role.ASSISTANT:
            return strip_phase_marker(strip_course_json(obj.content))
        return obj.content


class UploadedMaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedMaterial
        fields = ["id", "source_type", "name", "created"]


class ChatSessionSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)
    materials = UploadedMaterialSerializer(many=True, read_only=True)
    has_course_json = serializers.SerializerMethodField()

    class Meta:
        model = ChatSession
        fields = [
            "id", "course_id", "status", "messages", "materials",
            "has_course_json", "current_phase",
            "generation_status", "generation_error",
        ]

    def get_has_course_json(self, obj):
        return bool(obj.course_json)
