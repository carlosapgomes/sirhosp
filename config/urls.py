from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("search/", include("apps.search.urls")),
    path("", include("django.contrib.auth.urls")),
    path("", include("apps.ingestion.urls")),
    path("", include("apps.patients.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.services_portal.urls")),
    path("", include("apps.census.urls")),
]
