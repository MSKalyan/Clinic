from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.realtime"
    verbose_name = "Real-time events"

    def ready(self) -> None:
        # Importing consumers registers nothing by itself, but keeping the
        # import here guarantees the module is validated at startup.
        from apps.realtime import consumers  # noqa: F401
