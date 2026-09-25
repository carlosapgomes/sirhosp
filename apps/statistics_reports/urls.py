"""URL routes of the authorized daily statistics report (DSRS-S6, DSRS-S7)."""

from __future__ import annotations

from django.urls import path

from apps.statistics_reports import views

app_name = "statistics_reports"

urlpatterns = [
    path("statistics/", views.daily_report_view, name="daily_report"),
    path(
        "statistics/export/",
        views.daily_report_export_view,
        name="daily_report_export",
    ),
]
