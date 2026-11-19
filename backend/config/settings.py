"""Django settings for the AI Clinic Operations Assistant.

Configuration is environment-driven (12-factor). Every value has a safe
default for local development, but production deployments are expected to
override secrets via AWS Secrets Manager / environment variables.
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

# Read a repo-root .env if present (local development convenience only).
_ENV_FILE = REPO_ROOT / ".env"
if _ENV_FILE.exists():
    environ.Env.read_env(str(_ENV_FILE))

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    DJANGO_LOG_LEVEL=(str, "INFO"),
    DB_NAME=(str, "clinic"),
    DB_USER=(str, "clinic_app"),
    DB_PASSWORD=(str, "clinic_app"),
    DB_HOST=(str, "127.0.0.1"),
    DB_PORT=(str, "5432"),
    DB_CONN_MAX_AGE=(int, 60),
    ENABLE_ROW_LEVEL_SECURITY=(bool, True),
    REDIS_URL=(str, "redis://127.0.0.1:6379/0"),
    CELERY_BROKER_URL=(str, "redis://127.0.0.1:6379/1"),
    CELERY_RESULT_BACKEND=(str, "redis://127.0.0.1:6379/2"),
    ACCESS_TOKEN_LIFETIME_MINUTES=(int, 30),
    REFRESH_TOKEN_LIFETIME_DAYS=(int, 7),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000", "http://127.0.0.1:3000"]),
    INTERNAL_SERVICE_TOKEN_PEPPER=(str, "change-me"),
    SECRET_ENCRYPTION_KEY=(str, ""),
    SARVAM_BASE_URL=(str, "https://api.sarvam.ai"),
    SARVAM_API_KEY=(str, ""),
    SARVAM_VOICE_AGENT_ID=(str, ""),
    SARVAM_WEBHOOK_SECRET=(str, ""),
    WHATSAPP_GRAPH_URL=(str, "https://graph.facebook.com/v21.0"),
    WHATSAPP_PHONE_NUMBER_ID=(str, ""),
    WHATSAPP_ACCESS_TOKEN=(str, ""),
    WHATSAPP_APP_SECRET=(str, ""),
    WHATSAPP_VERIFY_TOKEN=(str, ""),
    TELEPHONY_BASE_URL=(str, ""),
    TELEPHONY_AUTH_TOKEN=(str, ""),
    TELEPHONY_PROVIDER=(str, "stub"),
    # WAHA (self-hosted WhatsApp HTTP API) -- local development integration.
    # In Docker the WAHA service is reachable by its compose service alias;
    # when Django is run on the host, use http://localhost:3000 instead.
    WAHA_BASE_URL=(str, "http://waha:3000"),
    WAHA_API_KEY=(str, ""),
    WAHA_SESSION=(str, "session_01"),
    # Which clinic this WhatsApp number belongs to. Used for senders we have
    # not seen before; an existing patient's own clinic always takes priority.
    WAHA_CLINIC_SLUG=(str, ""),
    # Emergency stop: when false, no automated WhatsApp/Meta message is sent
    # or queued. Set AUTOMATED_MESSAGING_ENABLED=false in .env to pause all
    # outbound automation without stopping services.
    AUTOMATED_MESSAGING_ENABLED=(bool, True),
    WAHA_WEBHOOK_SECRET=(str, ""),
    WAHA_WEBHOOK_HMAC_KEY=(str, ""),
    WAHA_REQUEST_TIMEOUT_SECONDS=(float, 10.0),
    WAHA_MAX_TEXT_LENGTH=(int, 4096),
)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-secret-key-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    # daphne's ASGI `runserver` must precede staticfiles so development serves
    # WebSockets as well as HTTP.
    "daphne",
    "channels",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    # local
    "apps.core",
    "apps.tenancy",
    "apps.accounts",
    "apps.doctors",
    "apps.appointments",
    "apps.conversations",
    "apps.integrations",
    "apps.ai_tools",
    "apps.usage",
    "apps.realtime",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
    "apps.core.middleware.TenantContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

#: WebSockets share the Redis instance used by Celery and the cache. A channel
#: layer lets every gunicorn/ASGI worker reach every connected browser.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [env("REDIS_URL")]},
    }
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST"),
        "PORT": env("DB_PORT"),
        "CONN_MAX_AGE": env("DB_CONN_MAX_AGE"),
        "CONN_HEALTH_CHECKS": True,
        "ATOMIC_REQUESTS": False,
        "TEST": {"NAME": f"test_{env('DB_NAME')}"},
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # The service-token authenticator runs first so a provider token is
        # never mistaken for a staff JWT. It steps aside for JWT-shaped
        # credentials, which the JWT authenticator then handles.
        "apps.core.authentication.ClinicServiceTokenAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "600/min",
        "service_token": "1200/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env("ACCESS_TOKEN_LIFETIME_MINUTES")),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env("REFRESH_TOKEN_LIFETIME_DAYS")),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "AI Clinic Operations Assistant API",
    "DESCRIPTION": "Multi-tenant API for clinic patient communication and operations.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

#: Headers the browser is allowed to send.
#:
#: The tenant is selected with ``X-Clinic-Id``, and a custom header makes
#: every request a preflight. django-cors-headers' default allow-list
#: contains no custom headers, so the preflight answered without naming
#: ``X-Clinic-Id`` and the browser then refused the *real* request. The
#: symptom was "Failed to fetch" on every screen, with the preflight
#: logging a cheerful 200 -- which is why it looked like a backend
#: problem.
#:
#: The name is ``CORS_ALLOW_HEADERS`` (not ``CORS_ALLOWED_HEADERS``) --
#: that is the setting django-cors-headers 4.4+ reads.
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "origin",
    "user-agent",
    "x-clinic-id",
    "x-csrftoken",
    "x-requested-with",
]

#: Methods the dashboard uses.
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

# --- Celery ---------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND")
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
CELERY_ENABLE_UTC = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 300
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    "scan-reminder-due": {
        "task": "apps.appointments.tasks.scan_appointment_reminders",
        "schedule": 60.0,
    },
    "scan-doctor-status-freshness": {
        "task": "apps.doctors.tasks.scan_stale_doctor_status",
        "schedule": 300.0,
    },
    "scan-unresolved-calls": {
        "task": "apps.conversations.tasks.scan_unresolved_calls",
        "schedule": 300.0,
    },
    "publish-outbox": {
        "task": "apps.core.tasks.publish_outbox",
        "schedule": 5.0,
    },
    "daily-usage-aggregation": {
        "task": "apps.usage.tasks.aggregate_daily_usage",
        "schedule": 3600.0,
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "KEY_PREFIX": "clinic",
    }
}

# --- Domain / product settings ------------------------------------------
ENABLE_ROW_LEVEL_SECURITY = env("ENABLE_ROW_LEVEL_SECURITY")
INTERNAL_SERVICE_TOKEN_PEPPER = env("INTERNAL_SERVICE_TOKEN_PEPPER")

#: Encrypts the provider credentials a clinic sets for itself.
#:
#: When this is empty the key is derived from the service-token pepper, so
#: a local development setup works without extra configuration. In
#: production it must be set explicitly and kept stable: changing it
#: makes every stored clinic secret unreadable.
SECRET_ENCRYPTION_KEY = env("SECRET_ENCRYPTION_KEY")

#: Header used by the frontend to select the active clinic for a session.
CLINIC_HEADER = "X-Clinic-Id"

#: Default appointment rules applied to a clinic when it has no explicit
#: ``appointment_rules`` override.
DEFAULT_APPOINTMENT_RULES = {
    "slot_interval_minutes": 30,
    "appointment_duration_minutes": 30,
    "buffer_minutes": 10,
    "booking_horizon_days": 30,
    "cancellation_window_hours": 4,
    "require_approval_for_new_patients": False,
    "allow_same_day_booking": True,
}

#: Default reminder policy.
DEFAULT_REMINDER_POLICY = {
    "offsets_hours": [24, 2],
    "channels": ["sms", "whatsapp"],
    "max_attempts": 3,
    "retry_backoff_minutes": [5, 30, 120],
}

#: Default escalation policy.
DEFAULT_ESCALATION_POLICY = {
    "missed_call_follow_up": True,
    "emergency_keywords": [
        "chest pain",
        "breathing",
        "unconscious",
        "severe bleeding",
        "stroke",
        "suicide",
        "ambulance",
    ],
    "business_hours_queue": True,
}

#: Freshness thresholds (minutes) per doctor status. A status older than its
#: threshold is reported as ``unknown`` and flagged stale in the dashboard.
DEFAULT_STATUS_FRESHNESS_MINUTES = {
    "present": 60,
    "running_late": 30,
    "unavailable": 120,
    "on_leave": 1440,
    "finished_for_day": 1440,
    "scheduled": 240,
    "unknown": 0,
}

#: Retention windows for data that must not be retained indefinitely.
RETENTION = {
    "conversation_message_days": 30,
    "call_recording_days": 0,  # recordings are not stored by default
    "audit_log_days": 365,
}

# --- Providers ------------------------------------------------------------
SARVAM_BASE_URL = env("SARVAM_BASE_URL")
SARVAM_API_KEY = env("SARVAM_API_KEY")
SARVAM_VOICE_AGENT_ID = env("SARVAM_VOICE_AGENT_ID")
#: Shared secret for the Sarvam webhook. Sarvam does not sign the request
#: body, so the secret travels in the URL path (or the X-Webhook-Secret
#: header) and is compared against this value.
SARVAM_WEBHOOK_SECRET = env("SARVAM_WEBHOOK_SECRET")

WHATSAPP_GRAPH_URL = env("WHATSAPP_GRAPH_URL")
WHATSAPP_PHONE_NUMBER_ID = env("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_ACCESS_TOKEN = env("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET")
#: The token configured in the Meta dashboard, used for the subscription
#: handshake. When it is empty the app secret is used instead.
WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN")

TELEPHONY_BASE_URL = env("TELEPHONY_BASE_URL")
TELEPHONY_AUTH_TOKEN = env("TELEPHONY_AUTH_TOKEN")
TELEPHONY_PROVIDER = env("TELEPHONY_PROVIDER")

# --- WAHA (self-hosted WhatsApp HTTP API) ---------------------------------
# Credentials stay on the backend; the webhook secret and HMAC key are never
# exposed through an API response or to the frontend.
WAHA_BASE_URL = env("WAHA_BASE_URL").rstrip("/")
WAHA_API_KEY = env("WAHA_API_KEY")
WAHA_SESSION = env("WAHA_SESSION")
WAHA_CLINIC_SLUG = env("WAHA_CLINIC_SLUG")
AUTOMATED_MESSAGING_ENABLED = env("AUTOMATED_MESSAGING_ENABLED")
WAHA_WEBHOOK_SECRET = env("WAHA_WEBHOOK_SECRET")
WAHA_WEBHOOK_HMAC_KEY = env("WAHA_WEBHOOK_HMAC_KEY")
WAHA_REQUEST_TIMEOUT_SECONDS = env("WAHA_REQUEST_TIMEOUT_SECONDS")
WAHA_MAX_TEXT_LENGTH = env("WAHA_MAX_TEXT_LENGTH")

#: Transactional WhatsApp messages sent on appointment lifecycle changes.
#: Placeholders are filled by ``apps.appointments.services.appointment_messages``.
WAHA_APPOINTMENT_MESSAGES: dict[str, str] = {
    "booked": (
        "Hi {patient_name}, your appointment at {clinic_name} is confirmed.\n"
        "Reference: {reference}\n"
        "Doctor: {doctor_name}\n"
        "When: {when} ({timezone})\n"
        "Reply to this message if you need to reschedule or cancel.\n"
        "Thank you."
    ),
    "rescheduled": (
        "Hi {patient_name}, your appointment at {clinic_name} has been "
        "rescheduled.\n"
        "Reference: {reference}\n"
        "Doctor: {doctor_name}\n"
        "New time: {when} ({timezone})\n"
        "Reply to this message if you need to make another change.\n"
        "Thank you."
    ),
    "cancelled": (
        "Hi {patient_name}, your appointment at {clinic_name} "
        "({reference}) with {doctor_name} scheduled for {when} has been "
        "cancelled. Reply to this message to book a new time.\n"
        "Thank you."
    ),
}

#: All patient-facing templates live in one registry. Values here override the
#: defaults in ``apps.conversations.services.templates.DEFAULT_TEMPLATES``.
MESSAGE_TEMPLATES: dict[str, str] = {
    "welcome": (
        "Hi {patient_name}, welcome to {clinic_name}! "
        "Your details are saved. You can reply to this message any time if you "
        "need help with appointments or have a question for our team."
    ),
}

#: Dispatching a provider HTTP call inside a request is the main source of UI
#: lag. When true, delivery runs in Celery and the request only writes a row.
MESSAGES_ASYNC = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)-7s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "apps": {"level": env("DJANGO_LOG_LEVEL"), "handlers": ["console"], "propagate": False},
    },
}
