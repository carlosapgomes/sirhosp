"""Context processors: sidebar navigation state and census photo freshness.

Uses request path to determine which menu item is active.
Injects the topbar badge values from the latest census photo
(``CensusSnapshot`` with maximum ``captured_at``) — the badge never reads
individual ingestion runs and never derives freshness from the request
time.
"""

from datetime import datetime, timedelta

from django.db.models import Max
from django.http import HttpRequest
from django.utils import timezone

# Age thresholds for the badge dot (design D3, operator decision).
FRESH_WITHIN = timedelta(hours=2)
STALE_WITHIN = timedelta(hours=6)

# Fail-closed presentation when no census photo exists (or reads fail).
NO_PHOTO_LABEL = "--:--"
NO_PHOTO_TITLE = "Nenhuma foto de censo disponível"
OUTDATED_CLASS = "is-outdated"

# Map URL prefixes to sidebar active menu keys
MENU_PATH_MAP = [
    ("/painel/", "dashboard"),
    ("/censo/", "censo"),
    ("/monitor/", "monitor"),
    ("/setores/", "setores"),
]


def sidebar_context(request: HttpRequest) -> dict:
    """Determine active sidebar menu item from request path."""
    if not hasattr(request, "path"):
        return {}

    path = request.path

    # Check specific prefixes first
    for prefix, menu_key in MENU_PATH_MAP:
        if path.startswith(prefix):
            return {"active_menu": menu_key, "page_title": _default_title(path)}

    # /pacientes/ and /patients/ both map to "pacientes"
    if path.startswith(("/pacientes/", "/patients/", "/admissions/")):
        return {"active_menu": "pacientes", "page_title": _default_title(path)}

    # Ingestion routes map to pacientes context
    if path.startswith("/ingestao/"):
        return {"active_menu": "pacientes", "page_title": _default_title(path)}

    return {"page_title": _default_title(path)}


def _default_title(path: str) -> str:
    """Derive a default page title from path."""
    clean = path.strip("/").split("/")[0]
    if clean == "painel":
        return "Dashboard"
    if clean == "censo":
        return "Censo Hospitalar"
    if clean == "monitor":
        return "Monitor de Risco"
    if clean == "beds":
        return "Leitos"
    if clean in ("pacientes", "patients"):
        return "Pacientes"
    if clean == "admissions":
        return "Timeline"
    if clean == "ingestao":
        return "Extração"
    return "Prisma"


def latest_census_photo() -> datetime | None:
    """Return the capture time of the latest census photo, or ``None``.

    Single index-backed aggregate (``census_captured_idx``); the same
    semantics as the dashboard "Última varredura completa" card.
    """
    from apps.census.models import CensusSnapshot

    return CensusSnapshot.objects.aggregate(Max("captured_at"))[
        "captured_at__max"
    ]


def census_badge_values(
    captured_at: datetime | None, now: datetime
) -> dict[str, str]:
    """Pure presentation values for the census freshness badge.

    Returns ``census_sync_label`` ("HH:MM" for a photo from today,
    "dd/mm HH:MM" otherwise, "--:--" without a photo), ``census_sync_title``
    (full local timestamp) and ``census_sync_age_class`` (closed classes:
    ``is-fresh`` <= 2 h, ``is-stale`` <= 6 h, ``is-outdated`` beyond 6 h or
    without a photo). The label prefix ("Censo: ") belongs to the template.
    """
    if captured_at is None:
        return {
            "census_sync_label": NO_PHOTO_LABEL,
            "census_sync_title": NO_PHOTO_TITLE,
            "census_sync_age_class": OUTDATED_CLASS,
        }

    local_dt = timezone.localtime(captured_at)
    age = now - captured_at
    if age <= FRESH_WITHIN:
        age_class = "is-fresh"
    elif age <= STALE_WITHIN:
        age_class = "is-stale"
    else:
        age_class = OUTDATED_CLASS

    if local_dt.date() == timezone.localtime(now).date():
        label = local_dt.strftime("%H:%M")
    else:
        label = local_dt.strftime("%d/%m %H:%M")

    return {
        "census_sync_label": label,
        "census_sync_title": local_dt.strftime(
            "Foto do censo de %d/%m/%Y %H:%M"
        ),
        "census_sync_age_class": age_class,
    }


def sync_status(request: HttpRequest) -> dict[str, str]:
    """Inject census photo freshness for the topbar badge.

    Fail-closed: without a photo — or on any database failure (e.g. test
    environments without django_db) — degrades to "--:--" + outdated.
    """
    try:
        captured_at = latest_census_photo()
        return census_badge_values(captured_at, timezone.now())
    except Exception:
        return {
            "census_sync_label": NO_PHOTO_LABEL,
            "census_sync_title": NO_PHOTO_TITLE,
            "census_sync_age_class": OUTDATED_CLASS,
        }
