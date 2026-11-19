# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Backend image — Django + DRF + Celery
#
# Stages:
#   base        — shared runtime with the app and its dependencies
#   development — adds dev/test tooling, runs the dev server
#   production  — runs gunicorn, no dev tooling
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq is needed to talk to PostgreSQL; build tools are dropped after install.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

# Install Python dependencies first so the layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health/ || exit 1


# ---------------------------------------------------------------------------
FROM base AS development

# The development stage bind-mounts the source tree, which is owned by the
# host user. Running as root keeps that mount writable; the production
# image below drops to the unprivileged `app` user.
USER root

ENV DJANGO_DEBUG=1

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


# ---------------------------------------------------------------------------
FROM base AS production

ENV DJANGO_DEBUG=0 \
    DJANGO_LOG_LEVEL=WARNING

# Static files are collected at build time and served by WhiteNoise.
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

# Daphne serves both HTTP and the WebSocket endpoint from config.asgi.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", \
     "--access-log", "-", "config.asgi:application"]
