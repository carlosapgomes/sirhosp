"""Portal profile page and self-service password change (SLICE-AUP-S1).

Shows the authenticated user's read-only identity (username, full name,
e-mail, last login, role) plus a password-change form built on
``django.contrib.auth.forms.PasswordChangeForm``. A successful change saves
the new password and rehashes the session auth hash so the current session
survives (design decision D2).
"""

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic.edit import FormView

COMMON_ROLE = "usuário comum"
ADMIN_ROLE = "admin"


class ProfileView(LoginRequiredMixin, FormView):
    """Read-only profile identity plus self-service password change."""

    form_class = PasswordChangeForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")

    def get_form_kwargs(self) -> dict:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Meu Perfil"
        context["role"] = (
            ADMIN_ROLE if self.request.user.is_superuser else COMMON_ROLE
        )
        return context

    def form_valid(self, form):
        form.save()
        update_session_auth_hash(self.request, self.request.user)
        messages.success(self.request, "Senha alterada com sucesso.")
        return super().form_valid(form)
