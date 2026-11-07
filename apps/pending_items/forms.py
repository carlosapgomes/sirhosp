"""Forms for contextual pending-item writes (PEND-S1/S1 catalog)."""

from __future__ import annotations

from django import forms

from apps.pending_items.models import (
    STATUS_CLOSED_UNRESOLVED,
    STATUS_RESOLVED,
    PendingItemType,
)

FINALIZE_CHOICES = [
    (STATUS_RESOLVED, "Resolvida"),
    (STATUS_CLOSED_UNRESOLVED, "Encerrada sem resolução"),
]


class PendingItemTypeChoiceField(forms.ModelChoiceField):
    """Type selector labelled ``Categoria > Tipo`` so homonyms differ."""

    def label_from_instance(self, obj: PendingItemType) -> str:
        return f"{obj.category.name} > {obj.name}"


class PendingItemForm(forms.Form):
    """Create form: catalog type plus mandatory description."""

    item_type = PendingItemTypeChoiceField(
        queryset=PendingItemType.objects.select_related("category"),
        label="Tipo",
    )
    description = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Descrição/observação",
    )


class PendingItemEditForm(PendingItemForm):
    """Edit form: same fields plus the observed version token."""

    expected_version = forms.IntegerField(widget=forms.HiddenInput)


class PendingItemFinalizeForm(forms.Form):
    """Finalize form: final status plus an optional note."""

    target_status = forms.ChoiceField(
        choices=FINALIZE_CHOICES,
        label="Destino",
    )
    note = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Anotação (opcional)",
        required=False,
    )
    expected_version = forms.IntegerField(widget=forms.HiddenInput)
