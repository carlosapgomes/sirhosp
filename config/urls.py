from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("search/", include("apps.search.urls")),
    path(
        "login/",
        auth_views.LoginView.as_view(redirect_authenticated_user=True),
        name="login",
    ),
    path("", include("django.contrib.auth.urls")),
    path("", include("apps.ingestion.urls")),
    path("", include("apps.patients.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.services_portal.urls")),
    path("", include("apps.census.urls")),
    path("", include("apps.summaries.urls")),
]
