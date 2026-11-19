"""WebSocket auth, tenant isolation and live event delivery.

Each test drives the communicator inside a single ``async_to_sync`` call so all
async work shares one event loop (no pytest-asyncio plugin required). An
in-memory channel layer keeps the test local while still exercising the real
consumer, routing and broadcast helpers.
"""
from __future__ import annotations

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import override_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.realtime.broadcast import conversation_changed, dashboard_changed
from apps.realtime.routing import websocket_urlpatterns

IN_MEMORY_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
APPLICATION = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))


def _communicator(clinic_id, token):
    return WebsocketCommunicator(
        APPLICATION,
        f"/ws/clinic/{clinic_id}/?token={token}",
    )


@pytest.mark.django_db(transaction=True)
@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYERS)
def test_socket_rejects_unauthenticated_and_cross_tenant(clinic, other_clinic, staff_user, membership):
    token = str(RefreshToken.for_user(staff_user).access_token)
    clinic_id, other_id = clinic.id, other_clinic.id

    async def exercise():
        comm = _communicator(clinic_id, "")
        connected, _ = await comm.connect()
        assert connected is False
        await comm.disconnect()

        # Valid token, but no membership for this clinic -> rejected.
        comm = _communicator(other_id, token)
        connected, _ = await comm.connect()
        assert connected is False
        await comm.disconnect()

    async_to_sync(exercise)()


@pytest.mark.django_db(transaction=True)
@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYERS)
def test_dashboard_event_reaches_the_clinic_socket(clinic, staff_user, membership):
    token = str(RefreshToken.for_user(staff_user).access_token)
    clinic_id = clinic.id

    async def exercise():
        comm = _communicator(clinic_id, token)
        connected, _ = await comm.connect()
        assert connected is True
        assert (await comm.receive_json_from())["event"] == "connected"

        await sync_to_async(dashboard_changed)(clinic_id, "appointment", reference="APT-1")
        event = await comm.receive_json_from()
        assert event["event"] == "dashboard.changed"
        assert event["data"]["reason"] == "appointment"
        assert event["data"]["reference"] == "APT-1"
        assert event["at"]
        await comm.disconnect()

    async_to_sync(exercise)()


@pytest.mark.django_db(transaction=True)
@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYERS)
def test_conversation_thread_subscribe_and_message(clinic, staff_user, membership, patient):
    from apps.conversations.models import Conversation

    conversation = Conversation.objects.create(
        clinic=clinic,
        patient=patient,
        channel="whatsapp",
    )
    conversation_id = str(conversation.id)
    token = str(RefreshToken.for_user(staff_user).access_token)
    clinic_id = clinic.id

    async def exercise():
        comm = _communicator(clinic_id, token)
        connected, _ = await comm.connect()
        assert connected is True
        assert (await comm.receive_json_from())["event"] == "connected"

        await comm.send_json_to({"action": "subscribe", "conversation_id": conversation_id})
        assert (await comm.receive_json_from())["event"] == "subscribed"

        await sync_to_async(conversation_changed)(
            clinic_id, conversation.id, "message", message={"id": "m1", "excerpt": "Hello"}
        )
        event = await comm.receive_json_from()
        assert event["event"] == "conversation.message"
        assert event["data"]["message"]["excerpt"] == "Hello"
        await comm.disconnect()

    async_to_sync(exercise)()
