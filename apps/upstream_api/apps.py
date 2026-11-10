from __future__ import annotations

from django.apps import AppConfig


class UpstreamApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.upstream_api"
    verbose_name = "Upstream Read API"
