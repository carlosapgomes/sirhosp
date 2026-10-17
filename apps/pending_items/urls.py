"""URL routes for contextual pending items (PEND-S1)."""

from django.urls import path

from . import views

app_name = "pending_items"

urlpatterns = [
    path(
        "admissions/<int:admission_id>/pending-items/",
        views.admission_pending_items,
        name="admission_items",
    ),
    path(
        "admissions/<int:admission_id>/pending-items/<int:item_id>/edit/",
        views.pending_item_edit,
        name="item_edit",
    ),
    path(
        "admissions/<int:admission_id>/pending-items/<int:item_id>/finalize/",
        views.pending_item_finalize,
        name="item_finalize",
    ),
    path(
        "admissions/<int:admission_id>/pending-items/<int:item_id>/history/",
        views.pending_item_history,
        name="item_history",
    ),
]
