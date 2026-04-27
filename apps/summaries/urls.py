"""URL routes for summary views (APS-S2)."""

from django.urls import path

from . import views

app_name = "summaries"

urlpatterns = [
    path(
        "admissions/<int:admission_id>/summary/create/",
        views.create_summary_run,
        name="create_summary_run",
    ),
    path(
        "summaries/<int:run_id>/",
        views.run_status,
        name="run_status",
    ),
]
