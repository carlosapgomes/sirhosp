"""Inpatient pending items domain (PEND-S1/S1 catalog).

Four small tables: admin-managed catalog categories and types, admission
scoped items without a redundant patient FK, and an append-only revision
history with author, type and observed-classification snapshots.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import ProtectedError

from apps.pending_items import details

GROUP_NAME = "Desospitalização"
"""Django group whose effective membership authorizes pending-item writes."""

OUTRO_SLUG = "outro"
"""Stable identifier of the protected fallback catalog entry."""

OUTRO_NAME = "Outro"
"""Display name of the protected fallback catalog entry."""

CATEGORY_SLUG_OUTRAS_PENDENCIAS = "outras-pendencias"
"""Stable identifier of the category that every preserved legacy type uses."""

PROFILE_SCHEDULING = "agendamento"
PROFILE_TREATMENT = "tratamento-periodo"
PROFILE_SIMPLE = "registro-simples"
PROFILE_SIGNATURE = "assinatura-documento"

PROFILE_CHOICES = [
    (PROFILE_SCHEDULING, "Agendamento"),
    (PROFILE_TREATMENT, "Tratamento com período"),
    (PROFILE_SIMPLE, "Registro simples"),
    (PROFILE_SIGNATURE, "Assinatura de documento"),
]

PROFILE_VALUES = tuple(value for value, _label in PROFILE_CHOICES)
"""The four fixed form profiles a catalog type may declare (S1, D1)."""

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

SLUG_IMMUTABLE_MESSAGE = (
    "O identificador (slug) é definido na criação e não pode ser alterado."
)

TYPE_CONTRACT_PROTECTED_MESSAGE = (
    "Este tipo já é usado por pendências ou versões: categoria, perfil, "
    "complementos RNM e obrigatoriedade de observações não podem mudar."
)


class PendingItemCategory(models.Model):
    """Administrative grouping of catalog types with a stable slug (S1)."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        if self.pk is None:
            return
        stored_slug = (
            PendingItemCategory.objects.filter(pk=self.pk)
            .values_list("slug", flat=True)
            .first()
        )
        if stored_slug is not None and stored_slug != self.slug:
            raise ValidationError({"slug": SLUG_IMMUTABLE_MESSAGE})

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)


class PendingItemTypeQuerySet(models.QuerySet):
    """Block queryset deletes that would remove the protected ``Outro``."""

    def delete(self):  # type: ignore[override]
        if self.filter(slug=OUTRO_SLUG).exists():
            raise ProtectedError(OUTRO_PROTECTED_MESSAGE, list(self[:1]))
        return super().delete()


