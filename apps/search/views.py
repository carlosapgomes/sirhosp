"""Search views (Slice S3)."""

from __future__ import annotations

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.utils.dateparse import parse_datetime

from apps.core.profession_types import to_display_label
from apps.search.services import SearchQueryParams, search_clinical_events


@login_required
def search_clinical_events_view(request: HttpRequest) -> JsonResponse:
    """Search clinical events with optional filters.

    Query params:
        q (required): Free-text search query.
        patient_id: Filter by patient ID.
        admission_id: Filter by admission ID.
        profession_type: Filter by profession type (medica, enfermagem, etc).
        date_from: ISO datetime filter (happened_at >= date_from).
        date_to: ISO datetime filter (happened_at <= date_to).
    """
    query = request.GET.get("q", "").strip()
    if not query:
        return JsonResponse(
            {"error": "Query parameter 'q' is required."},
            status=400,
        )

    params = SearchQueryParams(
        query=query,
        patient_id=_parse_int(request.GET.get("patient_id")),
        admission_id=_parse_int(request.GET.get("admission_id")),
        profession_type=request.GET.get("profession_type") or None,
        date_from=_parse_dt(request.GET.get("date_from")),
        date_to=_parse_dt(request.GET.get("date_to")),
    )

    qs = search_clinical_events(params)

    # Limit results for MVP
    events = qs[:50]

    results = [
        {
            "event_id": event.pk,
            "patient_id": event.patient_id,
            "admission_id": event.admission_id,
            "happened_at": event.happened_at.isoformat(),
            "author_name": event.author_name,
            "profession_type": to_display_label(event.profession_type),
            "content_text": event.content_text[:300],
        }
        for event in events
    ]

    return JsonResponse(
        {
            "query": query,
            "count": len(results),
            "results": results,
        }
    )


def _parse_int(value: str | None) -> int | None:
    """Parse an integer from a query parameter."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _parse_dt(value: str | None) -> datetime | None:
    """Parse a datetime from a query parameter."""
    if value is None:
        return None
    return parse_datetime(value)
