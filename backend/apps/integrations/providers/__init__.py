"""Provider adapters.

The registry helpers are re-exported here so that the domain layer can ask
for a provider without knowing which module implements it::

    from apps.integrations.providers import get_messaging_provider
"""
from apps.integrations.providers.registry import (  # noqa: F401
    get_messaging_provider,
    get_provider_for_webhook,
    get_telephony_provider,
    get_voice_provider,
    resolve_secret,
)

__all__ = [
    "get_messaging_provider",
    "get_provider_for_webhook",
    "get_telephony_provider",
    "get_voice_provider",
    "resolve_secret",
]
