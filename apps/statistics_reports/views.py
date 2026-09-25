"""Authorized read-only daily statistics surfaces (DSRS-S6, DSRS-S7).

The page renders one materialized revision and nothing else: the projection
service owns every wording and every grouping, this view only authorizes the
request, resolves the selected date, denies the sensitive response to shared
caches and hands the projection to the template. The export endpoint requires
its own permission, builds the workbook of that same projection in memory and
only then records the served-export audit row. No report is materialized,
corrected or recalculated here and no workbook is ever persisted.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from apps.statistics_reports.export import (
    XLSX_CONTENT_TYPE,
    build_export_workbook,
)
from apps.statistics_reports.models import StatisticsExportLog
from apps.statistics_reports.presentation import (
    daily_report_projection,
    default_report_date,
)

VIEW_PERMISSION = "statistics_reports.view_daily_statistics"
"""Dedicated consultation permission created by DSRS-S6 migration 0004."""

EXPORT_PERMISSION = "statistics_reports.export_daily_statistics"
"""Dedicated export permission, independent of the consultation permission."""


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


@login_required
def daily_report_export_view(request: HttpRequest) -> HttpResponse:
    """Serve the XLSX workbook of the selected date's current revision.

    The export permission is required on its own. The workbook reproduces the
    same projection the page renders, is built in memory and is never stored;
    a date without a ready revision has nothing to export and is answered as
    not found, and the audit row is created only after the response is fully
    built and configured and ready to be served.
    """
    if not request.user.has_perm(EXPORT_PERMISSION):
        raise PermissionDenied

    requested_date = _requested_date(request.GET.get("date"))
    selected_date = requested_date or default_report_date()
    projection = (
        None if selected_date is None else daily_report_projection(selected_date)
    )
    if projection is None:
        raise Http404("No materialized daily statistics report for this date")

    workbook = build_export_workbook(projection)

    response = HttpResponse(workbook.content, content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = (
        f'attachment; filename="{workbook.filename}"'
    )
    # The workbook is nominal content too: it stays private to the user and
    # shared caches may not store it.
    response["Cache-Control"] = "private, no-store"
    # The audit row means "workbook generated and ready to be served": it is
    # committed only after the response is fully built and configured, so a
    # failure while generating the workbook or while preparing the response
    # never records a success. It carries aggregate counts and the exact
    # revision, no nominal payload.
    StatisticsExportLog.objects.create(
        # request.user is guaranteed authenticated by @login_required.
        user=request.user,  # type: ignore[misc]
        report=projection.report,
        sheet_count=workbook.sheet_count,
        row_count=workbook.row_count,
    )
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
