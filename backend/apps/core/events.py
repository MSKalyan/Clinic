"""Internal event bus.

Domain services write ``OutboxEvent`` rows inside the business transaction.
Handlers registered here run when the outbox publisher drains them, which
keeps external side effects (notifications, provider calls) out of the
request/transaction path (PRD 11.3).

The handler modules are imported lazily so that an app does not have to be
imported by the publisher just to be *able* to handle its own events.
"""
from __future__ import annotations

import importlib
import logging
from typing import Callable

logger = logging.getLogger("apps.core.events")

_HANDLERS: dict[str, Callable] = {}

#: Modules that register handlers. Importing them registers their
#: ``@register``-decorated functions.
HANDLER_MODULES = (
    "apps.appointments.events",
    "apps.doctors.events",
)

_loaded = False


def register(event_type: str) -> Callable:
    """Decorator registering a handler for an internal event type."""

    def decorator(func: Callable) -> Callable:
        _HANDLERS[event_type] = func
        return func

    return decorator


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for module in HANDLER_MODULES:
        try:
            importlib.import_module(module)
        except Exception:  # pragma: no cover - a broken handler must not
            # stop the publisher from running the other handlers.
            logger.exception("could not import event handlers from %s", module)


def get_handler(event_type: str) -> Callable | None:
    _ensure_loaded()
    return _HANDLERS.get(event_type)
