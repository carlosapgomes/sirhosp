"""Test settings using SQLite (no PostgreSQL required)."""
from config.settings import *  # noqa: F401, F403

# Force SQLite for tests regardless of .env
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
