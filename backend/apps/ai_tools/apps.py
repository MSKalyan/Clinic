from __future__ import annotations

from django.apps import AppConfig


class AiToolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai_tools"
    label = "ai_tools"
    verbose_name = "AI Tools"

    def ready(self) -> None:
        # Importing the handlers module is what *registers* the tools. The
        # registry is populated at import time, so without this the
        # assistant would find an empty catalogue and every tool call would
        # 404.
        from apps.ai_tools import handlers  # noqa: F401
