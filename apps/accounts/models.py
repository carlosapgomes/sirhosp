"""Portal user profile (design D1/D3/D4, SLICE-AUP-S2).

``UserProfile`` keeps the first-login password-change flag next to the
standard Django auth user (``AUTH_USER_MODEL`` is unchanged). It is created
on demand by the provisioning command and read by
``RequirePasswordChangeMiddleware``.
"""

from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """One-to-one portal profile attached to a Django auth user.

    ``must_change_password`` is True while the user still needs to replace
    the provisional password on ``/perfil/``; only a successful password
    change clears it (provisioning and ``--reset-password`` only arm it).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    must_change_password = models.BooleanField(
        default=False,
        help_text="True until the user replaces the provisional password.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        name = self.user.get_full_name() or self.user.username
        return f"Perfil de {name}"
