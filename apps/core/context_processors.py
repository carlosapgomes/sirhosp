"""Context processor: injects sidebar navigation state and sync time.

Uses request path to determine which menu item is active.
"""

from django.http import HttpRequest

# Map URL prefixes to sidebar active menu keys
MENU_PATH_MAP = [
    ("/painel/", "dashboard"),
    ("/censo/", "censo"),
    ("/monitor/", "monitor"),
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
    return "SIRHOSP"


def sync_status(request: HttpRequest) -> dict:
    """Inject sync status time from the latest succeeded IngestionRun."""
    from django.utils import timezone

    from apps.ingestion.models import IngestionRun

    latest = (
        IngestionRun.objects
        .filter(status="succeeded", finished_at__isnull=False)
        .order_by("-finished_at")
        .first()
    )

    if latest is None:
        return {"sync_time": "--:--"}

    local_dt = timezone.localtime(latest.finished_at)
    return {"sync_time": local_dt.strftime("%H:%M")}
