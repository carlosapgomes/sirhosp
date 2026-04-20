"""URL routes for search (Slice S3)."""

from django.urls import path

from . import views

app_name = "search"

urlpatterns = [
    path("clinical-events/", views.search_clinical_events_view, name="clinical_events"),
]
