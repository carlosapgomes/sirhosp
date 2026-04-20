"""Search service: clinical event FTS with operational filters (Slice S3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from django.db import connection, models

if TYPE_CHECKING:
    from apps.clinical_docs.models import ClinicalEvent


@dataclass(frozen=True, slots=True)
class SearchQueryParams:
    """Parameters for clinical event search."""

    query: str
    patient_id: int | None = None
    admission_id: int | None = None
    profession_type: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def _is_postgres() -> bool:
    """Check if the database backend is PostgreSQL."""
    return connection.vendor == "postgresql"


def search_clinical_events(
    params: SearchQueryParams,
) -> models.QuerySet[ClinicalEvent]:
    """Search clinical events by FTS (PostgreSQL) or icontains (fallback).

    Returns a QuerySet of ClinicalEvent ordered by relevance, filtered
    by the provided operational parameters.
    """
    from apps.clinical_docs.models import ClinicalEvent

    qs = ClinicalEvent.objects.all()

    # Apply operational filters first (before text search)
    if params.patient_id is not None:
        qs = qs.filter(patient_id=params.patient_id)

    if params.admission_id is not None:
        qs = qs.filter(admission_id=params.admission_id)

    if params.profession_type:
        qs = qs.filter(profession_type=params.profession_type)

    if params.date_from is not None:
        qs = qs.filter(happened_at__gte=params.date_from)

    if params.date_to is not None:
        qs = qs.filter(happened_at__lte=params.date_to)

    # Apply text search
    query_text = params.query.strip()
    if not query_text:
        return qs.none()

    if _is_postgres():
        return _search_postgres(qs, query_text)
    return _search_fallback(qs, query_text)


def _search_postgres(
    qs: models.QuerySet,
    query_text: str,
) -> models.QuerySet:
    """PostgreSQL FTS using SearchVector + SearchQuery."""
    from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

    vector = SearchVector("content_text", config="portuguese")
    search_query = SearchQuery(query_text, config="portuguese")

    return (
        qs.annotate(
            search=vector,
            rank=SearchRank(vector, search_query),
        )
        .filter(search=search_query)
        .order_by("-rank", "-happened_at")
    )


def _search_fallback(
    qs: models.QuerySet,
    query_text: str,
) -> models.QuerySet:
    """Fallback text search using icontains (SQLite-compatible).

    Uses Case/When for rudimentary relevance ordering:
    exact match > contains whole query > partial match.
    """
    from django.db.models import Case, IntegerField, Value, When

    return (
        qs.filter(content_text__icontains=query_text)
        .annotate(
            relevance=Case(
                When(content_text__iexact=query_text, then=Value(3)),
                When(content_text__icontains=f" {query_text} ", then=Value(2)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("-relevance", "-happened_at")
    )
