"""Forms for contextual pending-item writes (PEND-S1)."""

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


class PendingItemForm(forms.Form):
    """Create form: catalog type plus mandatory description."""

    item_type = forms.ModelChoiceField(
        queryset=PendingItemType.objects.all(),
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
