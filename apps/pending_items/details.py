"""Typed complementary details of a pending item (STRUCT-PEND-S2, D2/D3).

The seven nullable values below are the only per-profile fields this
change introduces. Null means absent: applicability decides whether the
absence reads as "não informado" or as "não se aplica", and never "Não".

Forms, models and services share these helpers so the rules live in one
place: an explicit submission is merged with the stored values (an older
form cannot erase a new value by omission), values outside the selected
profile are rejected, and removing details that stop applying requires
an explicit confirmation.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Mapping

from django.core.exceptions import ValidationError
from django.utils import timezone as dj_timezone
from django.utils.formats import date_format

# The four fixed profile identifiers are declared in ``models``; they are
# repeated here because ``models`` imports this module for validation and
# a module-level import back would be circular. ``test_pending_items_
# details`` asserts both spellings stay identical.
PROFILE_SCHEDULING = "agendamento"
PROFILE_TREATMENT = "tratamento-periodo"
PROFILE_SIMPLE = "registro-simples"
PROFILE_SIGNATURE = "assinatura-documento"

DETAIL_FIELD_NAMES: tuple[str, ...] = (
    "is_scheduled",
    "scheduled_date",
    "treatment_start_date",
    "treatment_end_date",
    "signature_at",
    "contrast",
    "sedation",
)
"""Order used by the model, the form, the snapshot and the presentation."""

BOOLEAN_DETAIL_FIELDS = frozenset({"is_scheduled", "contrast", "sedation"})

DETAIL_LABELS: dict[str, str] = {
    "is_scheduled": "Agendada",
    "scheduled_date": "Data agendada",
    "treatment_start_date": "Início do tratamento",
    "treatment_end_date": "Previsão de término",
    "signature_at": "Assinatura do sumário em",
    "contrast": "Contraste",
    "sedation": "Sedação",
}

PROFILE_DETAIL_FIELDS: dict[str, tuple[str, ...]] = {
    PROFILE_SCHEDULING: ("is_scheduled", "scheduled_date"),
    PROFILE_TREATMENT: ("treatment_start_date", "treatment_end_date"),
    PROFILE_SIMPLE: (),
    PROFILE_SIGNATURE: ("signature_at",),
}

RNM_DETAIL_FIELDS: tuple[str, ...] = ("contrast", "sedation")

YES = "Sim"
NO = "Não"
UNKNOWN = "Não informado"
DATE_UNKNOWN = "Data não informada"

SCHEDULING_ANSWER_MESSAGE = "Informe se está agendada (Sim ou Não)."
SCHEDULED_DATE_MESSAGE = (
    "Informe que a pendência está agendada antes de registrar a data."
)
TREATMENT_ORDER_MESSAGE = "A previsão de término não pode anteceder o início."


class DetailRemovalRequired(ValidationError):
    """Removing stored details needs the explicit confirmation (D3)."""

    def __init__(self, labels: list[str]) -> None:
        self.labels = labels
        super().__init__(
            "Confirme a remoção dos detalhes que deixarão de se aplicar: "
            + ", ".join(labels)
            + "."
        )


def applicable_detail_fields(
    profile: str, has_rnm_complements: bool
) -> tuple[str, ...]:
    """Fields the given profile owns; RNM complements need scheduling."""
    fields = list(PROFILE_DETAIL_FIELDS.get(profile, ()))
    if profile == PROFILE_SCHEDULING and has_rnm_complements:
        fields.extend(RNM_DETAIL_FIELDS)
    return tuple(fields)


def item_type_detail_fields(item_type) -> tuple[str, ...]:
    return applicable_detail_fields(
        item_type.profile, item_type.has_rnm_complements
    )


def stored_details(source) -> dict[str, object]:
    """Snapshot of the seven values of an item, a revision or a mapping."""
    if isinstance(source, Mapping):
        return {name: source.get(name) for name in DETAIL_FIELD_NAMES}
    return {name: getattr(source, name) for name in DETAIL_FIELD_NAMES}


def detail_snapshot(source) -> dict[str, object]:
    """Keyword arguments copied into a revision row."""
    return stored_details(source)


def normalise_submitted_details(
    submitted: Mapping[str, object]
) -> dict[str, object]:
    """Reject unknown keys and non-tri-state booleans.

    Direct writers receive parsed values; this keeps ``0``/``""``/``"nao"``
    from being silently coerced into a stored answer.
    """
    cleaned: dict[str, object] = {}
    for name, value in submitted.items():
        if name not in DETAIL_FIELD_NAMES:
            raise ValidationError(
                f"Campo complementar desconhecido: {name}."
            )
        if name in BOOLEAN_DETAIL_FIELDS and not (
            value is None or isinstance(value, bool)
        ):
            raise ValidationError(
                {name: "Use Sim, Não ou Não informado."}
            )
        cleaned[name] = value
    return cleaned


def resolve_details(
    *, submitted: Mapping[str, object], stored: Mapping[str, object]
) -> dict[str, object]:
    """Merge an explicit submission with the stored values.

    A key that was not submitted is preserved (an older surface cannot
    erase a new value by omission); an explicitly empty value clears it.
    """
    return {
        name: (
            submitted[name] if name in submitted else stored.get(name)
        )
        for name in DETAIL_FIELD_NAMES
    }


def forced_removal_fields(
    *,
    profile: str,
    has_rnm_complements: bool,
    stored: Mapping[str, object],
    resolved: Mapping[str, object],
) -> list[str]:
    """Stored values the submitted classification would silently drop."""
    applicable = applicable_detail_fields(profile, has_rnm_complements)
    removals = [
        name
        for name in DETAIL_FIELD_NAMES
        if stored.get(name) is not None and name not in applicable
    ]
    if (
        stored.get("scheduled_date") is not None
        and resolved.get("is_scheduled") is not True
        and "scheduled_date" not in removals
    ):
        removals.append("scheduled_date")
    return removals


def validate_detail_placement(
    profile: str, has_rnm_complements: bool, values: Mapping[str, object]
) -> None:
    """Reject values that do not belong to the selected profile."""
    applicable = applicable_detail_fields(profile, has_rnm_complements)
    errors = {}
    for name in DETAIL_FIELD_NAMES:
        if values.get(name) is None or name in applicable:
            continue
        errors[name] = f"{DETAIL_LABELS[name]} não se aplica a este tipo."
    if errors:
        raise ValidationError(errors)


def validate_detail_coherence(values: Mapping[str, object]) -> None:
    """Local rules that do not depend on the catalog relation (D3)."""
    if values.get("scheduled_date") is not None and (
        values.get("is_scheduled") is not True
    ):
        raise ValidationError({"scheduled_date": SCHEDULED_DATE_MESSAGE})
    start = values.get("treatment_start_date")
    end = values.get("treatment_end_date")
    if isinstance(start, date) and isinstance(end, date) and end < start:
        raise ValidationError({"treatment_end_date": TREATMENT_ORDER_MESSAGE})


def require_scheduling_answer(
    profile: str, values: Mapping[str, object]
) -> None:
    """New and edited scheduling records need an explicit Sim/Não (D2)."""
    if profile == PROFILE_SCHEDULING and values.get("is_scheduled") is None:
        raise ValidationError({"is_scheduled": SCHEDULING_ANSWER_MESSAGE})


def plan_details(
    *,
    profile: str,
    has_rnm_complements: bool,
    stored: Mapping[str, object],
    submitted: Mapping[str, object],
    confirm_removal: bool = False,
) -> tuple[dict[str, object], list[str]]:
    """Return the effective values and the labels removed on purpose.

    Raises ``DetailRemovalRequired`` when stored details would disappear
    without the explicit confirmation required by D3.
    """
    resolved = resolve_details(
        submitted=normalise_submitted_details(submitted), stored=stored
    )
    removals = forced_removal_fields(
        profile=profile,
        has_rnm_complements=has_rnm_complements,
        stored=stored,
        resolved=resolved,
    )
    labels = [DETAIL_LABELS[name] for name in removals]
    if removals and not confirm_removal:
        raise DetailRemovalRequired(labels)
    for name in removals:
        resolved[name] = None
    validate_detail_placement(profile, has_rnm_complements, resolved)
    require_scheduling_answer(profile, resolved)
    validate_detail_coherence(resolved)
    return resolved, labels


def removal_labels_for_type(
    *,
    profile: str,
    has_rnm_complements: bool,
    stored: Mapping[str, object],
) -> list[str]:
    """Labels the given type would drop from the stored state, if any."""
    applicable = applicable_detail_fields(profile, has_rnm_complements)
    return [
        DETAIL_LABELS[name]
        for name in DETAIL_FIELD_NAMES
        if stored.get(name) is not None and name not in applicable
    ]


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return None
    return value if isinstance(value, date) else None


def _as_datetime(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _format_date(value: object) -> str:
    parsed = _as_date(value)
    return date_format(parsed, "d/m/Y") if parsed is not None else ""


def _format_datetime(value: object) -> str:
    """Institutional wall clock; the stored instant is never re-written."""
    parsed = _as_datetime(value)
    if parsed is None:
        return ""
    return date_format(dj_timezone.localtime(parsed), "d/m/Y H:i")


def _tri_state(value: object, *, missing: str = UNKNOWN) -> str:
    if value is True:
        return YES
    if value is False:
        return NO
    return missing


def detail_rows(
    profile: str | None,
    has_rnm_complements: bool | None,
    values: Mapping[str, object],
) -> list[dict[str, str]]:
    """Shared presentation of the applicable details (D6).

    Only information that applies to the profile is rendered; an
    applicable absence is explicit instead of being read as Não.
    """
    if profile is None:
        return []
    applicable = applicable_detail_fields(
        profile, bool(has_rnm_complements)
    )
    rows: list[dict[str, str]] = []
    if "is_scheduled" in applicable:
        answer = values.get("is_scheduled")
        rows.append(
            {"label": DETAIL_LABELS["is_scheduled"], "value": _tri_state(answer)}
        )
        scheduled_date = values.get("scheduled_date")
        if answer is False and scheduled_date is None:
            pass
        elif scheduled_date is None:
            if answer is True:
                rows.append(
                    {
                        "label": DETAIL_LABELS["scheduled_date"],
                        "value": DATE_UNKNOWN,
                    }
                )
            else:
                rows.append(
                    {
                        "label": DETAIL_LABELS["scheduled_date"],
                        "value": UNKNOWN,
                    }
                )
        else:
            rows.append(
                {
                    "label": DETAIL_LABELS["scheduled_date"],
                    "value": _format_date(scheduled_date),
                }
            )
    for name in ("treatment_start_date", "treatment_end_date"):
        if name in applicable:
            value = values.get(name)
            rows.append(
                {
                    "label": DETAIL_LABELS[name],
                    "value": _format_date(value) if value else UNKNOWN,
                }
            )
    if "signature_at" in applicable:
        value = values.get("signature_at")
        rows.append(
            {
                "label": DETAIL_LABELS["signature_at"],
                "value": _format_datetime(value) if value else UNKNOWN,
            }
        )
    for name in RNM_DETAIL_FIELDS:
        if name in applicable:
            rows.append(
                {
                    "label": DETAIL_LABELS[name],
                    "value": _tri_state(values.get(name)),
                }
            )
    return rows


def attempted_detail_rows(post_data: Mapping[str, object]) -> list[str]:
    """Human summary of the detail values a rejected POST attempted."""
    rows: list[str] = []
    for name in DETAIL_FIELD_NAMES:
        if name not in post_data:
            continue
        raw = post_data.get(name)
        text = str(raw).strip() if raw is not None else ""
        if not text:
            continue
        if name in BOOLEAN_DETAIL_FIELDS:
            display = YES if text in ("sim", "True") else NO
        elif name in ("scheduled_date", "treatment_start_date", "treatment_end_date"):
            display = text
            try:
                display = _format_date(date.fromisoformat(text))
            except ValueError:
                pass
        elif name == "signature_at":
            display = text.replace("T", " ")
        else:  # pragma: no cover - every name is covered above
            display = text
        rows.append(f"{DETAIL_LABELS[name]}: {display}")
    return rows
