"""URL routes for ingestion app: create run and check status."""

from django.urls import path

from . import views

app_name = "ingestion"

urlpatterns = [
    path("ingestao/criar/", views.create_run, name="create_run"),
    path("ingestao/status/<int:run_id>/", views.run_status, name="run_status"),
]
