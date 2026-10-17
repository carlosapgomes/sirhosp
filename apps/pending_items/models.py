"""Inpatient pending items domain (PEND-S1).

Three small tables: an admin-managed type catalog seeded only with
``Outro``, admission-scoped items without a redundant patient FK, and an
append-only revision history with author/type snapshots.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import ProtectedError

GROUP_NAME = "Desospitalização"
"""Django group whose effective membership authorizes pending-item writes."""

OUTRO_SLUG = "outro"
"""Stable identifier of the protected fallback catalog entry."""

OUTRO_NAME = "Outro"
"""Display name of the protected fallback catalog entry."""

STATUS_ACTIVE = "active"
STATUS_RESOLVED = "resolved"
STATUS_CLOSED_UNRESOLVED = "closed_unresolved"

STATUS_CHOICES = [
    (STATUS_ACTIVE, "Ativa"),
    (STATUS_RESOLVED, "Resolvida"),
    (STATUS_CLOSED_UNRESOLVED, "Encerrada sem resolução"),
]

FINAL_STATUSES = (STATUS_RESOLVED, STATUS_CLOSED_UNRESOLVED)

ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_FINALIZED = "finalized"

ACTION_CHOICES = [
    (ACTION_CREATED, "Criada"),
    (ACTION_UPDATED, "Editada"),
    (ACTION_FINALIZED, "Finalizada"),
]

INELIGIBLE_MESSAGE = (
    "Não há registro de internação ativa para o paciente no momento. "
    "Entre em contato com o administrador."
)
"""Exact PI-03 notice for absent/ambiguous current admissions."""

NOT_CURRENT_MESSAGE = (
    "Esta não é a internação atual do paciente. "
    "Cadastre ou edite pendências apenas na internação atual."
)

CLOSED_EPISODE_MESSAGE = (
    "Esta internação está encerrada. "
    "Pendências de episódios anteriores são somente leitura."
)

OUTRO_PROTECTED_MESSAGE = "O tipo “Outro” é protegido e não pode ser alterado."


class PendingItemTypeQuerySet(models.QuerySet):
    """Block queryset deletes that would remove the protected ``Outro``."""

    def delete(self):  # type: ignore[override]
        if self.filter(slug=OUTRO_SLUG).exists():
            raise ProtectedError(OUTRO_PROTECTED_MESSAGE, list(self[:1]))
        return super().delete()


class PendingItemType(models.Model):
    """Admin-managed catalog of pending-item types, seeded only with Outro."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PendingItemTypeQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(slug=OUTRO_SLUG, name=OUTRO_NAME)
                | ~models.Q(slug=OUTRO_SLUG),
                name="ck_pending_item_type_outro_identity",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_outro(self) -> bool:
        return self.slug == OUTRO_SLUG

    def save(self, *args, **kwargs) -> None:
        if self.pk is not None:
            old = (
                PendingItemType.objects.filter(pk=self.pk)
                .values("slug", "name")
                .first()
            )
            if (
                old is not None
                and old["slug"] == OUTRO_SLUG
                and (self.slug != OUTRO_SLUG or self.name != OUTRO_NAME)
            ):
                raise ValidationError(OUTRO_PROTECTED_MESSAGE)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[override]
        if self.slug == OUTRO_SLUG:
            raise ProtectedError(OUTRO_PROTECTED_MESSAGE, [self])
        return super().delete(*args, **kwargs)


class PendingItem(models.Model):
    """One manual pending item scoped to a single canonical admission."""

    admission = models.ForeignKey(
        "patients.Admission",
        on_delete=models.PROTECT,
        related_name="pending_items",
    )
    item_type = models.ForeignKey(
        PendingItemType,
        on_delete=models.PROTECT,
        related_name="pending_items",
    )
    description = models.TextField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )
    version = models.PositiveIntegerField(default=1)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_by_name = models.CharField(max_length=150, blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    updated_by_name = models.CharField(max_length=150, blank=True, default="")
    is_system_updated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=[STATUS_ACTIVE, *FINAL_STATUSES]),
                name="ck_pending_item_status",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status=STATUS_ACTIVE, finalized_at__isnull=True)
                    | models.Q(
                        status__in=FINAL_STATUSES,
                        finalized_at__isnull=False,
                    )
                ),
                name="ck_pending_item_finalized_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="ck_pending_item_version_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Pendência #{self.pk} ({self.get_status_display()})"

    def clean(self) -> None:
        super().clean()
        if not (self.description or "").strip():
            raise ValidationError({"description": "Descrição é obrigatória."})


class PendingItemRevision(models.Model):
    """Append-only snapshot of one effective item change (v1 = creation)."""

    item = models.ForeignKey(
        PendingItem,
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    item_type = models.ForeignKey(
        PendingItemType,
        on_delete=models.PROTECT,
        related_name="+",
    )
    type_name = models.CharField(max_length=100)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    note = models.TextField(blank=True, default="")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    author_name = models.CharField(max_length=150, blank=True, default="")
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["version"]
        constraints = [
            models.UniqueConstraint(
                fields=["item", "version"],
                name="uq_pending_item_revision_item_version",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="ck_pending_item_revision_version_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Revisão v{self.version} da pendência #{self.item_id}"

    def save(self, *args, **kwargs) -> None:
        if self.pk is not None:
            raise ValidationError("Revisões são somente leitura.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[override]
        raise ProtectedError("Revisões não podem ser excluídas.", [self])
