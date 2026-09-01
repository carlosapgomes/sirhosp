"""Patient flow findings classifier (PFIF-S3, D5).

Bulk, non-persistent presentation service deriving the CURRENT operational
finding for census patients from data that already exists: census input,
demographics, admissions, clinical events and the closed encounter-fallback
outcome recorded by PFIF-S1/S2 stage metrics.

Design constraints:

- Closed presentation contract only: ``code``, ``label``, ``severity`` and
  ``requires_manual_review``. Labels are constants; no free JSON, no model,
  no migration, nothing persisted.
- Exactly one primary finding per patient, by deterministic priority
  (D5): a later Admission/event/capture changes the projection on the next
  evaluation (auto-resolution), with no manual cleanup row.
- Strictly separated from the technical axis: runs, batches and
  ``failure_reason`` (timeout etc.) are never read nor rewritten; a
  finding and a technical failure coexist.
- Bulk by contract: at most five fixed queries per evaluation (patients,
  admissions, event maxima, stage outcomes and movement maxima)
  regardless of cohort size — no query in loops, no N+1.
- Privacy: the module never logs and never exposes identifiers, names,
  dates of birth, professionals or clinical text; the obstetric 3A sector
  identity is a closed constant, and a sector alone never classifies.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from django.db.models import Max
from django.utils import timezone

from apps.census.models import PatientMovement
from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.extractors.patient_flow_snapshot import (
    OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION,
)
from apps.ingestion.models import IngestionRunStageMetric
from apps.patients.models import Admission, Patient

# ── Closed codes (R1) ────────────────────────────────────────────────

CODE_RECENT_ENCOUNTER_WITHOUT_ADMISSION = (
    "recent_encounter_without_admission"
)
CODE_NEWBORN_WAITING_REGISTRATION = "newborn_waiting_registration"
CODE_POSSIBLE_NEWBORN_COMPANION = "possible_newborn_companion"
CODE_RECENT_ADMISSION_AWAITING_FIRST_EVOLUTION = (
    "recent_admission_awaiting_first_evolution"
)
CODE_SUSPECTED_LEGACY_RESIDUAL = "suspected_legacy_residual"
CODE_MIRROR_STALE_ADMISSION = "mirror_stale_admission"

ALL_FINDING_CODES = frozenset(
    {
        CODE_RECENT_ENCOUNTER_WITHOUT_ADMISSION,
        CODE_NEWBORN_WAITING_REGISTRATION,
        CODE_POSSIBLE_NEWBORN_COMPANION,
        CODE_RECENT_ADMISSION_AWAITING_FIRST_EVOLUTION,
        CODE_SUSPECTED_LEGACY_RESIDUAL,
        CODE_MIRROR_STALE_ADMISSION,
    }
)

# ── Closed presentation contract (labels are constants, R7) ──────────

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"

_FINDING_SPECS: dict[str, tuple[str, str, bool]] = {
    CODE_RECENT_ENCOUNTER_WITHOUT_ADMISSION: (
        "Atendimento recente sem internação",
        SEVERITY_INFO,
        False,
    ),
    CODE_NEWBORN_WAITING_REGISTRATION: (
        "RN aguardando registro",
        SEVERITY_INFO,
        False,
    ),
    CODE_POSSIBLE_NEWBORN_COMPANION: (
        "Possível RN acompanhante",
        SEVERITY_WARNING,
        True,
    ),
    CODE_RECENT_ADMISSION_AWAITING_FIRST_EVOLUTION: (
        "Internação recente aguardando 1ª evolução",
        SEVERITY_INFO,
        False,
    ),
    CODE_SUSPECTED_LEGACY_RESIDUAL: (
        "Suspeita de paciente residual no legado",
        SEVERITY_WARNING,
        True,
    ),
    CODE_MIRROR_STALE_ADMISSION: (
        "Suspeita de admissão órfã no espelho",
        SEVERITY_WARNING,
        True,
    ),
}


@dataclass(frozen=True)
class PatientFlowFinding:
    """Closed presentation DTO (R1): exactly these four fields."""

    code: str
    label: str
    severity: str
    requires_manual_review: bool


def _finding(code: str) -> PatientFlowFinding:
    label, severity, review = _FINDING_SPECS[code]
    return PatientFlowFinding(
        code=code,
        label=label,
        severity=severity,
        requires_manual_review=review,
    )


# ── Evidence constants ───────────────────────────────────────────────

_ENCOUNTER_FALLBACK_STAGE = "encounter_fallback"
"""Stage that PFIF-S1/S2 use to record the closed operational outcome."""

_ALLOWLISTED_OUTCOMES = frozenset(
    {OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION}
)

def _fold_name(value: str) -> str:
    """Casefold + strip accents for closed sector-name comparison."""
    return (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .strip()
        .casefold()
    )


OBSTETRIC_3A_SECTOR_CODES = frozenset({"654"})
"""Source-system ward codes of the Obstetrícia 3A sector (rule 3)."""

_OBSTETRIC_3A_NAME_FOLDS = frozenset(
    {
        _fold_name("3 6 - 3A - OBSTETRÍCIA CLÍNICA - HGRS"),
    }
)


def _is_obstetric_3a(sector: str, sector_code: str) -> bool:
    if sector_code and sector_code.strip() in OBSTETRIC_3A_SECTOR_CODES:
        return True
    return bool(sector) and _fold_name(sector) in _OBSTETRIC_3A_NAME_FOLDS


# ── Newborn / recency windows ────────────────────────────────────────

_NEWBORN_MIN_DAYS = 0
_NEWBORN_MAX_DAYS = 4
_COMPANION_MIN_DAYS = 5
_COMPANION_MAX_DAYS = 28
_EVENT_WINDOW = timedelta(hours=48)
_MOVEMENT_WINDOW = timedelta(hours=48)


@dataclass(frozen=True)
class PatientFindingInput:
    """One census row to classify. No PHI beyond lookup keys."""

    prontuario: str
    patient_id: int | None = None
    sector: str = ""
    sector_code: str = ""


# ── Pure rule evaluation (D5 priority, one finding per patient) ──────


def _is_recent_movement(
    latest_movement_at: datetime | None, now: datetime
) -> bool:
    """Fail-closed movement recency: absent or future timestamps are not
    recent (invalid evidence is treated as absent)."""
    return (
        latest_movement_at is not None
        and now - _MOVEMENT_WINDOW <= latest_movement_at <= now
    )


def classify_patient_finding(
    *,
    now: datetime,
    date_of_birth: date | None = None,
    sector: str = "",
    sector_code: str = "",
    latest_admission_created_at: datetime | None = None,
    latest_outcome_at: datetime | None = None,
    has_active_admission: bool = False,
    active_admission_date: datetime | None = None,
    active_admission_last_event_at: datetime | None = None,
    latest_movement_at: datetime | None = None,
) -> PatientFlowFinding | None:
    """Return the single primary finding for one patient, or ``None``.

    Priority (D5, R2):
    1. recent-encounter outcome newer than any Admission;
    2. newborn 0–4 days without an active Admission;
    3. newborn 5–28 days without an active Admission in Obstetrícia 3A;
    4. active Admission < 48h without any event;
    5. active Admission >= 48h with no event in the previous 48h, split
       by movement recency: a sector entry within the last 48h means the
       mirror keeps a stale (orphan) admission
       (`mirror_stale_admission`); otherwise the legacy residual
       suspicion stands.

    A missing or future DOB never classifies a newborn; a missing or
    future movement timestamp is treated as absent (fail-closed); a
    sector alone never classifies; the residual suspicion never asserts
    a discharge. ``now`` must be timezone-aware.
    """
    # Rule 1: the outcome holds until a posterior Admission appears.
    if latest_outcome_at is not None and (
        latest_admission_created_at is None
        or latest_outcome_at >= latest_admission_created_at
    ):
        return _finding(CODE_RECENT_ENCOUNTER_WITHOUT_ADMISSION)

    today = timezone.localtime(now).date()
    age_days: int | None = None
    if date_of_birth is not None:
        candidate = (today - date_of_birth).days
        if candidate >= 0:  # a future DOB is invalid newborn evidence
            age_days = candidate

    # Rules 2–3 require NO active Admission (a sector alone never labels).
    if not has_active_admission and age_days is not None:
        if _NEWBORN_MIN_DAYS <= age_days <= _NEWBORN_MAX_DAYS:
            return _finding(CODE_NEWBORN_WAITING_REGISTRATION)
        if (
            _COMPANION_MIN_DAYS <= age_days <= _COMPANION_MAX_DAYS
            and _is_obstetric_3a(sector, sector_code)
        ):
            return _finding(CODE_POSSIBLE_NEWBORN_COMPANION)

    # Rules 4–5 require an active Admission with a known start.
    if has_active_admission and active_admission_date is not None:
        elapsed = now - active_admission_date
        hours = elapsed.total_seconds() / 3600.0
        if 0 <= hours < 48 and active_admission_last_event_at is None:
            return _finding(CODE_RECENT_ADMISSION_AWAITING_FIRST_EVOLUTION)
        if hours >= 48:
            window_start = now - _EVENT_WINDOW
            if (
                active_admission_last_event_at is None
                or active_admission_last_event_at < window_start
            ):
                if _is_recent_movement(latest_movement_at, now):
                    return _finding(CODE_MIRROR_STALE_ADMISSION)
                return _finding(CODE_SUSPECTED_LEGACY_RESIDUAL)

    return None


# ── Bulk evaluation (R4): fixed query budget, no N+1 ─────────────────


def build_patient_flow_findings(
    patients: Iterable[PatientFindingInput],
    *,
    now: datetime | None = None,
) -> dict[str, PatientFlowFinding]:
    """Classify a whole census cohort with a fixed number of queries.

    Returns a map keyed by ``prontuario`` (registro). Patients absent from
    the input are never classified (leaving the census resolves findings).
    Uses at most five bulk queries independent of cohort size: patient
    DOBs, cohort admissions, per-admission event maxima, the latest
    allowlisted encounter-fallback outcome per registro and the latest
    sector entry per patient (``PatientMovement.first_seen_at``).
    """
    now = now or timezone.now()

    unique: dict[str, PatientFindingInput] = {}
    for item in patients:
        pront = (item.prontuario or "").strip()
        if pront and pront not in unique:
            unique[pront] = item
    if not unique:
        return {}

    pronts = list(unique)
    patient_ids = [
        p.patient_id for p in unique.values() if p.patient_id is not None
    ]

    # Query 1: DOBs for the cohort's mirrored patients.
    dob_map: dict[int, date | None] = {}
    if patient_ids:
        dob_map = dict(
            Patient.objects.filter(pk__in=patient_ids).values_list(
                "pk", "date_of_birth"
            )
        )

    # Query 2: all cohort admissions (latest creation and latest active).
    latest_created_at: dict[int, datetime] = {}
    active_by_patient: dict[int, dict[str, Any]] = {}
    if patient_ids:
        for adm_row in (
            Admission.objects.filter(patient_id__in=patient_ids)
            .values(
                "patient_id",
                "pk",
                "admission_date",
                "discharge_date",
                "created_at",
            )
        ):
            adm_pid = adm_row["patient_id"]
            created = adm_row["created_at"]
            if (
                adm_pid not in latest_created_at
                or created > latest_created_at[adm_pid]
            ):
                latest_created_at[adm_pid] = created
            if adm_row["discharge_date"] is None:
                recency_key = (
                    adm_row["admission_date"] or created,
                    adm_row["pk"],
                )
                current = active_by_patient.get(adm_pid)
                if current is None or recency_key > current["key"]:
                    active_by_patient[adm_pid] = {
                        "key": recency_key,
                        "pk": adm_row["pk"],
                        "admission_date": adm_row["admission_date"],
                    }

    # Query 3: latest event timestamp per active admission.
    last_event_at: dict[int, datetime] = {}
    active_admission_ids = [
        rec["pk"] for rec in active_by_patient.values()
    ]
    if active_admission_ids:
        for evt_row in (
            ClinicalEvent.objects.filter(
                admission_id__in=active_admission_ids
            )
            .values("admission_id")
            .annotate(last=Max("happened_at"))
        ):
            last_event_at[evt_row["admission_id"]] = evt_row["last"]

    # Query 4: latest allowlisted encounter-fallback outcome per registro.
    outcome_at: dict[str, datetime] = {}
    for stage_row in (
        IngestionRunStageMetric.objects.filter(
            stage_name=_ENCOUNTER_FALLBACK_STAGE,
            status="succeeded",
            details_json__outcome__in=_ALLOWLISTED_OUTCOMES,
            run__parameters_json__patient_record__in=pronts,
        )
        .order_by("-started_at", "-pk")
        .values("run__parameters_json__patient_record", "started_at")
    ):
        record = stage_row["run__parameters_json__patient_record"]
        if record and record not in outcome_at:
            outcome_at[record] = stage_row["started_at"]

    # Query 5: latest sector entry per cohort patient (movement ledger).
    movement_at: dict[int, datetime] = {}
    if patient_ids:
        for mov_row in (
            PatientMovement.objects.filter(patient_id__in=patient_ids)
            .values("patient_id")
            .annotate(last=Max("first_seen_at"))
        ):
            movement_at[mov_row["patient_id"]] = mov_row["last"]

    findings: dict[str, PatientFlowFinding] = {}
    for pront, item in unique.items():
        pid = item.patient_id
        active = active_by_patient.get(pid) if pid is not None else None
        finding = classify_patient_finding(
            now=now,
            date_of_birth=dob_map.get(pid) if pid is not None else None,
            sector=item.sector,
            sector_code=item.sector_code,
            latest_admission_created_at=(
                latest_created_at.get(pid) if pid is not None else None
            ),
            latest_outcome_at=outcome_at.get(pront),
            has_active_admission=active is not None,
            active_admission_date=(
                active["admission_date"] if active else None
            ),
            active_admission_last_event_at=(
                last_event_at.get(active["pk"]) if active else None
            ),
            latest_movement_at=(
                movement_at.get(pid) if pid is not None else None
            ),
        )
        if finding is not None:
            findings[pront] = finding
    return findings
