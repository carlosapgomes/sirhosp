"""URL routes for patient navigation (Slice S4)."""

from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path(
        "patients/<int:patient_id>/admissions/",
        views.admission_list_view,
        name="admission_list",
    ),
    path(
        "admissions/<int:admission_id>/timeline/",
        views.timeline_view,
        name="timeline",
    ),
]
