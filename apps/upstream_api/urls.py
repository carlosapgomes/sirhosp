from django.urls import path

from . import views

app_name = "upstream_api"

urlpatterns = [
    path("inpatients/current", views.current_inpatients, name="current_inpatients"),
    path(
        "patients/<str:prontuario>",
        views.patient_demographics,
        name="patient_demographics",
    ),
]
