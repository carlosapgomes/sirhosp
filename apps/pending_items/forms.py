"""Forms for contextual pending-item writes (STRUCT-PEND-S2, D5).

One progressive form is shared by the contextual cadastro, the edit page
and the quick-edit modal: category narrows the type list, the selected
type decides which typed details are applicable, and the same domain
helpers validate the submission. Observation is optional except for the
generic catalog entries.
"""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import ModelChoiceField

from apps.pending_items import details
from apps.pending_items.models import (
    STATUS_CLOSED_UNRESOLVED,
    STATUS_RESOLVED,
    PendingItem,
    PendingItemCategory,
    PendingItemType,
)

FINALIZE_CHOICES = [
    (STATUS_RESOLVED, "Resolvida"),
    (STATUS_CLOSED_UNRESOLVED, "Encerrada sem resolução"),
]

YES_NO_CHOICES = [
    ("", details.UNKNOWN),
    ("sim", details.YES),
    ("nao", details.NO),
]
"""Agendada, Contraste and Sedação share the same tri-state control."""

DATE_INPUT_FORMATS = ["%Y-%m-%d", "%d/%m/%Y"]
DATETIME_INPUT_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%d/%m/%Y %H:%M",
]

DESCRIPTION_REQUIRED_MESSAGE = "Descrição é obrigatória."
CATEGORY_TYPE_MISMATCH_MESSAGE = "Selecione um tipo da categoria escolhida."


def _coerce_yes_no(value: str) -> bool:
    return value == "sim"


def _yes_no_choice(value: object) -> str:
    """Map a stored boolean to the tri-state control value."""
    if value is True:
        return "sim"
    if value is False:
        return "nao"
    return ""


class YesNoField(forms.TypedChoiceField):
    """Tri-state Sim/Não/Não informado; absence is never coerced to Não."""

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("choices", YES_NO_CHOICES)
        kwargs.setdefault("coerce", _coerce_yes_no)
        kwargs.setdefault("empty_value", None)
        kwargs.setdefault("required", False)
        kwargs.setdefault(
            "widget", forms.Select(attrs={"class": "form-select"})
        )
        super().__init__(**kwargs)

    def prepare_value(self, value):
        return _yes_no_choice(value)


class PendingItemTypeChoiceField(forms.ModelChoiceField):
    """Type selector labelled ``Categoria > Tipo`` so homonyms differ."""

    def label_from_instance(self, obj: PendingItemType) -> str:
        return f"{obj.category.name} > {obj.name}"


