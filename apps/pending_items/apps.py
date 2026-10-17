from django.apps import AppConfig


class PendingItemsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pending_items"
    verbose_name = "Pending Items"
