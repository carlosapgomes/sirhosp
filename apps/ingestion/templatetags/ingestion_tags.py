"""Template tags for ingestion templates (stage labels, duration formatting)."""

from __future__ import annotations

from django import template

register = template.Library()

STAGE_LABELS: dict[str, str] = {
    "admissions_capture": "Captura de internações",
    "gap_planning": "Planejamento de gaps",
    "evolution_extraction": "Extração de evoluções",
    "ingestion_persistence": "Persistência dos dados",
    "demographics_extraction": "Extração de dados demográficos",
    "demographics_persistence": "Persistência de dados demográficos",
}


@register.filter
def stage_label(stage_name: str) -> str:
    """Map internal stage_name to a human-readable Portuguese label."""
    return STAGE_LABELS.get(stage_name, stage_name)


@register.filter
def stage_duration(metric) -> str:
    """Format stage duration as 'Xm Ys' or 'Xs'.

    Returns empty string when finished_at is None.
    """
    if metric.finished_at is None:
        return ""
    delta = metric.finished_at - metric.started_at
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    if seconds == 0:
        return f"{minutes}m"
    return f"{minutes}m {seconds}s"
