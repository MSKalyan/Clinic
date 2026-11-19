from django.urls import re_path

from apps.realtime.consumers import ClinicConsumer

websocket_urlpatterns = [
    re_path(r"^ws/clinic/(?P<clinic_id>[^/]+)/$", ClinicConsumer.as_asgi()),
]
