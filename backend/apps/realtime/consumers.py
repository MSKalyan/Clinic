"""Authenticated WebSocket consumer for clinic-wide live updates.

The browser connects to ``ws://<host>/ws/clinic/<clinic-id>/?token=<jwt>``.
The JWT is checked against an active clinic membership before any group is
joined, so a socket can never receive another tenant's events. A client may
then subscribe to an individual conversation thread.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.constants import MembershipStatus

logger = logging.getLogger("apps.realtime")


@database_sync_to_async
def _authorise(token: str, clinic_id: str):
    """Return the authenticated user id, or ``None`` when access is denied."""
    from apps.accounts.models import ClinicMembership

    try:
        user_id = AccessToken(token)["user_id"]
    except (TokenError, KeyError, TypeError, ValueError):
        return None
    allowed = ClinicMembership.objects.filter(
        clinic_id=clinic_id, user_id=user_id, status=MembershipStatus.ACTIVE
    ).exists()
    return str(user_id) if allowed else None


@database_sync_to_async
def _thread_is_allowed(conversation_id: str, clinic_id: str, user_id: str) -> bool:
    from apps.conversations.models import Conversation
    from apps.core.rls import rls_scope

    # `database_sync_to_async` runs on a thread-pool connection with no RLS
    # scope, so the RLS-protected conversations table would be invisible. The
    # clinic id is trusted here: connect() already verified the caller's active
    # membership for it.
    with rls_scope(clinic_id):
        return Conversation.objects.filter(id=conversation_id, clinic_id=clinic_id).exists()


class ClinicConsumer(AsyncJsonWebsocketConsumer):
    """Push dashboard and conversation events to one signed-in clinic user."""

    async def connect(self) -> None:
        self.clinic_id = self.scope["url_route"]["kwargs"]["clinic_id"]
        self.thread_group: str | None = None
        self.dashboard_group: str | None = None
        self.conversations_group: str | None = None

        token = self._token_from_scope()
        self.user_id = await _authorise(token, self.clinic_id) if token else None
        if not self.user_id:
            await self.close(code=4401)
            return

        # Channels group names may only contain alphanumerics, '-', '_' and
        # '.' — colons raise TypeError on both the in-memory and Redis layers.
        self.dashboard_group = f"clinic_{self.clinic_id}_dashboard"
        self.conversations_group = f"clinic_{self.clinic_id}_conversations"
        await self.channel_layer.group_add(self.dashboard_group, self.channel_name)
        await self.channel_layer.group_add(self.conversations_group, self.channel_name)
        await self.accept()
        await self.send_json({"event": "connected", "data": {"clinic_id": self.clinic_id}})

    def _token_from_scope(self) -> str:
        query = parse_qs(self.scope.get("query_string", b"").decode())
        if query.get("token"):
            return query["token"][0]
        for protocol in self.scope.get("subprotocols", []):
            if protocol.startswith("access."):
                return protocol[len("access.") :]
        return ""

    async def disconnect(self, code: int) -> None:
        # A rejected connection never joined any groups, so these may be None.
        for group in (self.dashboard_group, self.conversations_group, self.thread_group):
            if group:
                await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content: dict, **kwargs) -> None:
        """Allow a client to subscribe to one conversation thread."""
        action = content.get("action")
        conversation_id = str(content.get("conversation_id") or "")
        if action in {"subscribe", "unsubscribe"} and conversation_id and len(conversation_id) <= 64:
            if not await _thread_is_allowed(conversation_id, self.clinic_id, self.user_id):
                await self.send_json(
                    {"event": "error", "data": {"message": "Conversation not found."}}
                )
                return
            group = f"conversation_{conversation_id}"
            if action == "subscribe":
                if self.thread_group and self.thread_group != group:
                    await self.channel_layer.group_discard(self.thread_group, self.channel_name)
                await self.channel_layer.group_add(group, self.channel_name)
                self.thread_group = group
                await self.send_json(
                    {"event": "subscribed", "data": {"conversation_id": conversation_id}}
                )
            elif self.thread_group == group:
                await self.channel_layer.group_discard(group, self.channel_name)
                self.thread_group = None

    async def realtime_event(self, event: dict) -> None:
        await self.send_json(
            {
                "event": event["event"],
                "data": event.get("data", {}),
                "at": event.get("at"),
            }
        )

    async def receive(self, text_data: str | None = None, bytes_data: bytes | None = None) -> None:
        """Accept legacy string frames as well as JSON frames."""
        if text_data:
            try:
                await self.receive_json(json.loads(text_data))
            except (ValueError, TypeError):  # pragma: no cover - malformed client frame
                await self.send_json({"event": "error", "data": {"message": "Invalid JSON."}})
        elif bytes_data:  # pragma: no cover - browsers send text frames
            await self.receive(text_data=bytes_data.decode("utf-8", errors="replace"))
