from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("search/", include("apps.search.urls")),
    path("", include("apps.ingestion.urls")),
    path("", include("apps.patients.urls")),
    path("", include("apps.core.urls")),
]
