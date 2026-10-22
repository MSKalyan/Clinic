"""Authentication endpoints."""
from __future__ import annotations

from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from apps.core.audit import record_audit
from apps.core.constants import AuditAction
from apps.core.utils import normalise_phone


def issue_tokens(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


class LoginView(APIView):
    """Email + password login."""

    permission_classes = [AllowAny]

    def post(self, request):  # noqa: ANN001
        email = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password") or ""
        if not email or not password:
            return Response(
                {
                    "error": {
                        "code": "missing_credentials",
                        "message": "Enter your email and password.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=email, password=password)
        if user is None:
            # Try the email as the username too (users are created with
            # email == username).
            user = authenticate(request, username=email.lower(), password=password)
        if user is None or not user.is_active:
            return Response(
                {
                    "error": {
                        "code": "invalid_credentials",
                        "message": "That email and password combination did not work.",
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        from django.utils import timezone

        user.last_login_at = timezone.now()
        user.save(update_fields=["last_login_at"])

        record_audit(
            action=AuditAction.LOGIN,
            resource_type="user",
            resource_id=user.id,
            actor=user,
            request=request,
        )
        return Response(
            {"user": UserSerializer(user).data, "tokens": issue_tokens(user)}
        )


class RefreshView(APIView):
    """Exchange a refresh token for a new access token."""

    permission_classes = [AllowAny]

    def post(self, request):  # noqa: ANN001
        raw = (request.data.get("refresh") or "").strip()
        if not raw:
            return Response(
                {
                    "error": {
                        "code": "missing_refresh_token",
                        "message": "A refresh token is required.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            refresh = RefreshToken(raw)
        except TokenError:
            return Response(
                {
                    "error": {
                        "code": "invalid_refresh_token",
                        "message": "That session has expired. Please sign in again.",
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user_id = refresh.get("user_id")
        if not user_id:
            return Response(
                {
                    "error": {
                        "code": "invalid_refresh_token",
                        "message": "That session is not valid.",
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = User.objects.filter(id=user_id, is_active=True).first()
        if user is None:
            return Response(
                {
                    "error": {
                        "code": "invalid_refresh_token",
                        "message": "That session is not valid.",
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response({"user": UserSerializer(user).data, "tokens": issue_tokens(user)})


class RegisterView(APIView):
    """Create a user account. A clinic membership is granted separately."""

    permission_classes = [AllowAny]

    def post(self, request):  # noqa: ANN001
        email = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password") or ""
        if not email or not password:
            return Response(
                {
                    "error": {
                        "code": "missing_fields",
                        "message": "An email address and password are required.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {
                    "error": {
                        "code": "email_taken",
                        "message": "An account already exists for that email address.",
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=(request.data.get("first_name") or "")[:150],
            last_name=(request.data.get("last_name") or "")[:150],
            phone=normalise_phone(request.data.get("phone")),
        )
        return Response(
            {"user": UserSerializer(user).data, "tokens": issue_tokens(user)},
            status=status.HTTP_201_CREATED,
        )


class MeView(APIView):
    """The signed-in user and the clinics they belong to."""

    permission_classes = [AllowAny]

    def get(self, request):  # noqa: ANN001
        user = request.user
        if not user.is_authenticated:
            return Response({"user": None, "clinics": []})
        memberships = user.clinic_memberships.select_related("clinic").filter(status="active")
        return Response(
            {
                "user": UserSerializer(user).data,
                "clinics": [
                    {
                        "clinic_id": str(m.clinic_id),
                        "name": m.clinic.name,
                        "timezone": m.clinic.timezone,
                        "role": m.role,
                    }
                    for m in memberships
                ],
            }
        )
