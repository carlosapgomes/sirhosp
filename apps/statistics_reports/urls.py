"""URL routes of the authorized daily statistics report (DSRS-S6)."""

from __future__ import annotations

from django.urls import path

from apps.statistics_reports import views

app_name = "statistics_reports"

urlpatterns = [
    path("statistics/", views.daily_report_view, name="daily_report"),
]
