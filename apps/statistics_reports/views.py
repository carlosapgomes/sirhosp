"""Authorized read-only daily statistics page (DSRS-S6).

The page renders one materialized revision and nothing else: the projection
service owns every wording and every grouping, this view only authorizes the
request, resolves the selected date, denies the sensitive response to shared
caches and hands the projection to the template. No report is materialized,
corrected or recalculated here.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.statistics_reports.presentation import (
    daily_report_projection,
    default_report_date,
)

VIEW_PERMISSION = "statistics_reports.view_daily_statistics"
"""Dedicated consultation permission created by DSRS-S6 migration 0004."""


@login_required
def daily_report_view(request: HttpRequest) -> HttpResponse:
    """Render the authorized daily report of the selected local date.

    Without a ``date`` parameter the page opens yesterday when it is ready and
    otherwise the latest ready date, never today. An explicit date without a
    ready revision is rendered as an explicit unavailable state; the request
    never triggers a materialization.
    """
    if not request.user.has_perm(VIEW_PERMISSION):
        raise PermissionDenied

    requested_date = _requested_date(request.GET.get("date"))
    selected_date = requested_date or default_report_date()
    projection = (
        None if selected_date is None else daily_report_projection(selected_date)
    )

    response = render(
        request,
        "statistics_reports/daily_report.html",
        {
            "page_title": "Estatísticas",
            "active_menu": "estatisticas",
            "selected_date": selected_date,
            "projection": projection,
        },
    )
    # The nominal answer is sensitive: it is private to the user and shared
    # caches may not store it.
    response["Cache-Control"] = "private, no-store"
    return response


def _requested_date(raw: str | None) -> date | None:
    """Explicit requested date, or ``None`` for the safe default.

    A malformed value is treated as no request at all, so the page falls back
    to the safe default instead of guessing a date.
    """
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None
