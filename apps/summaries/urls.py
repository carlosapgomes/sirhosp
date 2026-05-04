"""URL routes for summary views (APS-S2, STP-S5)."""

from django.urls import path

from . import views

app_name = "summaries"

urlpatterns = [
    path(
        "admissions/<int:admission_id>/summary/config/",
        views.summary_config,
        name="summary_config",
    ),
    path(
        "admissions/<int:admission_id>/summary/create/",
        views.create_summary_run,
        name="create_summary_run",
    ),
    path(
        "summaries/status/<int:run_id>/",
        views.run_status,
        name="run_status",
    ),
    path(
        "summaries/status/<int:run_id>/progress/",
        views.run_progress,
        name="run_progress",
    ),
    path(
        "summaries/read/<int:run_id>/",
        views.summary_read,
        name="read",
    ),
    # Prompt library CRUD (STP-S5)
    path(
        "prompts/",
        views.prompt_list,
        name="prompt_list",
    ),
    path(
        "prompts/create/",
        views.prompt_create,
        name="prompt_create",
    ),
    path(
        "prompts/<int:pk>/edit/",
        views.prompt_edit,
        name="prompt_edit",
    ),
    path(
        "prompts/<int:pk>/delete/",
        views.prompt_delete,
        name="prompt_delete",
    ),
]
