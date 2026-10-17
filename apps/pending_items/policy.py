"""Write policy for pending items (PEND-S1, D2).

Human writes require effective membership in the ``Desospitalização``
group. ``is_staff``/``is_superuser`` never substitute for membership, so
the check deliberately avoids ``has_perm``, whose default behavior lets
superusers bypass object-agnostic permissions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied

from apps.pending_items.models import GROUP_NAME

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser, AnonymousUser

WRITE_DENIED_MESSAGE = (
    "A escrita de pendências exige associação ao grupo Desospitalização."
)


def can_write_pending_items(user: AbstractUser | AnonymousUser) -> bool:
    """Return True only for authenticated effective group members."""
    if not getattr(user, "is_authenticated", False):
        return False
    return user.groups.filter(name=GROUP_NAME).exists()  # type: ignore[union-attr]


def require_can_write(user: AbstractUser | AnonymousUser) -> None:
    """Raise PermissionDenied unless the user may write pending items."""
    if not can_write_pending_items(user):
        raise PermissionDenied(WRITE_DENIED_MESSAGE)
