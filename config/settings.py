from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "true").strip().lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "apps.core",
    "apps.accounts",
    "apps.patients",
    "apps.clinical_docs",
    "apps.ingestion",
    "apps.summaries",
    "apps.search",
    "apps.services_portal",
    "apps.census",
    "apps.statistics_reports.apps.StatisticsReportsConfig",
    "apps.discharges.DischargesConfig",
    "apps.deaths.DeathsConfig",
    "apps.admissions.AdmissionsConfig",
    "apps.pending_items.apps.PendingItemsConfig",
    "apps.upstream_api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.RequirePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.sidebar_context",
                "apps.core.context_processors.sync_status",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.getenv("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB"),
            "USER": os.getenv("POSTGRES_USER", ""),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(BASE_DIR / "db.sqlite3"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Bahia"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/painel/"
LOGOUT_REDIRECT_URL = "/"

# ---------------------------------------------------------------------------
# Progressive admission summary (APS)
# ---------------------------------------------------------------------------
# Chunk size in days for the planner (default: 3).
SUMMARY_CHUNK_DAYS: int = int(os.getenv("SUMMARY_CHUNK_DAYS", "3"))
# Overlap between consecutive chunks in days (default: 1).
SUMMARY_OVERLAP_DAYS: int = int(os.getenv("SUMMARY_OVERLAP_DAYS", "1"))

# ---------------------------------------------------------------------------
# Upstream read API (sirhosp-upstream-api-v1)
# ---------------------------------------------------------------------------
# Static Bearer token for the internal upstream read API. Empty or missing
# means every /api/v1/ request fails closed with 500 (design D5): the API never
# opens its gate without a configured token, so it can ship before the token
# exists. Wire a minimum of 32 random bytes through the deploy environment.
SIRHOSP_UPSTREAM_API_TOKEN: str = os.getenv("SIRHOSP_UPSTREAM_API_TOKEN", "").strip()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Django logs every response with status >= 400 on ``django.request`` using the
# raw ``request.path``. That path carries the prontuario on the demographics
# route, so the filter rewrites /api/v1 request targets to their fixed route
# pattern (design D6) and passes every other record through untouched. Only
# that logger is filtered: it is the single configured logger that emits a
# request path (``django.server`` belongs to the development server, which the
# API contract leaves out of scope). ``disable_existing_loggers`` stays False
# so gunicorn's own loggers are not disturbed.
LOGGING: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "sanitize_upstream_api_target": {
            "()": "apps.upstream_api.access_log.SanitizeUpstreamTargetFilter",
        },
    },
    "loggers": {
        "django.request": {
            "filters": ["sanitize_upstream_api_target"],
        },
    },
}

# ---------------------------------------------------------------------------
# Daily statistics reporting (DSRS)
# ---------------------------------------------------------------------------
# First eligible America/Bahia local date (YYYY-MM-DD) declared for the daily
# statistics feature. Unset means the feature is not activated yet: no date is
# eligible and the closing command fails closed instead of rebuilding any
# earlier history.
_STATISTICS_ACTIVATION_DATE = os.getenv("STATISTICS_ACTIVATION_DATE", "").strip()
STATISTICS_ACTIVATION_DATE: date | None = (
    date.fromisoformat(_STATISTICS_ACTIVATION_DATE)
    if _STATISTICS_ACTIVATION_DATE
    else None
)
# Number of closed America/Bahia local dates the automatic finalization may
# consider at once (default: 7). The batch closes only the most recent closed
# dates, so no request triggers a large historical rebuild; an older
# post-activation date is reachable through an explicit single-date request.
# A non-positive value is refused by the command without processing any date.
STATISTICS_FINALIZATION_LOOKBACK_DAYS: int = int(
    os.getenv("STATISTICS_FINALIZATION_LOOKBACK_DAYS", "7")
)
