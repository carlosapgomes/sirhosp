"""URL routes for services portal: dashboard, census, risk monitor, ingestion metrics."""

from django.urls import path

from . import views

app_name = "services_portal"

urlpatterns = [
    path("painel/", views.dashboard, name="dashboard"),
    path("censo/", views.censo, name="censo"),
    path("monitor/", views.monitor_risco, name="monitor_risco"),
    path("metrica-ingestao/", views.ingestion_metrics, name="ingestion_metrics"),
    path("painel/altas/", views.discharge_chart, name="discharge_chart"),
]
