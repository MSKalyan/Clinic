"""Serializers for the accounts app."""
from __future__ import annotations

from rest_framework import serializers

from apps.accounts.models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "phone", "is_platform_admin"]
        read_only_fields = ["id", "is_platform_admin"]
