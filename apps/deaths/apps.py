from __future__ import annotations

from django.apps import AppConfig


class DeathsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.deaths"
    verbose_name = "Deaths"
