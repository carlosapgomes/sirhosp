"""Context processor: injects sidebar navigation state and sync time.

Uses request path to determine which menu item is active.
"""

from django.http import HttpRequest

# Map URL prefixes to sidebar active menu keys
MENU_PATH_MAP = [
    ("/painel/", "dashboard"),
    ("/censo/", "censo"),
    ("/monitor/", "monitor"),
    # /pacientes/ and /patients/ are separate URL patterns
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
    if clean in ("pacientes", "patients"):
        return "Pacientes"
    if clean == "admissions":
        return "Timeline"
    if clean == "ingestao":
        return "Extração"
    return "SIRHOSP"


def sync_status(request: HttpRequest) -> dict:
    """Inject sync status time and indicator.

    In a real implementation this would be read from the latest
    successful IngestionRun, but for now returns a demo timestamp
    to keep the UI functional while backend evolves.
    """
    # Demo sync time — will be replaced by real IngestionRun query later
    return {
        "sync_time": "12:45",
    }
