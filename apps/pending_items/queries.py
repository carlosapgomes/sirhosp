"""Conservative aggregate cut for current inpatient pending items.

PEND-S3 (D3/D7/D8): a single shared resolver maps the latest occupied
census photo to at most one canonical open admission per patient. The
aggregate list, the hospital indicators and the future XLSX export all
consume this cut, so ambiguous cases (conflicting beds, ambiguous
identity, two open admissions) are excluded everywhere and equivalent
photo repetitions never duplicate rows. A confirmed exit wins over
residual census presence; previous episodes never enter the cut, while
the explicit contextual lookup stays available elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.contrib.auth.models import User
from django.db.models import Max, QuerySet
from django.http import QueryDict
from django.utils import timezone

from apps.census.models import (
    BedStatus,
    CensusSnapshot,
    PatientMovement,
    Specialty,
)
from apps.patients.models import Admission, Patient
from apps.pending_items.models import (
    FINAL_STATUSES,
    STATUS_ACTIVE,
    PendingItem,
    PendingItemType,
)

FIRST_UNIT_UNKNOWN = "Primeira unidade não identificada"
"""Fallback label when no movement is attributable to the episode."""

SYSTEM_FILTER_VALUE = "system"
"""Last-updater filter value selecting system-written revisions."""

STATUS_ALL = "all"
"""Status filter value disabling the status restriction."""

VIEW_PATIENTS = "patients"
VIEW_ITEMS = "items"

ORDER_DEFAULT = ""
ORDER_TIME_ASC = "tempo_asc"
ORDER_TIME_DESC = "tempo_desc"

AGGREGATE_PER_PAGE = 20
"""Rows per aggregate page: patient groups in patients view, items else."""


@dataclass(frozen=True)
class CurrentOccupation:
    """One included patient: current admission plus its census cell."""

    admission_id: int
    patient_id: int
    prontuario: str
    patient_name: str
    setor: str
    leito: str
    especialidade: str
    census_name: str


@dataclass(frozen=True)
class CurrentCut:
    """Outcome of the shared conservative resolver."""

    captured_at: datetime | None
    occupations: dict[int, CurrentOccupation]


@dataclass(frozen=True)
class AggregateFilters:
    """Validated aggregate filters; time bounds are exact timedeltas."""

    view: str = VIEW_PATIENTS
    status: str = STATUS_ACTIVE
    unidade: str = ""
    leito: str = ""
    especialidade: str = ""
    item_type_id: int | None = None
    creator_id: int | None = None
    updater_id: int | None = None
    updater_system: bool = False
    min_open: timedelta | None = None
    max_open: timedelta | None = None
    ordering: str = ORDER_DEFAULT
    void: bool = False


@dataclass
class PatientGroup:
    """Every matching item of one patient; groups never split on pages."""

    admission_id: int
    occupation: CurrentOccupation
    items: list[PendingItem]


@dataclass(frozen=True)
class HospitalIndicators:
    """Hospital-wide active-cut indicators, filter-independent."""

    patient_count: int
    mean_days: float | None
    max_days: float | None


@dataclass(frozen=True)
class AggregateOptions:
    """Stable dropdown values drawn from the current cut."""

    unidades: list[str]
    leitos: list[str]
    especialidades: list[dict[str, str]]
    tipos: list[PendingItemType]
    criadores: list[User]
    atualizadores: list[User]
    has_system_updates: bool


def latest_captured_at() -> datetime | None:
    """Capture time of the latest census photo.

    Same definition as the census screen and the write eligibility: the
    maximum ``captured_at`` over all snapshots; occupancy is filtered
    afterwards, never before the maximum is taken.
    """
    return CensusSnapshot.objects.aggregate(latest=Max("captured_at"))["latest"]


# Shared conservative classification (design D3): one status vocabulary
# consumed by both the aggregate cut and the write eligibility, so the
# rule can never diverge between surfaces.
CUT_OK = "ok"
CUT_ABSENT = "absent"
CUT_AMBIGUOUS_IDENTITY = "ambiguous_identity"
CUT_AMBIGUOUS_OCCUPATION = "ambiguous_occupation"
CUT_MULTIPLE_OPEN = "multiple_open"


@dataclass(frozen=True)
class PatientCutClassification:
    """Conservative outcome of the shared cut rule for one patient."""

    status: str
    patient_id: int | None
    open_admission_id: int | None
    occupation: tuple[str, str] | None


def classify_patient(
    *,
    cells: set[tuple[str, str]],
    identity_rows: list[tuple[int, str]],
    open_ids: list[int],
) -> PatientCutClassification:
    """Classify one patient against the shared conservative rule.

    ``cells`` are the distinct occupied (setor, leito) cells of the latest
    photo for the record key (equivalent repetitions count once);
    ``identity_rows`` are ``(patient_pk, name)`` candidates sharing the
    record key; ``open_ids`` are the canonical open admission ids of the
    unique candidate (ignored otherwise). Pure on purpose: the aggregate
    feeds it from bulk queries, the eligibility from single-patient ones.
    """
    if not cells:
        return PatientCutClassification(CUT_ABSENT, None, None, None)
    if len(cells) > 1:
        return PatientCutClassification(
            CUT_AMBIGUOUS_OCCUPATION, None, None, None
        )
    if len(identity_rows) != 1:
        return PatientCutClassification(
            CUT_AMBIGUOUS_IDENTITY, None, None, None
        )
    patient_id, _name = identity_rows[0]
    if len(open_ids) != 1:
        return PatientCutClassification(
            CUT_MULTIPLE_OPEN, patient_id, None, None
        )
    return PatientCutClassification(
        CUT_OK, patient_id, open_ids[0], next(iter(cells))
    )


@dataclass(frozen=True)
class PatientCutDetail:
    """Single-patient inputs for the shared classification rule."""

    has_photo: bool
    cells: set[tuple[str, str]]
    identity_rows: list[tuple[int, str]]
    open_ids: list[int]


def resolve_patient_detail(source_key: str) -> PatientCutDetail:
    """Fetch the shared-rule inputs for one record key (write side)."""
    latest = latest_captured_at()
    if latest is None:
        return PatientCutDetail(False, set(), [], [])
    cells = set(
        CensusSnapshot.objects.filter(
            captured_at=latest,
            bed_status=BedStatus.OCCUPIED,
            prontuario=source_key,
        ).values_list("setor", "leito")
    )
    identity_rows = list(
        Patient.objects.filter(patient_source_key=source_key).values_list(
            "pk", "name"
        )
    )
    open_ids: list[int] = []
    if len(identity_rows) == 1:
        open_ids = list(
            Admission.objects.filter(
                patient_id=identity_rows[0][0],
                discharge_date__isnull=True,
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )
    return PatientCutDetail(True, cells, identity_rows, open_ids)


def resolve_current_cut() -> CurrentCut:
    """Map the latest occupied photo to current admissions, conservatively.

    Shared classification with the write eligibility (design D3): excludes
    conflicting beds for one patient, ambiguous identity and patients without
    exactly one canonical open admission — the latter covers both residual
    presence after a confirmed exit and two open candidates. Equivalent
    repetitions of one (setor, leito) cell count once, using the earliest row
    for display. Never invents patients or links.
    """
    latest = latest_captured_at()
    if latest is None:
        return CurrentCut(captured_at=None, occupations={})
    beds: dict[str, set[tuple[str, str]]] = {}
    first_cell: dict[tuple[str, str, str], tuple[str, str]] = {}
    rows = (
        CensusSnapshot.objects.filter(
            captured_at=latest, bed_status=BedStatus.OCCUPIED
        )
        .exclude(prontuario="")
        .order_by("pk")
        .values_list("prontuario", "setor", "leito", "especialidade", "nome")
    )
    for prontuario, setor, leito, especialidade, nome in rows:
        beds.setdefault(prontuario, set()).add((setor, leito))
        first_cell.setdefault(
            (prontuario, setor, leito), (especialidade, nome)
        )
    single = {key: cells for key, cells in beds.items() if len(cells) == 1}
    if not single:
        return CurrentCut(captured_at=latest, occupations={})
    found: dict[str, list[tuple[int, str]]] = {key: [] for key in single}
    for key, pk, name in Patient.objects.filter(
        patient_source_key__in=list(single)
    ).values_list("patient_source_key", "pk", "name"):
        found[key].append((pk, name))
    identified = {key: rows for key, rows in found.items() if len(rows) == 1}
    if not identified:
        return CurrentCut(captured_at=latest, occupations={})
    patient_ids = [rows[0][0] for rows in identified.values()]
    open_by_patient: dict[int, list[int]] = {pid: [] for pid in patient_ids}
    for pid, aid in (
        Admission.objects.filter(
            patient_id__in=patient_ids, discharge_date__isnull=True
        )
        .order_by("pk")
        .values_list("patient_id", "pk")
    ):
        open_by_patient[pid].append(aid)
    occupations: dict[int, CurrentOccupation] = {}
    for key, identity_rows in identified.items():
        outcome = classify_patient(
            cells=single[key],
            identity_rows=identity_rows,
            open_ids=open_by_patient.get(identity_rows[0][0], []),
        )
        if outcome.status != CUT_OK:
            continue
        assert outcome.open_admission_id is not None
        assert outcome.patient_id is not None
        assert outcome.occupation is not None
        setor, leito = outcome.occupation
        especialidade, census_name = first_cell[(key, setor, leito)]
        _pid, patient_name = identity_rows[0]
        occupations[outcome.open_admission_id] = CurrentOccupation(
            admission_id=outcome.open_admission_id,
            patient_id=outcome.patient_id,
            prontuario=key,
            patient_name=patient_name,
            setor=setor,
            leito=leito,
            especialidade=especialidade,
            census_name=census_name,
        )
    return CurrentCut(captured_at=latest, occupations=occupations)


def _parse_optional_id(raw: str | None) -> tuple[int | None, bool]:
    """Parse an optional id filter; the flag reports supplied-but-void."""
    text = (raw or "").strip()
    if not text:
        return None, False
    try:
        return int(text), False
    except ValueError:
        return None, True


def _parse_days(raw: str | None, label: str) -> tuple[timedelta | None, str | None]:
    """Parse an optional day bound; the text explains invalid input."""
    text = (raw or "").strip().replace(",", ".")
    if not text:
        return None, None
    try:
        days = float(text)
    except ValueError:
        return None, f"Limite {label} inválido: informe um número de dias."
    if days < 0:
        return None, f"Limite {label} inválido: valores não podem ser negativos."
    return timedelta(days=days), None


def parse_aggregate_filters(params: QueryDict) -> tuple[AggregateFilters, str | None]:
    """Validate raw GET params; an error message implies empty results.

    Unknown view/status/ordering fall back to defaults; supplied but
    unparseable id filters void the result; invalid day bounds produce
    an explanatory error (non-numeric, negative or inverted).
    """
    view = (params.get("view") or "").strip()
    if view not in (VIEW_PATIENTS, VIEW_ITEMS):
        view = VIEW_PATIENTS
    status = (params.get("status") or "").strip()
    if status not in (STATUS_ACTIVE, *FINAL_STATUSES, STATUS_ALL):
        status = STATUS_ACTIVE
    ordering = (params.get("ordenar") or "").strip()
    if ordering not in (ORDER_DEFAULT, ORDER_TIME_ASC, ORDER_TIME_DESC):
        ordering = ORDER_DEFAULT
    item_type_id, type_void = _parse_optional_id(params.get("tipo"))
    creator_id, creator_void = _parse_optional_id(params.get("criador"))
    updater_raw = (params.get("atualizador") or "").strip()
    updater_id: int | None = None
    updater_system = False
    updater_void = False
    if updater_raw:
        if updater_raw == SYSTEM_FILTER_VALUE:
            updater_system = True
        else:
            updater_id, updater_void = _parse_optional_id(updater_raw)
    min_open, min_error = _parse_days(params.get("min_dias"), "mínimo")
    max_open, max_error = _parse_days(params.get("max_dias"), "máximo")
    error = min_error or max_error
    if (
        error is None
        and min_open is not None
        and max_open is not None
        and min_open > max_open
    ):
        error = "Limites de tempo inválidos: o mínimo não pode ser maior que o máximo."
    return (
        AggregateFilters(
            view=view,
            status=status,
            unidade=(params.get("unidade") or "").strip(),
            leito=(params.get("leito") or "").strip(),
            especialidade=(params.get("especialidade") or "").strip(),
            item_type_id=item_type_id,
            creator_id=creator_id,
            updater_id=updater_id,
            updater_system=updater_system,
            min_open=min_open,
            max_open=max_open,
            ordering=ordering,
            void=type_void or creator_void or updater_void,
        ),
        error,
    )


def base_current_items(cut: CurrentCut) -> QuerySet[PendingItem]:
    """One selection per item before grouping, filtering or pagination.

    Shared by the aggregate list and the hospital indicators (which add
    only the active-status restriction); the future export reuses the
    same base so every surface agrees on the conservative cut.
    """
    return (
        PendingItem.objects.filter(admission_id__in=list(cut.occupations))
        .select_related("item_type", "admission", "created_by", "updated_by")
        .order_by("created_at", "pk")
    )


def apply_aggregate_filters(
    items: QuerySet[PendingItem], cut: CurrentCut, filters: AggregateFilters
) -> QuerySet[PendingItem]:
    """Restrict the base selection; time bounds apply afterwards in Python."""
    if filters.void:
        return items.none()
    if filters.status != STATUS_ALL:
        items = items.filter(status=filters.status)
    if filters.unidade or filters.leito or filters.especialidade:
        allowed = [
            aid
            for aid, occ in cut.occupations.items()
            if (not filters.unidade or occ.setor == filters.unidade)
            and (not filters.leito or occ.leito == filters.leito)
            and (
                not filters.especialidade
                or occ.especialidade == filters.especialidade
            )
        ]
        items = items.filter(admission_id__in=allowed)
    if filters.item_type_id is not None:
        items = items.filter(item_type_id=filters.item_type_id)
    if filters.creator_id is not None:
        items = items.filter(created_by_id=filters.creator_id)
    if filters.updater_system:
        items = items.filter(is_system_updated=True)
    elif filters.updater_id is not None:
        items = items.filter(updated_by_id=filters.updater_id)
    return items


def open_duration(item: PendingItem, now: datetime) -> timedelta:
    """Exact open time: until now for actives, until transition otherwise."""
    if item.status == STATUS_ACTIVE:
        return now - item.created_at
    end = item.finalized_at or item.updated_at
    return end - item.created_at


def apply_time_bounds(
    items: list[PendingItem], filters: AggregateFilters, now: datetime
) -> list[PendingItem]:
    """Keep items within the day bounds by exact comparison, unrounded."""
    if filters.min_open is None and filters.max_open is None:
        return items
    kept: list[PendingItem] = []
    for item in items:
        duration = open_duration(item, now)
        if filters.min_open is not None and duration < filters.min_open:
            continue
        if filters.max_open is not None and duration > filters.max_open:
            continue
        kept.append(item)
    return kept


def _default_item_key(
    item: PendingItem, occupations: dict[int, CurrentOccupation]
) -> tuple[str, str, str, datetime, int]:
    occ = occupations[item.admission_id]
    return (
        occ.setor,
        occ.leito,
        occ.patient_name,
        item.created_at,
        item.pk or 0,
    )


def sort_aggregate_items(
    items: list[PendingItem],
    cut: CurrentCut,
    filters: AggregateFilters,
    now: datetime,
) -> list[PendingItem]:
    """Stable ordering: unit/bed/patient/creation, or exact open time."""
    ordered = sorted(items, key=lambda item: _default_item_key(item, cut.occupations))
    if filters.ordering == ORDER_TIME_ASC:
        ordered.sort(key=lambda item: open_duration(item, now))
    elif filters.ordering == ORDER_TIME_DESC:
        ordered.sort(key=lambda item: open_duration(item, now), reverse=True)
    return ordered


def group_by_patient(
    items: list[PendingItem], cut: CurrentCut
) -> list[PatientGroup]:
    """Group filtered items per patient; every match stays in its group."""
    buckets: dict[int, list[PendingItem]] = {}
    for item in items:
        buckets.setdefault(item.admission_id, []).append(item)
    return [
        PatientGroup(
            admission_id=aid,
            occupation=cut.occupations[aid],
            items=group,
        )
        for aid, group in buckets.items()
    ]


def _group_default_key(group: PatientGroup) -> tuple[str, str, str, int]:
    occ = group.occupation
    return (occ.setor, occ.leito, occ.patient_name, group.admission_id)


def sort_patient_groups(
    groups: list[PatientGroup], filters: AggregateFilters, now: datetime
) -> list[PatientGroup]:
    """Order groups and their items; time ordering uses group extremes.

    Within a group, items follow creation order by default and duration
    order otherwise. Groups follow unit/bed/patient by default; under
    time ordering they follow the shortest (ascending) or longest
    (descending) open time in the group, with stable default ties.
    """
    for group in groups:
        group.items.sort(key=lambda item: (item.created_at, item.pk or 0))
        if filters.ordering == ORDER_TIME_ASC:
            group.items.sort(key=lambda item: open_duration(item, now))
        elif filters.ordering == ORDER_TIME_DESC:
            group.items.sort(
                key=lambda item: open_duration(item, now), reverse=True
            )
    groups.sort(key=_group_default_key)
    if filters.ordering == ORDER_TIME_ASC:
        groups.sort(
            key=lambda group: min(open_duration(item, now) for item in group.items)
        )
    elif filters.ordering == ORDER_TIME_DESC:
        groups.sort(
            key=lambda group: max(open_duration(item, now) for item in group.items),
            reverse=True,
        )
    return groups


def _local_interval(admission: Admission) -> tuple[date | None, date | None]:
    start = (
        timezone.localtime(admission.admission_date).date()
        if admission.admission_date
        else None
    )
    end = (
        timezone.localtime(admission.discharge_date).date()
        if admission.discharge_date
        else None
    )
    return start, end


def _contains(
    interval: tuple[date | None, date | None], day: date
) -> bool | None:
    """Date containment; missing lower bound stays indeterminate."""
    start, end = interval
    if start is None:
        return None
    if day < start:
        return False
    if end is None:
        return True
    return day <= end


def resolve_first_units(admission_ids: list[int]) -> dict[int, str]:
    """First registered sector per episode, without fixing movement links.

    A movement carrying the target FK counts only when its date falls
    inside the target episode's local interval; one without FK counts
    only when the target interval contains it and no other canonical
    admission of the patient contains it or is indeterminate, so
    overlaps and same-day readmissions never attribute FK-less rows.
    Pronto-socorro has no special exclusion. Three batched queries.
    """
    unique_ids = list(dict.fromkeys(admission_ids))
    if not unique_ids:
        return {}
    targets = {
        admission.pk: admission
        for admission in Admission.objects.filter(pk__in=unique_ids)
    }
    if not targets:
        return {aid: FIRST_UNIT_UNKNOWN for aid in unique_ids}
    patient_ids = list({adm.patient_id for adm in targets.values()})
    episodes: dict[int, list[tuple[int, date | None, date | None]]] = {
        pid: [] for pid in patient_ids
    }
    for pk, pid, start_dt, end_dt in Admission.objects.filter(
        patient_id__in=patient_ids
    ).values_list("pk", "patient_id", "admission_date", "discharge_date"):
        start = timezone.localtime(start_dt).date() if start_dt else None
        end = timezone.localtime(end_dt).date() if end_dt else None
        episodes[pid].append((pk, start, end))
    movements: dict[int, list[PatientMovement]] = {pid: [] for pid in patient_ids}
    for movement in PatientMovement.objects.filter(
        patient_id__in=patient_ids
    ).order_by("movement_date", "sequence", "pk"):
        movements[movement.patient_id].append(movement)
    result: dict[int, str] = {}
    for aid in unique_ids:
        target = targets.get(aid)
        if target is None:
            result[aid] = FIRST_UNIT_UNKNOWN
            continue
        interval = _local_interval(target)
        others = [
            (start, end)
            for pk, start, end in episodes.get(target.patient_id, [])
            if pk != aid
        ]
        first: str | None = None
        for movement in movements.get(target.patient_id, []):
            if movement.admission_id == aid:
                if _contains(interval, movement.movement_date) is not True:
                    continue
                first = movement.sector
                break
            if movement.admission_id is not None:
                continue
            if _contains(interval, movement.movement_date) is not True:
                continue
            if any(
                _contains(other, movement.movement_date) is not False
                for other in others
            ):
                continue
            first = movement.sector
            break
        result[aid] = first if first is not None else FIRST_UNIT_UNKNOWN
    return result


def hospital_indicators(cut: CurrentCut, now: datetime) -> HospitalIndicators:
    """Distinct patients with current actives plus mean/max item age.

    Same conservative cut as the list; filters, view and page never
    enter. Ages are exact (now minus creation) in days; an empty active
    set yields zero patients and unknown durations. One query.
    """
    if not cut.occupations:
        return HospitalIndicators(patient_count=0, mean_days=None, max_days=None)
    rows = list(
        PendingItem.objects.filter(
            admission_id__in=list(cut.occupations), status=STATUS_ACTIVE
        ).values_list("admission__patient_id", "created_at")
    )
    if not rows:
        return HospitalIndicators(patient_count=0, mean_days=None, max_days=None)
    patients = {patient_id for patient_id, _created in rows}
    ages = [(now - created).total_seconds() / 86400 for _pid, created in rows]
    return HospitalIndicators(
        patient_count=len(patients),
        mean_days=sum(ages) / len(ages),
        max_days=max(ages),
    )


def specialty_labels() -> tuple[dict[str, str], dict[str, str]]:
    """Catalog maps (code->name, name->code) for specialty display."""
    code_to_name = {
        code: name for code, name in Specialty.objects.values_list("code", "name")
    }
    name_to_code = {name: code for code, name in code_to_name.items()}
    return code_to_name, name_to_code


def resolve_specialty(
    raw: str, code_to_name: dict[str, str], name_to_code: dict[str, str]
) -> tuple[str, str]:
    """Split a census specialty cell into (sigla, nome), censo-compatible."""
    if raw in code_to_name:
        return raw, code_to_name[raw]
    if raw in name_to_code:
        return name_to_code[raw], raw
    return raw, raw


def aggregate_options(
    cut: CurrentCut, code_to_name: dict[str, str]
) -> AggregateOptions:
    """Stable dropdown values from the current cut, filter-independent."""
    setores = sorted({occ.setor for occ in cut.occupations.values()})
    leitos = sorted({occ.leito for occ in cut.occupations.values()})
    raw_specs = sorted(
        {
            occ.especialidade
            for occ in cut.occupations.values()
            if occ.especialidade
        }
    )
    especialidades = [
        {"value": raw, "label": code_to_name.get(raw, raw), "code": raw}
        for raw in raw_specs
    ]
    tipos = list(PendingItemType.objects.all())
    if cut.occupations:
        base = PendingItem.objects.filter(
            admission_id__in=list(cut.occupations)
        )
        creator_ids = base.exclude(created_by__isnull=True).values_list(
            "created_by_id", flat=True
        )
        updater_ids = base.exclude(updated_by__isnull=True).values_list(
            "updated_by_id", flat=True
        )
        criadores = list(
            User.objects.filter(pk__in=creator_ids).order_by("username")
        )
        atualizadores = list(
            User.objects.filter(pk__in=updater_ids).order_by("username")
        )
        has_system = base.filter(is_system_updated=True).exists()
    else:
        criadores = []
        atualizadores = []
        has_system = False
    return AggregateOptions(
        unidades=setores,
        leitos=leitos,
        especialidades=especialidades,
        tipos=tipos,
        criadores=criadores,
        atualizadores=atualizadores,
        has_system_updates=has_system,
    )