class PendingItemForm(forms.Form):
    """Create/edit form: classification, typed details and observations."""

    category = forms.ModelChoiceField(
        queryset=PendingItemCategory.objects.all(),
        label="Categoria",
        required=False,
        empty_label="Selecione…",
        widget=forms.Select(
            attrs={
                "class": "form-select",
                "aria-describedby": "pending-category-hint",
            }
        ),
    )
    item_type = PendingItemTypeChoiceField(
        queryset=PendingItemType.objects.select_related("category"),
        label="Tipo",
        widget=forms.Select(
            attrs={
                "class": "form-select",
                "aria-describedby": "pending-type-hint",
            }
        ),
    )
    is_scheduled = YesNoField(
        label="Agendada?",
        widget=forms.Select(
            attrs={
                "class": "form-select",
                "aria-describedby": "pending-is-scheduled-hint",
            }
        ),
    )
    scheduled_date = forms.DateField(
        label="Data agendada",
        required=False,
        input_formats=DATE_INPUT_FORMATS,
        widget=forms.DateInput(
            format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}
        ),
    )
    treatment_start_date = forms.DateField(
        label="Início do tratamento",
        required=False,
        input_formats=DATE_INPUT_FORMATS,
        widget=forms.DateInput(
            format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}
        ),
    )
    treatment_end_date = forms.DateField(
        label="Previsão de término",
        required=False,
        input_formats=DATE_INPUT_FORMATS,
        widget=forms.DateInput(
            format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}
        ),
    )
    signature_at = forms.DateTimeField(
        label="Assinatura do sumário em",
        required=False,
        input_formats=DATETIME_INPUT_FORMATS,
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local", "class": "form-control"},
        ),
    )
    contrast = YesNoField(
        label="Contraste",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    sedation = YesNoField(
        label="Sedação",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    description = forms.CharField(
        label="Observações",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "class": "form-control",
                "aria-describedby": "pending-description-hint",
            }
        ),
    )
    confirm_detail_removal = forms.BooleanField(
        label="Confirmo a remoção destes detalhes",
        required=False,
    )

    def __init__(self, *args, item: PendingItem | None = None, **kwargs) -> None:
        self.item = item
        self.stored = details.stored_details(item) if item is not None else {}
        super().__init__(*args, **kwargs)
        if item is not None and not self.is_bound:
            self.initial.setdefault("category", item.item_type.category_id)
            self.initial.setdefault("item_type", item.item_type_id)
            self.initial.setdefault("description", item.description)
            for name in details.DETAIL_FIELD_NAMES:
                self.initial.setdefault(name, self.stored.get(name))
        category_field = self.fields["category"]
        assert isinstance(category_field, ModelChoiceField)
        self.category_options = [
            {
                "pk": category.pk,
                "slug": category.slug,
                "label": category.name,
            }
            for category in category_field.queryset or []
        ]
        self.type_options = self._build_type_options()
        self.selected_option = self._selected_type_option()
        self.removal_labels = self._selected_removal_labels()
        self.needs_removal_confirmation = False

    def _build_type_options(self) -> list[dict[str, object]]:
        options = []
        type_field = self.fields["item_type"]
        assert isinstance(type_field, ModelChoiceField)
        for item_type in type_field.queryset or []:
            options.append(
                {
                    "value": item_type.pk,
                    "label": f"{item_type.category.name} > {item_type.name}",
                    "category": str(item_type.category_id),
                    "profile": item_type.profile,
                    "rnm": "1" if item_type.has_rnm_complements else "0",
                    "requires_description": (
                        "1" if item_type.requires_description else "0"
                    ),
                    "removals": "|".join(
                        details.removal_labels_for_type(
                            profile=item_type.profile,
                            has_rnm_complements=item_type.has_rnm_complements,
                            stored=self.stored,
                        )
                    ),
                }
            )
        return options

    def _selected_type_option(self) -> dict[str, object] | None:
        raw = self["item_type"].value()
        try:
            selected_pk = int(raw)
        except (TypeError, ValueError):
            return None
        for option in self.type_options:
            if option["value"] == selected_pk:
                return option
        return None

    def _selected_removal_labels(self) -> list[str]:
        option = self.selected_option
        if option is None:
            return []
        removal = str(option["removals"] or "")
        return [label for label in removal.split("|") if label]

    def clean(self):
        cleaned = super().clean()
        item_type = cleaned.get("item_type")
        if item_type is None:
            return cleaned
        category = cleaned.get("category")
        if category is not None and item_type.category_id != category.pk:
            self.add_error("item_type", CATEGORY_TYPE_MISMATCH_MESSAGE)
        text = (cleaned.get("description") or "").strip()
        if item_type.requires_description and not text:
            self.add_error("description", DESCRIPTION_REQUIRED_MESSAGE)
        cleaned["description"] = text
        submitted = {
            name: cleaned.get(name)
            for name in details.DETAIL_FIELD_NAMES
            if name in self.data
        }
        cleaned["submitted_details"] = submitted
        try:
            details.plan_details(
                profile=item_type.profile,
                has_rnm_complements=item_type.has_rnm_complements,
                stored=self.stored,
                submitted=submitted,
                confirm_removal=bool(cleaned.get("confirm_detail_removal")),
            )
        except details.DetailRemovalRequired as exc:
            self.removal_labels = exc.labels
            self.needs_removal_confirmation = True
            self.add_error(None, exc)
        except ValidationError as exc:
            for field, messages in exc.message_dict.items():
                self.add_error(field, messages)
        return cleaned


class PendingItemEditForm(PendingItemForm):
    """Edit form: same fields plus the observed version token."""

    expected_version = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, *args, item: PendingItem | None = None, **kwargs) -> None:
        super().__init__(*args, item=item, **kwargs)
        if item is not None and not self.is_bound:
            self.initial.setdefault("expected_version", item.version)


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
