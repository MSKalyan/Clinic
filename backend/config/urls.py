"""Root URL configuration."""
from __future__ import annotations

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.api.v1.views.health import LivenessView, ReadinessView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.api.v1.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    # Health checks at the root as well as under the API.
    #
    # "/health" is the conventional path. A load balancer, a container
    # health check or a monitoring agent will use it without being told
    # that this project puts its API under a prefix -- and a 404 from a
    # health check looks exactly like a dead service.
    path("health", LivenessView.as_view(), name="health-root"),
    path("health/", LivenessView.as_view(), name="health-root-slash"),
    path("health/ready", ReadinessView.as_view(), name="health-ready-root"),
    path("health/ready/", ReadinessView.as_view(), name="health-ready-root-slash"),
]
