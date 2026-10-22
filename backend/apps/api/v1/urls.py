"""v1 API routes."""
from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.api.v1.views.appointments import AppointmentViewSet, AvailabilitySlotView
from apps.api.v1.views.auth import LoginView, MeView, RefreshView, RegisterView
from apps.api.v1.views.clinics import ClinicViewSet, MembershipViewSet
from apps.api.v1.views.conversations import CallLogViewSet, ConversationViewSet
from apps.api.v1.views.dashboard import DashboardSummaryView
from apps.api.v1.views.doctors import DoctorViewSet
from apps.api.v1.views.followups import FollowUpTaskViewSet
from apps.api.v1.views.patients import PatientViewSet
from apps.api.v1.views.tools import ToolInvokeView, ToolListView
from apps.api.v1.views.webhooks import (
    TelephonyWebhookView,
    VoiceWebhookView,
    WhatsAppWebhookView,
)

from apps.api.v1.views.health import LivenessView, ReadinessView

router = DefaultRouter()
router.register("clinics", ClinicViewSet, basename="clinic")
router.register("memberships", MembershipViewSet, basename="membership")
router.register("doctors", DoctorViewSet, basename="doctor")
router.register("appointments", AppointmentViewSet, basename="appointment")
router.register("patients", PatientViewSet, basename="patient")
router.register("follow-ups", FollowUpTaskViewSet, basename="follow-up")
router.register("conversations", ConversationViewSet, basename="conversation")
router.register("call-logs", CallLogViewSet, basename="call-log")

urlpatterns = [
    # -- health -------------------------------------------------------
    path("health/", LivenessView.as_view(), name="health"),
    path("health/ready/", ReadinessView.as_view(), name="health-ready"),
    # -- auth ---------------------------------------------------------
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("auth/refresh/", RefreshView.as_view(), name="refresh"),
    # -- resources ----------------------------------------------------
    path("", include(router.urls)),
    path("availability/slots/", AvailabilitySlotView.as_view({"get": "list"}), name="availability-slots"),
    # -- dashboard ----------------------------------------------------
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    # -- AI tools -----------------------------------------------------
    path("tools/", ToolListView.as_view(), name="tool-list"),
    path("tools/<str:tool_name>/invoke/", ToolInvokeView.as_view(), name="tool-invoke"),
    # -- provider webhooks --------------------------------------------
    # The optional <secret> segment carries the shared webhook secret for
    # providers (such as Sarvam) that cannot sign the body.
    path("webhooks/voice/<str:provider>/", VoiceWebhookView.as_view(), name="webhook-voice"),
    path(
        "webhooks/voice/<str:provider>/<str:secret>/",
        VoiceWebhookView.as_view(),
        name="webhook-voice-signed",
    ),
    path("webhooks/whatsapp/<str:provider>/", WhatsAppWebhookView.as_view(), name="webhook-whatsapp"),
    path("webhooks/telephony/<str:provider>/", TelephonyWebhookView.as_view(), name="webhook-telephony"),
]
