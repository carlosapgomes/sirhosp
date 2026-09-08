"""URL configuration for the accounts app (SLICE-AUP-S1).

Only the portal profile route lives here for now; the forced password
change and provisioning command arrive in SLICE-AUP-S2.
"""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("perfil/", views.ProfileView.as_view(), name="profile"),
]