class PendingItemType(models.Model):
    """Admin-managed catalog of pending-item types grouped by category."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    category = models.ForeignKey(
        PendingItemCategory,
        on_delete=models.PROTECT,
        related_name="types",
    )
    profile = models.CharField(max_length=32, choices=PROFILE_CHOICES)
    has_rnm_complements = models.BooleanField(default=False)
    requires_description = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PendingItemTypeQuerySet.as_manager()

    class Meta:
        ordering = ["category__name", "name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(slug=OUTRO_SLUG, name=OUTRO_NAME)
                | ~models.Q(slug=OUTRO_SLUG),
                name="ck_pending_item_type_outro_identity",
            ),
            models.CheckConstraint(
                condition=models.Q(profile__in=PROFILE_VALUES),
                name="ck_pending_item_type_profile",
            ),
            models.CheckConstraint(
                condition=models.Q(has_rnm_complements=False)
                | models.Q(profile=PROFILE_SCHEDULING),
                name="ck_pending_item_type_rnm_requires_scheduling",
            ),
            models.UniqueConstraint(
                fields=["category", "name"],
                name="uq_pending_item_type_category_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_outro(self) -> bool:
        return self.slug == OUTRO_SLUG

    def is_referenced(self) -> bool:
        """True when an item or any revision references this type (D1)."""
        if self.pk is None:
            return False
        return (
            PendingItem.objects.filter(item_type_id=self.pk).exists()
            or PendingItemRevision.objects.filter(item_type_id=self.pk).exists()
        )

    def clean(self) -> None:
        super().clean()
        if self.pk is None:
            return
        stored = (
            PendingItemType.objects.filter(pk=self.pk)
            .values(
                "slug",
                "name",
                "category_id",
                "profile",
                "has_rnm_complements",
                "requires_description",
            )
            .first()
        )
        if stored is None:
            return
        if stored["slug"] != self.slug:
            raise ValidationError({"slug": SLUG_IMMUTABLE_MESSAGE})
        if stored["slug"] == OUTRO_SLUG:
            category_slug = self.category.slug if self.category_id else None
            if (
                self.name != OUTRO_NAME
                or self.profile != PROFILE_SIMPLE
                or self.has_rnm_complements
                or not self.requires_description
                or category_slug != CATEGORY_SLUG_OUTRAS_PENDENCIAS
            ):
                raise ValidationError(OUTRO_PROTECTED_MESSAGE)
            return
        contract_changed = (
            stored["category_id"] != self.category_id
            or stored["profile"] != self.profile
            or stored["has_rnm_complements"] != self.has_rnm_complements
            or stored["requires_description"] != self.requires_description
        )
        if contract_changed and self.is_referenced():
            raise ValidationError(TYPE_CONTRACT_PROTECTED_MESSAGE)

    def save(self, *args, **kwargs) -> None:
        self.clean()
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
    is_scheduled = models.BooleanField(null=True, blank=True)
    scheduled_date = models.DateField(null=True, blank=True)
    treatment_start_date = models.DateField(null=True, blank=True)
    treatment_end_date = models.DateField(null=True, blank=True)
    signature_at = models.DateTimeField(null=True, blank=True)
    contrast = models.BooleanField(null=True, blank=True)
    sedation = models.BooleanField(null=True, blank=True)
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
            models.CheckConstraint(
                condition=models.Q(scheduled_date__isnull=True)
                | models.Q(is_scheduled__isnull=False, is_scheduled=True),
                name="ck_pending_item_scheduled_date_requires_yes",
            ),
            models.CheckConstraint(
                condition=models.Q(treatment_start_date__isnull=True)
                | models.Q(treatment_end_date__isnull=True)
                | models.Q(
                    treatment_end_date__gte=models.F("treatment_start_date")
                ),
                name="ck_pending_item_treatment_period_order",
            ),
        ]

    def __str__(self) -> str:
        return f"Pendência #{self.pk} ({self.get_status_display()})"

    @property
    def detail_rows(self) -> list[dict[str, str]]:
        """Shared presentation of this item's applicable details (D6)."""
        return details.detail_rows(
            self.item_type.profile,
            self.item_type.has_rnm_complements,
            details.stored_details(self),
        )

    def clean(self) -> None:
        super().clean()
        if not self.item_type_id:
            return
        item_type = self.item_type
        if item_type.requires_description and not (
            self.description or ""
        ).strip():
            raise ValidationError({"description": "Descrição é obrigatória."})
        values = details.stored_details(self)
        details.validate_detail_placement(
            item_type.profile, item_type.has_rnm_complements, values
        )
        details.validate_detail_coherence(values)


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
    type_slug = models.SlugField(max_length=100, null=True, blank=True)
    category_name = models.CharField(max_length=100, null=True, blank=True)
    category_slug = models.SlugField(max_length=100, null=True, blank=True)
    profile = models.CharField(
        max_length=32, choices=PROFILE_CHOICES, null=True, blank=True
    )
    has_rnm_complements = models.BooleanField(null=True, blank=True)
    requires_description = models.BooleanField(null=True, blank=True)
    description = models.TextField()
    is_scheduled = models.BooleanField(null=True, blank=True)
    scheduled_date = models.DateField(null=True, blank=True)
    treatment_start_date = models.DateField(null=True, blank=True)
    treatment_end_date = models.DateField(null=True, blank=True)
    signature_at = models.DateTimeField(null=True, blank=True)
    contrast = models.BooleanField(null=True, blank=True)
    sedation = models.BooleanField(null=True, blank=True)
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
            models.CheckConstraint(
                condition=models.Q(profile__isnull=True)
                | models.Q(profile__in=PROFILE_VALUES),
                name="ck_pending_item_revision_profile",
            ),
            models.CheckConstraint(
                condition=models.Q(profile__isnull=True)
                | models.Q(has_rnm_complements__isnull=True)
                | models.Q(has_rnm_complements=False)
                | models.Q(profile=PROFILE_SCHEDULING),
                name="ck_pending_item_revision_rnm_requires_scheduling",
            ),
            models.CheckConstraint(
                condition=models.Q(scheduled_date__isnull=True)
                | models.Q(is_scheduled__isnull=False, is_scheduled=True),
                name="ck_pending_item_revision_scheduled_date_requires_yes",
            ),
            models.CheckConstraint(
                condition=models.Q(treatment_start_date__isnull=True)
                | models.Q(treatment_end_date__isnull=True)
                | models.Q(
                    treatment_end_date__gte=models.F("treatment_start_date")
                ),
                name="ck_pending_item_revision_treatment_period_order",
            ),
        ]

    def __str__(self) -> str:
        return f"Revisão v{self.version} da pendência #{self.item_id}"

    @property
    def details_known(self) -> bool:
        """False for versions written before the classification snapshot."""
        return self.profile is not None

    @property
    def detail_rows(self) -> list[dict[str, str]]:
        """Shared presentation using the metadata observed by the version."""
        return details.detail_rows(
            self.profile,
            self.has_rnm_complements,
            details.stored_details(self),
        )

    def clean(self) -> None:
        super().clean()
        if self.profile is None:
            return
        values = details.stored_details(self)
        details.validate_detail_placement(
            self.profile, bool(self.has_rnm_complements), values
        )
        details.validate_detail_coherence(values)

    def save(self, *args, **kwargs) -> None:
        if self.pk is not None:
            raise ValidationError("Revisões são somente leitura.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[override]
        raise ProtectedError("Revisões não podem ser excluídas.", [self])
