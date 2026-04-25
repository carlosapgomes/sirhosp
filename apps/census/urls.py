"""URL routes for bed status (Slice S6)."""

from __future__ import annotations

from django.urls import path

from apps.census import views

app_name = "census"

urlpatterns = [
    path("beds/", views.bed_status_view, name="bed_status"),
]
