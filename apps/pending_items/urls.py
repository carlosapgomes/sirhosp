"""URL routes for pending items: contextual (PEND-S1) and aggregate (PEND-S3)."""

from django.urls import path

from . import views, views_aggregate

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
    path(
        "pendencias/",
        views_aggregate.aggregate,
        name="aggregate",
    ),
    path(
        "pendencias/<int:item_id>/history/",
        views_aggregate.aggregate_history,
        name="aggregate_history",
    ),
    path(
        "pendencias/<int:item_id>/edit/",
        views_aggregate.aggregate_edit,
        name="aggregate_edit",
    ),
    path(
        "pendencias/<int:item_id>/finalize/",
        views_aggregate.aggregate_finalize,
        name="aggregate_finalize",
    ),
]
