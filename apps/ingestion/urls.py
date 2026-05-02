"""URL routes for ingestion app: create run and check status."""

from django.urls import path

from . import views

app_name = "ingestion"

urlpatterns = [
    path("ingestao/criar/", views.create_run, name="create_run"),
    path(
        "ingestao/sincronizar-internacoes/",
        views.create_admissions_only,
        name="create_admissions_only",
    ),
    path(
        "ingestao/sincronizar-demograficos/",
        views.create_demographics_only,
        name="sync_demographics",
    ),
    path(
        "ingestao/status/<int:run_id>/progresso/",
        views.run_status_fragment,
        name="run_status_fragment",
    ),
    path("ingestao/status/<int:run_id>/", views.run_status, name="run_status"),
]
