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
    path("painel/admissoes/", views.admission_chart, name="admission_chart"),
    path("painel/obitos/", views.death_chart, name="death_chart"),
    path("altas/", views.discharge_list, name="discharge_list"),
    path("admissoes/", views.admission_list, name="admission_list"),
    path("obitos/", views.death_list, name="death_list"),
    path("censo-oficial/", views.official_census_list, name="official_census_list"),
    path("setores/ocupacao/", views.sector_occupation, name="sector_occupation"),
]
