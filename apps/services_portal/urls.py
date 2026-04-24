"""URL routes for services portal: dashboard, census, risk monitor."""

from django.urls import path

from . import views

app_name = "services_portal"

urlpatterns = [
    path("painel/", views.dashboard, name="dashboard"),
    path("censo/", views.censo, name="censo"),
    path("monitor/", views.monitor_risco, name="monitor_risco"),
]
