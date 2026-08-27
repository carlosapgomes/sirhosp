"""PSW-S23: current-versus-persistent parity suite.

This module is the single parity proof that the persistent-session worker
(``process_ingestion_runs_persistent_session``) can replace the current worker
(``process_ingestion_runs``) for every supported queued intent while reusing one
authenticated session across heterogeneous jobs.

Design (see ``SLICE-PSW-S23.md``):

- **R1/R2 (intent parity matrix):** for each supported intent the SAME synthetic
  source payload is fed to BOTH worker commands through their respective source
  boundaries (current ``PlaywrightEvolutionExtractor``/subprocess vs persistent
  adapter), and only externally visible effects are compared (Patient,
  Admission, ClinicalEvent, demographics, follow-up enqueue, counters, stages,
  batch). Private call order is never compared.
- **R3 (shared failure boundaries):** the timeout / invalid-payload / retryable /
  terminal boundaries are covered ONCE through both workers (PSW-S17 owns the
  full taxonomy x mode matrix); here we add the complementary
  "no bad persistence" angle plus cross-worker equality.
- **R5 (heterogeneous multi-job sequence):** a real adapter backed by a fake
  session processes ``admissions_only -> demographics_only -> full_sync ->
  admissions_only`` through ONE handle, with no browser/context relaunch and safe
  cleanup between jobs.
- **R6 (forbidden lifecycle/artifact calls):** the persistent per-job path never
  invokes subprocess / ``sync_playwright`` / ``launch_persistent_context``.
- **R7 (empty/unknown intent):** outside replacement scope; no source action.

Normalization (R4): worker label/PID and clock/timestamp values are normalized
to presence/shape (not exact values); primary keys are compared as counts. Each
normalization is listed in the slice report.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.extractors.errors import (
    ExtractionError,
    ExtractionTimeoutError,
    InvalidJsonError,
)
from apps.ingestion.extractors.persistent_extraction_adapter import (
    PersistentExtractionAdapter,
)
from apps.ingestion.extractors.session_policy import TabCleanupOutcome
from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
    Command as PersistentWorkerCommand,
)
from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
    IngestionRunAttempt,
    IngestionRunStageMetric,
)
from apps.ingestion.services import (
    compute_content_hash,
    compute_event_identity_key,
)
from apps.patients.models import Admission, Patient

# ---------------------------------------------------------------------------
# Canonical synthetic source data factories
#
# Both workers receive the SAME normalized payloads so their persistence
# services (shared) produce identical clinical state. The patient_record is
# parameterized so each worker starts from an identical but independent DB
# state (no cross-contamination).
# ---------------------------------------------------------------------------

_DEMOGRAPHIC_FIELDS = (
    "name", "social_name", "date_of_birth", "gender", "gender_identity",
    "mother_name", "father_name", "race_color", "birthplace", "nationality",
    "marital_status", "education_level", "profession", "cns", "cpf",
    "phone_home", "phone_cellular", "phone_contact", "street", "address_number",
    "address_complement", "neighborhood", "city", "state", "postal_code",
)


def _admissions_snapshot(pr: str) -> list[dict[str, Any]]:
    """Canonical admissions snapshot for ``pr`` (two admissions)."""
    return [
        {
            "admission_key": f"ADM-DEDUP-{pr}",
            "admission_start": "2024-01-10 00:00:00",
            "admission_end": "2024-01-15 00:00:00",
            "ward": "UTI",
            "bed": "01",
        },
        {
            "admission_key": f"ADM-NEW-{pr}",
            "admission_start": "2024-02-01 00:00:00",
            "admission_end": None,
            "ward": "Enfermaria",
            "bed": "02",
        },
    ]


def _demographics(pr: str) -> dict[str, Any]:
    """Canonical demographics payload (external keys the persistence service
    reads). ``prontuario`` positively identifies ``pr`` for the persistent
    identity check."""
    return {
        "prontuario": pr,
        "nome": "PACIENTE TESTE PARITY",
        "nome_social": "",
        "sexo": "Feminino",
        "genero": "Cisgenero",
        "data_nascimento": "10/05/1980",
        "nome_mae": "MAE TESTE",
        "nome_pai": "PAI TESTE",
        "raca_cor": "Branca",
        "naturalidade": "Sao Paulo",
        "nacionalidade": "Brasileira",
        "estado_civil": "Casada",
        "profissao": "Enfermeira",
        "grau_instrucao": "Ensino Superior Completo",
        "cns": "700123456789012",
        "cpf": "12345678900",
        "ddd_fone_residencial": "11",
        "fone_residencial": "30304040",
        "logradouro": "Rua das Flores",
        "numero": "100",
        "bairro": "Centro",
        "cidade": "Sao Paulo",
        "uf": "SP",
        "cep": "01001000",
    }


def _evolutions_full(pr: str, *, revised: bool = False) -> list[dict[str, Any]]:
    """Canonical evolutions in the FULL persistence schema that
    ``ingest_evolutions`` reads. With ``revised`` two events share an identity
    key (same happened_at/author) but differ in content -> one create + one
    revision, both associated to the snapshot admission by ``admission_key``."""
    base = {
        "admission_key": f"ADM-NEW-{pr}",
        "patient_source_key": pr,
        "patient_name": "PACIENTE TESTE",
        "source_system": "tasy",
        "ward": "Enfermaria",
        "bed": "02",
        "happened_at": "2024-02-05T09:00:00",
        "signed_at": "2024-02-05T09:05:00",
        "author_name": "DRA. TESTE",
        "profession_type": "medica",
        "signature_line": "Dra. Teste CRM-SP 12345",
        "content_text": "Paciente estavel, sem intercorrencias.",
    }
    if not revised:
        return [base]
    revised_event = dict(base)
    revised_event["content_text"] = "Paciente em melhora clinica, alta prevista."
    return [base, revised_event]


def _admissions_snapshot_camel(pr: str) -> list[dict[str, Any]]:
    """camelCase snapshot the REAL adapter's ``AdmissionSnapshotParser`` reads
    from the ``admission-snapshot-data`` container (used by the real-adapter
    sequence only; the mock-adapter matrix uses snake_case directly)."""
    return [
        {
            "admissionKey": f"ADM-DEDUP-{pr}",
            "admissionStart": "2024-01-10 00:00:00",
            "admissionEnd": "2024-01-15 00:00:00",
            "ward": "UTI",
            "bed": "01",
        },
        {
            "admissionKey": f"ADM-NEW-{pr}",
            "admissionStart": "2024-02-01 00:00:00",
            "admissionEnd": None,
            "ward": "Enfermaria",
            "bed": "02",
        },
    ]


def _evolutions_5key(pr: str) -> list[dict[str, Any]]:
    """5-key evolution container payload the persistent adapter stub path
    enriches to the full schema (used by the real-adapter sequence only)."""
    return [
        {
            "admission_key": f"ADM-NEW-{pr}",
            "happened_at": "2024-02-05T09:00:00",
            "event_type": "medical_evolution",
            "content": "Paciente estavel (sequence).",
            "profession": "medica",
        }
    ]


# ---------------------------------------------------------------------------
# Run creation
# ---------------------------------------------------------------------------


def _make_run(
    intent: str,
    pr: str,
    *,
    batch: CensusExecutionBatch | None = None,
    start_date: str = "",
    end_date: str = "",
    attempt_count: int = 0,
    max_attempts: int = 1,
) -> IngestionRun:
    params: dict[str, Any] = {"patient_record": pr, "intent": intent}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return IngestionRun.objects.create(
        status="queued",
        intent=intent,
        batch=batch,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        parameters_json=params,
    )


def _drained_batch() -> CensusExecutionBatch:
    return CensusExecutionBatch.objects.create(status="running")


# ---------------------------------------------------------------------------
# Source-boundary patches (one per worker)
# ---------------------------------------------------------------------------

_CURRENT_EXTRACTOR_PATH = (
    "apps.ingestion.management.commands.process_ingestion_runs"
    ".PlaywrightEvolutionExtractor"
)
_CURRENT_DEMO_SUBPROC_PATH = (
    "apps.ingestion.extractors.subprocess_utils.run_subprocess"
)


def _current_patches(
    *,
    snapshot: list[dict] | None = None,
    evolutions: list[dict] | None = None,
    demographics: dict | None = None,
    fail_exc: Exception | None = None,
) -> list:
    """Patch the CURRENT worker's two source boundaries.

    - admissions / full_sync: ``PlaywrightEvolutionExtractor``.
    - demographics: ``run_subprocess`` writes the JSON the worker reads.

    Both are always installed; the unused one is inert for a given intent.
    """
    mock_ext = MagicMock()
    if fail_exc is not None:
        mock_ext.get_admission_snapshot.side_effect = fail_exc
    else:
        mock_ext.get_admission_snapshot.return_value = snapshot or []
    mock_ext.extract_evolutions.return_value = evolutions or []

    demo_payload = demographics

    def _subproc_side_effect(cmd, **kwargs):  # noqa: ANN001
        data = demo_payload or {}
        for i, arg in enumerate(cmd):
            if arg == "--json-output" and i + 1 < len(cmd):
                out = Path(cmd[i + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )
                break
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    return [
        patch(_CURRENT_EXTRACTOR_PATH, return_value=mock_ext),
        patch(_CURRENT_DEMO_SUBPROC_PATH, side_effect=_subproc_side_effect),
    ]


def _persistent_patches(
    *,
    snapshot: list[dict] | None = None,
    evolutions: list[dict] | None = None,
    demographics: dict | None = None,
    fail_exc: Exception | None = None,
) -> list:
    """Patch the PERSISTENT worker's single source boundary (``_create_adapter``)."""
    mock_adapter = MagicMock()
    if fail_exc is not None:
        mock_adapter.get_admission_snapshot.side_effect = fail_exc
    else:
        mock_adapter.get_admission_snapshot.return_value = snapshot or []
    mock_adapter.get_demographics.return_value = (
        demographics if demographics is not None else {}
    )
    mock_adapter.extract_evolutions.return_value = evolutions or []
    mock_adapter.ensure_session_ready.return_value = True
    mock_adapter.cleanup_after_failure = MagicMock()
    mock_adapter.controller = MagicMock()
    mock_adapter.controller.restart_required.return_value = False
    return [
        patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        )
    ]


# ---------------------------------------------------------------------------
# Follow-up isolation
#
# admissions_only auto-enqueues a demographics_only + full_sync follow-up. To
# keep each worker run isolated (one run processed, no queue pollution) the
# enqueuers are patched to record calls without creating real runs. Both
# workers call the SAME shared services, so follow-up parity is proven by
# identical call patterns.
# ---------------------------------------------------------------------------


class _FollowupRecorder:
    def __init__(self) -> None:
        self.demo_calls: list[str] = []
        self.fullsync_calls: list[str] = []

    def demo(self, *args, **kwargs):
        self.demo_calls.append(kwargs.get("patient_record", ""))
        return MagicMock()

    def fullsync(self, *args, **kwargs):
        self.fullsync_calls.append("called")
        return MagicMock()

    def as_dict(self) -> dict[str, Any]:
        return {
            "demo_call_count": len(self.demo_calls),
            "fullsync_call_count": len(self.fullsync_calls),
        }


@contextmanager
def _isolate_current_followups(rec: _FollowupRecorder):
    with patch(
        "apps.ingestion.management.commands.process_ingestion_runs"
        ".queue_demographics_only_run",
        side_effect=rec.demo,
    ), patch(
        "apps.ingestion.services.enqueue_most_recent_admission_full_sync",
        side_effect=rec.fullsync,
    ):
        yield


@contextmanager
def _isolate_persistent_followups(rec: _FollowupRecorder):
    with patch(
        "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"  # noqa: E501
        ".queue_demographics_only_run",
        side_effect=rec.demo,
    ), patch(
        "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"  # noqa: E501
        ".enqueue_most_recent_admission_full_sync",
        side_effect=rec.fullsync,
    ):
        yield


# ---------------------------------------------------------------------------
# Observable-effect snapshot (R2: only externally visible effects)
# ---------------------------------------------------------------------------


def _stage_statuses(run: IngestionRun) -> dict[str, str]:
    return {
        s.stage_name: s.status
        for s in IngestionRunStageMetric.objects.filter(run=run)
    }


def _clinical_counts() -> tuple[int, int, int]:
    """Global Patient/Admission/ClinicalEvent row counts for delta checks."""
    return (
        Patient.objects.count(),
        Admission.objects.count(),
        ClinicalEvent.objects.count(),
    )


# ---------------------------------------------------------------------------
# C1-R1: deterministic persisted clinical snapshot (narrow normalization)
#
# The ONLY values normalized are the synthetic patient-record token (which
# differs per worker) and the Patient PK embedded in event_identity_key.
# Ward, bed, dates, content, content_hash, author, profession, and signature
# are NEVER normalized, so a differing value can never hide behind equal
# counts or equal normalized identifiers.
# ---------------------------------------------------------------------------

_PR_MARKER = "<PR>"
_IDENTITY_PATIENT_ID = 0


def _norm_token(value: Any, pr: str) -> Any:
    if value is None:
        return None
    return value.replace(pr, _PR_MARKER)


def _norm_identity_key(event: ClinicalEvent) -> str:
    """Recompute event_identity_key with a constant patient PK.

    The real identity key embeds the Patient DB PK (stable per row but
    different across the two workers' independent rows). Recomputing it with
    a constant PK lets two logically-identical events compare equal while
    keeping happened_at/author/source_system observable. Mirrors
    ``compute_event_identity_key``'s formula exactly.
    """
    raw = (
        f"{event.patient.source_system}"
        f"|{_IDENTITY_PATIENT_ID}"
        f"|{event.happened_at.isoformat()}"
        f"|{event.author_name}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clinical_snapshot(pr: str) -> dict[str, Any]:
    """Deterministic, normalized field snapshot of persisted clinical state."""
    patient = Patient.objects.filter(
        source_system="tasy", patient_source_key=pr
    ).first()
    if patient is None:
        return {"patient": None, "admissions": [], "events": []}
    patient_snap = {
        "source_system": patient.source_system,
        "patient_source_key": _norm_token(patient.patient_source_key, pr),
        "name": patient.name,
        "demographics": {
            f: (getattr(patient, f, None) or "") for f in _DEMOGRAPHIC_FIELDS
        },
    }
    admissions = [
        {
            "source_system": adm.source_system,
            "source_admission_key": _norm_token(adm.source_admission_key, pr),
            "source_patient_reference": _norm_token(
                adm.source_patient_reference or "", pr
            ),
            "admission_date": (
                adm.admission_date.isoformat() if adm.admission_date else None
            ),
            "discharge_date": (
                adm.discharge_date.isoformat() if adm.discharge_date else None
            ),
            "ward": adm.ward,
            "bed": adm.bed,
        }
        for adm in Admission.objects.filter(patient=patient)
    ]
    admissions.sort(
        key=lambda a: (a["source_admission_key"], a["admission_date"] or "")
    )
    events = [
        {
            "patient_source_key": _norm_token(
                ev.patient.patient_source_key, pr
            ),
            "admission_source_key": _norm_token(
                ev.admission.source_admission_key, pr
            ),
            "event_identity_key": _norm_identity_key(ev),
            "content_hash": ev.content_hash,
            "happened_at": (
                ev.happened_at.isoformat() if ev.happened_at else None
            ),
            "signed_at": ev.signed_at.isoformat() if ev.signed_at else None,
            "author_name": ev.author_name,
            "profession_type": ev.profession_type,
            "content_text": ev.content_text,
            "signature_line": ev.signature_line,
        }
        for ev in ClinicalEvent.objects.filter(
            admission__patient=patient
        ).select_related("admission", "patient")
    ]
    events.sort(key=lambda e: (e["event_identity_key"], e["content_hash"]))
    return {
        "patient": patient_snap,
        "admissions": admissions,
        "events": events,
    }


def _observable(run: IngestionRun, pr: str) -> dict[str, Any]:
    run.refresh_from_db()
    patient = Patient.objects.filter(
        source_system="tasy", patient_source_key=pr
    ).first()
    admission_keys = sorted(
        Admission.objects.filter(patient=patient).values_list(
            "source_admission_key", flat=True
        )
    ) if patient else []
    event_count = (
        ClinicalEvent.objects.filter(admission__patient=patient).count()
        if patient
        else 0
    )
    batch = run.batch
    return {
        "status": run.status,
        "failure_reason": run.failure_reason,
        "timed_out": run.timed_out,
        "attempt_count": run.attempt_count,
        "admissions_seen": run.admissions_seen,
        "admissions_created": run.admissions_created,
        "admissions_updated": run.admissions_updated,
        "events_processed": run.events_processed,
        "events_created": run.events_created,
        "events_skipped": run.events_skipped,
        "events_revised": run.events_revised,
        "gaps_count": len(run.gaps_json or []),
        "patient_exists": patient is not None,
        "admission_count": len(admission_keys),
        "event_count": event_count,
        "stage_statuses": _stage_statuses(run),
        "has_processing_started": run.processing_started_at is not None,
        "has_finished": run.finished_at is not None,
        "has_heartbeat": run.worker_heartbeat_at is not None,
        "batch_status": batch.status if batch else None,
        "batch_closed": (batch.finished_at is not None) if batch else None,
        "clinical": _clinical_snapshot(pr),
    }


def _demographic_snapshot(pr: str) -> dict[str, Any]:
    patient = Patient.objects.filter(
        source_system="tasy", patient_source_key=pr
    ).first()
    if patient is None:
        return {"present": False}
    return {
        "present": True,
        "fields": {
            f: getattr(patient, f, None) or "" for f in _DEMOGRAPHIC_FIELDS
        },
    }


# ---------------------------------------------------------------------------
# Scenario preparation (pre-seed identical DB state per worker)
# ---------------------------------------------------------------------------


def _preseed(intent: str, pr: str) -> None:
    """Pre-seed identical starting state for ``pr`` so both workers start equal.

    - admissions_only: an existing admission (different ward) to exercise
      key-based dedup/reconciliation.
    - demographics_only: a minimal existing patient to exercise the update path.
    - full_sync: fresh patient (admissions created during the run).
    - full_admission_sync: fresh patient (admissions + events during the run).
    """
    if intent == "admissions_only":
        patient = Patient.objects.create(
            source_system="tasy", patient_source_key=pr, name="OLD PATIENT"
        )
        Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key=f"ADM-DEDUP-{pr}",
            admission_date=timezone.make_aware(
                datetime(2024, 1, 10, 0, 0, 0)
            ),
            discharge_date=timezone.make_aware(
                datetime(2024, 1, 15, 0, 0, 0)
            ),
            ward="WARD-OLD",
            bed="BED-OLD",
        )
    elif intent == "demographics_only":
        Patient.objects.create(
            source_system="tasy", patient_source_key=pr, name="OLD PATIENT"
        )


def _source_for(intent: str, pr: str) -> dict[str, Any]:
    """Build the canonical source payload for ``intent``/``pr``."""
    if intent == "demographics_only":
        return {"demographics": _demographics(pr)}
    if intent in ("full_sync",):
        return {"snapshot": _admissions_snapshot(pr), "evolutions": []}
    if intent == "full_admission_sync":
        return {
            "snapshot": _admissions_snapshot(pr),
            "evolutions": _evolutions_full(pr, revised=True),
        }
    # admissions_only
    return {"snapshot": _admissions_snapshot(pr)}


def _run_params_for(intent: str) -> dict[str, Any]:
    if intent in ("full_sync", "full_admission_sync"):
        return {"start_date": "2024-01-01", "end_date": "2024-12-31"}
    return {}


def _needs_batch(intent: str) -> bool:
    """full_sync/full_admission_sync rows compare batch closure, so they carry a
    drained batch. admissions_only/demographics_only use no batch (their
    follow-ups are detached and not compared here)."""
    return intent in ("full_sync", "full_admission_sync")


# ===========================================================================
# R1/R2: intent pairwise parity matrix
# ===========================================================================


@pytest.mark.django_db
class TestComparatorSensitivity:
    """C1-R1: equal row counts must NOT hide differing persisted values.

    Two states with identical counts but a differing Admission value (ward)
    and a differing ClinicalEvent value (content) must produce non-equal
    observable snapshots. Against the count-only snapshot this fails because
    the counts match -- the meaningful RED for C1.
    """

    def _seed_state(self, pr: str, ward: str, content: str) -> IngestionRun:
        run = IngestionRun.objects.create(
            status="succeeded",
            intent="full_admission_sync",
            attempt_count=1,
            max_attempts=1,
            admissions_seen=1,
            admissions_created=1,
            events_processed=1,
            events_created=1,
            parameters_json={
                "patient_record": pr,
                "intent": "full_admission_sync",
            },
        )
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key=pr,
            name="PACIENTE SENS",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key=f"ADM-NEW-{pr}",
            admission_date=timezone.make_aware(datetime(2024, 2, 1, 0, 0, 0)),
            ward=ward,
            bed="01",
        )
        happened = timezone.make_aware(datetime(2024, 2, 5, 9, 0, 0))
        ClinicalEvent.objects.create(
            admission=admission,
            patient=patient,
            ingestion_run=run,
            event_identity_key=compute_event_identity_key(
                {
                    "source_system": "tasy",
                    "happened_at": "2024-02-05T09:00:00",
                    "author_name": "DRA. TESTE",
                },
                patient_id=patient.pk,
            ),
            content_hash=compute_content_hash(content),
            happened_at=happened,
            signed_at=happened,
            author_name="DRA. TESTE",
            profession_type="medica",
            content_text=content,
            signature_line="Dra. Teste CRM-SP 12345",
        )
        return run

    def test_equal_counts_with_differing_values_are_not_equal(self) -> None:
        run_a = self._seed_state("SENS-A", "WARD-A", "CONTENT-A")
        run_b = self._seed_state("SENS-B", "WARD-B", "CONTENT-B")
        snap_a = _observable(run_a, "SENS-A")
        snap_b = _observable(run_b, "SENS-B")
        # Equal counts must NOT hide the differing ward + content values.
        assert snap_a != snap_b, (snap_a, snap_b)


@pytest.mark.django_db
class TestIntentParityMatrix:
    """Each supported intent compares equal observable effects across workers.

    Rows (Closed Pairwise Parity Matrix):
    - admissions_only success + dedup -> counters, patient/admission, follow-ups
    - demographics_only success + update -> fields, metrics, follow-ups
    - full_sync success + no evolutions -> gaps, events, batch/stages
    - full_admission_sync success -> admission association and revisions
    """

    INTENTS = [
        "admissions_only",
        "demographics_only",
        "full_sync",
        "full_admission_sync",
    ]

    @pytest.mark.parametrize("intent", INTENTS)
    def test_observable_effects_match(self, intent: str) -> None:
        pr_cur = f"CUR-{intent}"
        pr_per = f"PER-{intent}"

        # --- Current worker ---
        _preseed(intent, pr_cur)
        rec_cur = _FollowupRecorder()
        run_cur = _make_run(
            intent, pr_cur,
            batch=_drained_batch() if _needs_batch(intent) else None,
            **_run_params_for(intent),
        )
        source_cur = _source_for(intent, pr_cur)
        with ExitStack() as stack:
            for p in _current_patches(**source_cur):
                stack.enter_context(p)
            with _isolate_current_followups(rec_cur):
                call_command("process_ingestion_runs")

        # --- Persistent worker ---
        _preseed(intent, pr_per)
        rec_per = _FollowupRecorder()
        run_per = _make_run(
            intent, pr_per,
            batch=_drained_batch() if _needs_batch(intent) else None,
            **_run_params_for(intent),
        )
        source_per = _source_for(intent, pr_per)
        with ExitStack() as stack:
            for p in _persistent_patches(**source_per):
                stack.enter_context(p)
            with _isolate_persistent_followups(rec_per):
                call_command("process_ingestion_runs_persistent_session")

        # --- Parity: observable run/persistence effects ---
        obs_cur = _observable(run_cur, pr_cur)
        obs_per = _observable(run_per, pr_per)
        assert obs_cur == obs_per, (
            f"Intent {intent} observable mismatch:\n"
            f"current={obs_cur}\npersistent={obs_per}"
        )

        # --- Parity: demographics fields (demographics_only row) ---
        if intent == "demographics_only":
            assert _demographic_snapshot(pr_cur) == _demographic_snapshot(pr_per)
            # The shared metrics key is recorded identically.
            run_cur.refresh_from_db()
            run_per.refresh_from_db()
            assert (
                run_cur.parameters_json.get("demographics_fields_extracted")
                == run_per.parameters_json.get("demographics_fields_extracted")
            )

        # --- Parity: follow-up enqueue pattern ---
        assert rec_cur.as_dict() == rec_per.as_dict(), (
            f"Intent {intent} follow-up mismatch: "
            f"current={rec_cur.as_dict()} persistent={rec_per.as_dict()}"
        )

        # --- Independent expected-value spot checks (not worker equality) ---
        assert obs_cur["status"] == "succeeded"
        assert obs_cur["patient_exists"] is True
        if intent == "admissions_only":
            # Dedup exercised: one new admission created, one existing updated.
            assert obs_cur["admissions_seen"] == 2
            assert obs_cur["admissions_created"] == 1
            assert obs_cur["admissions_updated"] == 1
            assert obs_cur["event_count"] == 0
            # Follow-ups: one demographics_only + one full_sync per worker.
            assert rec_cur.demo_calls == [pr_cur]
            assert rec_per.demo_calls == [pr_per]
            assert rec_cur.fullsync_calls == ["called"]
            assert rec_per.fullsync_calls == ["called"]
        elif intent == "demographics_only":
            assert obs_cur["event_count"] == 0
            # No follow-ups enqueued by demographics_only.
            assert rec_cur.as_dict() == {"demo_call_count": 0, "fullsync_call_count": 0}
        elif intent == "full_sync":
            # No evolutions extracted -> zero events, gaps planned, batch closed.
            assert obs_cur["events_processed"] == 0
            assert obs_cur["event_count"] == 0
            assert obs_cur["gaps_count"] >= 1
            assert obs_cur["batch_status"] == "succeeded"
            assert obs_cur["batch_closed"] is True
        elif intent == "full_admission_sync":
            # Admission association + revision: one create + one revise. A
            # revision creates a new ClinicalEvent row, so 2 rows persist.
            assert obs_cur["events_processed"] == 2
            assert obs_cur["events_created"] == 1
            assert obs_cur["events_revised"] == 1
            assert obs_cur["event_count"] == 2
            assert obs_cur["batch_status"] == "succeeded"

    def test_full_admission_sync_event_associated_to_admission(self) -> None:
        """full_admission_sync row: the persisted event is associated to the
        snapshot admission for BOTH workers (independent check)."""
        for _worker, pr, patches_fn, runner in [
            ("current", "ASSOC-CUR", _current_patches, "current"),
            ("persistent", "ASSOC-PER", _persistent_patches, "persistent"),
        ]:
            run = _make_run(
                "full_admission_sync", pr,
                start_date="2024-01-01", end_date="2024-12-31",
            )
            source = _source_for("full_admission_sync", pr)
            with ExitStack() as stack:
                for p in patches_fn(**source):
                    stack.enter_context(p)
                if runner == "current":
                    call_command("process_ingestion_runs")
                else:
                    call_command("process_ingestion_runs_persistent_session")
            run.refresh_from_db()
            assert run.status == "succeeded"
            patient = Patient.objects.get(
                source_system="tasy", patient_source_key=pr
            )
            events = list(
                ClinicalEvent.objects.filter(admission__patient=patient)
            )
            # One create + one revision -> two rows, all associated to the
            # snapshot admission.
            assert len(events) == 2
            assert all(
                e.admission.source_admission_key == f"ADM-NEW-{pr}"
                for e in events
            )


# ===========================================================================
# R3: shared failure boundary parity (covered once; PSW-S17 owns taxonomy)
# ===========================================================================

# (boundary_id, exc_factory, expected_reason, expected_timed_out, terminal)
_FAILURE_BOUNDARIES = [
    pytest.param(
        "timeout",
        lambda: ExtractionTimeoutError("source action timed out"),
        "timeout", True, False,
        id="timeout-retryable",
    ),
    pytest.param(
        "invalid_payload",
        lambda: InvalidJsonError("bad json"),
        "invalid_payload", False, False,
        id="invalid-payload-retryable",
    ),
    pytest.param(
        "retryable_failure",
        lambda: ExtractionError("source unavailable"),
        "source_unavailable", False, False,
        id="retryable-source-unavailable",
    ),
    pytest.param(
        "attempts_exhausted",
        lambda: ExtractionError("source unavailable"),
        "source_unavailable", False, True,
        id="attempts-exhausted-terminal",
    ),
]


@pytest.mark.django_db
class TestSharedFailureBoundaryParity:
    """The shared failure boundary compares equal effects across workers,
    covered ONCE (not per intent). Complements PSW-S17 with the
    "no bad persistence" angle."""

    def _queue(self, boundary_id: str, label: str) -> IngestionRun:
        batch = _drained_batch()
        pr = f"F-{boundary_id}-{label}"
        params = {"patient_record": pr, "intent": "admissions_only"}
        if boundary_id == "attempts_exhausted":
            # Terminal: two prior failed attempts -> next attempt is the last.
            run = IngestionRun.objects.create(
                status="queued", intent="admissions_only", batch=batch,
                attempt_count=2, max_attempts=3, parameters_json=params,
            )
            for i in (1, 2):
                IngestionRunAttempt.objects.create(
                    run=run, attempt_number=i, status="failed",
                    failure_reason="source_unavailable",
                    finished_at=timezone.now(),
                )
            return run
        return IngestionRun.objects.create(
            status="queued", intent="admissions_only", batch=batch,
            attempt_count=0, max_attempts=3, parameters_json=params,
        )

    @pytest.mark.parametrize(
        "boundary_id, exc_factory, expected_reason, expected_timed_out, terminal",
        _FAILURE_BOUNDARIES,
    )
    def test_boundary_effects_match_and_no_bad_persistence(
        self, boundary_id, exc_factory, expected_reason, expected_timed_out,
        terminal,
    ) -> None:
        # Current worker
        run_cur = self._queue(boundary_id, "CUR")
        before_cur = _clinical_counts()
        with ExitStack() as stack:
            for p in _current_patches(fail_exc=exc_factory()):
                stack.enter_context(p)
            call_command("process_ingestion_runs")
        run_cur.refresh_from_db()
        # C1-R2: zero clinical persistence delta on failure (exact counts).
        assert _clinical_counts() == before_cur, boundary_id

        # Persistent worker
        run_per = self._queue(boundary_id, "PER")
        before_per = _clinical_counts()
        with ExitStack() as stack:
            for p in _persistent_patches(fail_exc=exc_factory()):
                stack.enter_context(p)
            call_command("process_ingestion_runs_persistent_session")
        run_per.refresh_from_db()
        # C1-R2: zero clinical persistence delta on failure (exact counts).
        assert _clinical_counts() == before_per, boundary_id

        # --- Classification parity ---
        for run in (run_cur, run_per):
            assert run.failure_reason == expected_reason, boundary_id
            assert run.timed_out is expected_timed_out, boundary_id

        # --- Mode-specific lifecycle parity ---
        if terminal:
            for run in (run_cur, run_per):
                assert run.batch is not None, boundary_id
                assert run.status == "failed", boundary_id
                assert run.finished_at is not None
                assert run.next_retry_at is None
                assert FinalRunFailure.objects.filter(run=run).count() == 1
                run.batch.refresh_from_db()
                assert run.batch.status == "failed"
                assert run.batch.finished_at is not None
        else:
            for run in (run_cur, run_per):
                assert run.batch is not None, boundary_id
                assert run.status == "queued", boundary_id
                assert run.next_retry_at is not None
                assert run.finished_at is None
                assert FinalRunFailure.objects.filter(run=run).count() == 0
                run.batch.refresh_from_db()
                assert run.batch.status == "running"

        # --- No bad persistence: proven above by the exact model-count
        # delta being zero for each failure execution (current and
        # persistent). The weaker key-shape check is removed.

        # --- Cross-worker observable snapshot equality including attempt
        # cardinality/state (C1-R2). ---
        def _snap(run: IngestionRun) -> dict[str, Any]:
            assert run.batch is not None, boundary_id
            attempts = list(IngestionRunAttempt.objects.filter(run=run))
            latest = (
                max(attempts, key=lambda a: a.attempt_number)
                if attempts else None
            )
            return {
                "status": run.status,
                "failure_reason": run.failure_reason,
                "timed_out": run.timed_out,
                "attempt_count": run.attempt_count,
                "attempt_row_count": len(attempts),
                "latest_attempt_number": (
                    latest.attempt_number if latest else None
                ),
                "latest_attempt_status": latest.status if latest else None,
                "latest_attempt_failure_reason": (
                    latest.failure_reason if latest else None
                ),
                "latest_attempt_timed_out": (
                    latest.timed_out if latest else None
                ),
                "next_retry_at_present": run.next_retry_at is not None,
                "stage_statuses": _stage_statuses(run),
                "batch_status": run.batch.status,
            }

        assert _snap(run_cur) == _snap(run_per), boundary_id


# ===========================================================================
# RPAP-S2: empty batch-bound admissions capture fails closed in BOTH workers
# ===========================================================================


@pytest.mark.django_db
class TestEmptyBatchBoundAdmissionsParity:
    """RPAP-S2: an empty normalized admissions snapshot is INVALID when the
    run is linked to a census/recovery batch, and remains a VALID explicit
    no-admissions outcome for standalone runs.

    The batch-bound capture must fail through the existing failure/retry
    machinery BEFORE any persistence, success bookkeeping, or follow-up
    enqueue, with the shared ``invalid_payload`` taxonomy and observably
    equivalent effects in the current and persistent workers.
    """

    max_attempts = 3

    def _admissions_run(self, pr: str) -> IngestionRun:
        return _make_run(
            "admissions_only",
            pr,
            batch=_drained_batch(),
            max_attempts=self.max_attempts,
        )

    def _full_sync_run(self, pr: str) -> IngestionRun:
        return _make_run(
            "full_sync",
            pr,
            batch=_drained_batch(),
            start_date="2024-01-01",
            end_date="2024-12-31",
            max_attempts=self.max_attempts,
        )

    def _failure_snapshot(self, run: IngestionRun, pr: str) -> dict[str, Any]:
        run.refresh_from_db()
        assert run.batch is not None, "failure scenario requires a batch"
        attempts = list(IngestionRunAttempt.objects.filter(run=run))
        latest = max(attempts, key=lambda a: a.attempt_number)
        return {
            "status": run.status,
            "failure_reason": run.failure_reason,
            "timed_out": run.timed_out,
            "error_message": run.error_message,
            "attempt_count": run.attempt_count,
            "admissions_seen": run.admissions_seen,
            "admissions_created": run.admissions_created,
            "admissions_updated": run.admissions_updated,
            "events_created": run.events_created,
            "next_retry_at_present": run.next_retry_at is not None,
            "finished": run.finished_at is not None,
            "attempt_row_count": len(attempts),
            "attempt_status": latest.status,
            "attempt_failure_reason": latest.failure_reason,
            "attempt_timed_out": latest.timed_out,
            "attempt_error_message": latest.error_message,
            "stage_statuses": _stage_statuses(run),
            "batch_status": run.batch.status,
            "patient_exists": Patient.objects.filter(
                source_system="tasy", patient_source_key=pr
            ).exists(),
            "admission_count": Admission.objects.filter(
                patient__patient_source_key=pr
            ).count(),
        }

    def test_admissions_only_empty_batch_bound_fails_in_both_workers(
        self,
    ) -> None:
        """Empty admissions_only capture bound to a batch fails before
        persisting anything, with identical observable effects in both
        workers (RPAP-S2 R1-R6)."""
        # --- Current worker ---
        run_cur = self._admissions_run("EBC-CUR")
        before_cur = _clinical_counts()
        rec_cur = _FollowupRecorder()
        with ExitStack() as stack:
            for p in _current_patches(snapshot=[]):
                stack.enter_context(p)
            with _isolate_current_followups(rec_cur):
                call_command("process_ingestion_runs")
        snap_cur = self._failure_snapshot(run_cur, "EBC-CUR")
        assert _clinical_counts() == before_cur

        # --- Persistent worker ---
        run_per = self._admissions_run("EBC-PER")
        before_per = _clinical_counts()
        rec_per = _FollowupRecorder()
        adapter_per = MagicMock()
        adapter_per.get_admission_snapshot.return_value = []
        adapter_per.get_demographics.return_value = {}
        adapter_per.extract_evolutions.return_value = []
        adapter_per.ensure_session_ready.return_value = True
        adapter_per.controller.restart_required.return_value = False
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    PersistentWorkerCommand,
                    "_create_adapter",
                    return_value=adapter_per,
                )
            )
            with _isolate_persistent_followups(rec_per):
                call_command("process_ingestion_runs_persistent_session")
        snap_per = self._failure_snapshot(run_per, "EBC-PER")
        assert _clinical_counts() == before_per

        # --- Fail-before-persist with the shared taxonomy ---
        for snap in (snap_cur, snap_per):
            # Retryable failure, NOT a success with admissions_seen=0.
            assert snap["status"] == "queued"
            assert snap["failure_reason"] == "invalid_payload"
            assert snap["timed_out"] is False
            assert snap["next_retry_at_present"] is True
            assert snap["finished"] is False
            # No positive counter and no persisted clinical row.
            assert snap["admissions_seen"] == 0
            assert snap["admissions_created"] == 0
            assert snap["admissions_updated"] == 0
            assert snap["events_created"] == 0
            assert snap["patient_exists"] is False
            assert snap["admission_count"] == 0
            # Existing failure machinery: attempt failed, admissions stage
            # failed (never succeeded), batch stays open.
            assert snap["attempt_status"] == "failed"
            assert snap["attempt_failure_reason"] == "invalid_payload"
            assert snap["attempt_timed_out"] is False
            assert snap["stage_statuses"] == {"admissions_capture": "failed"}
            assert snap["batch_status"] == "running"

        # Cross-worker observable parity, including sanitized error text.
        assert snap_cur == snap_per

        # Sanitized persisted text: no patient-record token anywhere.
        for run in (run_cur, run_per):
            run.refresh_from_db()
            assert run.error_message
            assert "EBC-" not in (run.error_message or "")

        # Zero follow-ups (no demographics, no full-sync) in both workers.
        assert rec_cur.as_dict() == {
            "demo_call_count": 0,
            "fullsync_call_count": 0,
        }
        assert rec_per.as_dict() == {
            "demo_call_count": 0,
            "fullsync_call_count": 0,
        }

        # Persistent worker ran the existing recoverable-error cleanup path.
        assert adapter_per.cleanup_after_failure.called

    def test_full_sync_empty_batch_bound_fails_in_both_workers(self) -> None:
        """The mandatory admissions capture that precedes full-sync also fails
        closed for an empty batch-bound snapshot in both workers: no gap
        planning, no evolution extraction, no persistence."""
        # --- Current worker ---
        run_cur = self._full_sync_run("EFS-CUR")
        before_cur = _clinical_counts()
        with ExitStack() as stack:
            for p in _current_patches(snapshot=[], evolutions=[]):
                stack.enter_context(p)
            call_command("process_ingestion_runs")
        snap_cur = self._failure_snapshot(run_cur, "EFS-CUR")
        assert _clinical_counts() == before_cur

        # --- Persistent worker ---
        run_per = self._full_sync_run("EFS-PER")
        before_per = _clinical_counts()
        adapter_per = MagicMock()
        adapter_per.get_admission_snapshot.return_value = []
        adapter_per.get_demographics.return_value = {}
        adapter_per.extract_evolutions.return_value = []
        adapter_per.ensure_session_ready.return_value = True
        adapter_per.controller.restart_required.return_value = False
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    PersistentWorkerCommand,
                    "_create_adapter",
                    return_value=adapter_per,
                )
            )
            call_command("process_ingestion_runs_persistent_session")
        snap_per = self._failure_snapshot(run_per, "EFS-PER")
        assert _clinical_counts() == before_per

        for snap in (snap_cur, snap_per):
            assert snap["status"] == "queued"
            assert snap["failure_reason"] == "invalid_payload"
            assert snap["timed_out"] is False
            assert snap["next_retry_at_present"] is True
            assert snap["patient_exists"] is False
            assert snap["admission_count"] == 0
            # Capture failed BEFORE gap planning: no other stage ran.
            assert snap["stage_statuses"] == {"admissions_capture": "failed"}
            assert snap["attempt_status"] == "failed"
            assert snap["batch_status"] == "running"

        assert snap_cur == snap_per
        assert adapter_per.cleanup_after_failure.called

    def test_standalone_empty_snapshot_keeps_no_admissions_outcome(
        self,
    ) -> None:
        """RPAP-S2 R4: a standalone (batch-less) empty capture keeps the old
        explicit contract in both workers — success with seen=0, succeeded
        stage/attempt, demographics follow-up, and NO evolution candidate."""
        # --- Current worker ---
        run_cur = _make_run("admissions_only", "SBC-CUR")
        rec_cur = _FollowupRecorder()
        with ExitStack() as stack:
            for p in _current_patches(snapshot=[]):
                stack.enter_context(p)
            # Only the demographics follow-up is isolated; the real
            # full-sync enqueuer runs so "no evolution candidate" is proven
            # by actual queue state (it returns None without admissions).
            with patch(
                "apps.ingestion.management.commands.process_ingestion_runs"
                ".queue_demographics_only_run",
                side_effect=rec_cur.demo,
            ):
                call_command("process_ingestion_runs")
        obs_cur = _observable(run_cur, "SBC-CUR")

        # --- Persistent worker ---
        run_per = _make_run("admissions_only", "SBC-PER")
        rec_per = _FollowupRecorder()
        with ExitStack() as stack:
            for p in _persistent_patches(snapshot=[]):
                stack.enter_context(p)
            with patch(
                "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"  # noqa: E501
                ".queue_demographics_only_run",
                side_effect=rec_per.demo,
            ):
                call_command("process_ingestion_runs_persistent_session")
        obs_per = _observable(run_per, "SBC-PER")

        assert obs_cur == obs_per
        for obs in (obs_cur, obs_per):
            assert obs["status"] == "succeeded"
            assert obs["failure_reason"] == ""
            assert obs["timed_out"] is False
            assert obs["admissions_seen"] == 0
            assert obs["admission_count"] == 0
            assert obs["event_count"] == 0
            assert obs["stage_statuses"] == {
                "admissions_capture": "succeeded"
            }
        # Explicit standalone feedback retained: demographics follow-up is
        # still enqueued, but no full-sync evolution candidate is produced
        # (real enqueuer found no admission for the captured patient).
        assert rec_cur.demo_calls == ["SBC-CUR"]
        assert rec_per.demo_calls == ["SBC-PER"]
        for pr in ("SBC-CUR", "SBC-PER"):
            assert not IngestionRun.objects.filter(
                intent="full_sync",
                parameters_json__patient_record=pr,
            ).exists()

    def test_nonempty_batch_bound_still_persists_and_enqueues_full_sync(
        self,
    ) -> None:
        """RPAP-S2 guard: a valid non-empty batch-bound capture keeps the old
        success semantics — persistence, succeeded stage/attempt, full-sync
        follow-up, and batch closure in both workers."""
        # --- Current worker ---
        run_cur = self._admissions_run("NBC-CUR")
        rec_cur = _FollowupRecorder()
        with ExitStack() as stack:
            for p in _current_patches(snapshot=_admissions_snapshot("NBC-CUR")):
                stack.enter_context(p)
            with _isolate_current_followups(rec_cur):
                call_command("process_ingestion_runs")
        obs_cur = _observable(run_cur, "NBC-CUR")

        # --- Persistent worker ---
        run_per = self._admissions_run("NBC-PER")
        rec_per = _FollowupRecorder()
        with ExitStack() as stack:
            for p in _persistent_patches(
                snapshot=_admissions_snapshot("NBC-PER")
            ):
                stack.enter_context(p)
            with _isolate_persistent_followups(rec_per):
                call_command("process_ingestion_runs_persistent_session")
        obs_per = _observable(run_per, "NBC-PER")

        assert obs_cur == obs_per
        for obs in (obs_cur, obs_per):
            assert obs["status"] == "succeeded"
            assert obs["admissions_seen"] == 2
            assert obs["admissions_created"] == 2
            assert obs["patient_exists"] is True
            assert obs["admission_count"] == 2
            assert obs["stage_statuses"] == {
                "admissions_capture": "succeeded"
            }
            assert obs["batch_status"] == "succeeded"
            assert obs["batch_closed"] is True
        assert rec_cur.fullsync_calls == ["called"]
        assert rec_per.fullsync_calls == ["called"]


# ===========================================================================
# R5: heterogeneous multi-job sequence through ONE authenticated handle
# ===========================================================================


def _build_all_containers_html(pr: str) -> str:
    """HTML carrying every container + a high ``#tempoSessao`` countdown so a
    real adapter (renewal + readiness) can serve all three intents for ``pr``."""
    return (
        "<html><body>"
        '<div id="tempoSessao">'
        "T: <span>00</span>:<span>29</span>:<span>01</span>"
        "</div>"
        '<div id="admission-snapshot-data">'
        + json.dumps(_admissions_snapshot_camel(pr))
        + "</div>"
        '<div id="demographics-data">'
        + json.dumps(_demographics(pr))
        + "</div>"
        '<div id="evolution-data">'
        + json.dumps(_evolutions_5key(pr))
        + "</div>"
        "</body></html>"
    )


@pytest.mark.django_db
class TestHeterogeneousMultiJobSequence:
    """admissions_only -> demographics_only -> full_sync -> admissions_only
    reuse ONE handle: one adapter creation, no browser/context relaunch, and
    safe cleanup (mark_job_processed) between jobs."""

    def test_four_heterogeneous_jobs_one_handle_no_relaunch(self) -> None:
        import subprocess

        pr = "SEQ-P1"
        html = _build_all_containers_html(pr)
        lifecycle: list[str] = []

        # Real adapter + fake session: a single handle is reused.
        class _SequenceSession:
            def __init__(self_inner) -> None:
                self_inner.restart_calls = 0
                self_inner.bootstrap_calls = 0

            def bootstrap(self_inner) -> None:
                # The ONE synthetic initial login/authentication boundary.
                # Marks the fake session ready and increments the counter so
                # the test can prove authentication ran exactly once.
                self_inner.bootstrap_calls += 1

            def get_page_html(self_inner) -> str:
                return html

            def is_connected(self_inner) -> bool:
                # Ready only after the initial login/bootstrap boundary.
                return self_inner.bootstrap_calls >= 1

            def click_selector(self_inner, selector: str) -> None:  # noqa: ARG002
                pass

            def open_tab(self_inner, url: str, *, timeout: int = 120) -> bool:  # noqa: ARG002
                lifecycle.append("open_tab")
                return True

            def get_tab_classes(self_inner) -> list[str]:
                # Root-only baseline so cleanup is a safe no-op between jobs.
                return ["tabs-first tabs-last tabs-selected"]

            def close_last_non_root_tab(self_inner):
                lifecycle.append("cleanup_tab")
                return TabCleanupOutcome.ROOT_ONLY

            def restart_browser(self_inner) -> None:
                self_inner.restart_calls += 1
                lifecycle.append("restart_browser")

            def supports_real_evolution_actions(self_inner) -> bool:
                # Explicit stub capability -> URL/container path (no real PDF).
                return False

        session = _SequenceSession()
        adapter = PersistentExtractionAdapter(session=session)

        # Instrument the REAL controller cleanup so we can prove a cleanup
        # checkpoint ran after each job without reimplementing selection. With
        # a root-only baseline the cleanup is a safe no-op (ROOT_ONLY); the
        # point is that the checkpoint fires per job.
        cleanup_checks: list[int] = []
        original_cleanup = adapter.controller.close_job_tab_if_present

        def _cleanup_recorder():
            cleanup_checks.append(1)
            return original_cleanup()

        adapter.controller.close_job_tab_if_present = _cleanup_recorder  # type: ignore[method-assign]

        # Queue exactly four heterogeneous jobs for the same patient.
        IngestionRun.objects.create(
            status="queued", intent="admissions_only",
            parameters_json={"patient_record": pr, "intent": "admissions_only"},
        )
        IngestionRun.objects.create(
            status="queued", intent="demographics_only",
            parameters_json={"patient_record": pr, "intent": "demographics_only"},
        )
        IngestionRun.objects.create(
            status="queued", intent="full_sync",
            parameters_json={
                "patient_record": pr, "intent": "full_sync",
                "start_date": "2024-01-01", "end_date": "2024-12-31",
            },
        )
        IngestionRun.objects.create(
            status="queued", intent="admissions_only",
            parameters_json={"patient_record": pr, "intent": "admissions_only"},
        )

        created_adapters: list = []

        def _create_once(self_cmd):
            # The patched command factory runs the ONE initial
            # bootstrap/login boundary, then returns the single adapter.
            session.bootstrap()
            created_adapters.append(adapter)
            return adapter

        # Suppress follow-up enqueue so only the four queued jobs run.
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", _create_once
        ), patch(
            "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"  # noqa: E501
            ".queue_demographics_only_run",
            return_value=MagicMock(),
        ), patch(
            "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"  # noqa: E501
            ".enqueue_most_recent_admission_full_sync",
            return_value=MagicMock(),
        ), patch.object(
            subprocess, "run", wraps=None
        ) as spy_subprocess:
            call_command("process_ingestion_runs_persistent_session")

        runs = [
            r for r in IngestionRun.objects.order_by("pk")
            if (r.parameters_json or {}).get("patient_record") == pr
        ]
        assert len(runs) == 4, runs
        assert all(r.status == "succeeded" for r in runs), [r.status for r in runs]

        # ONE handle created and reused for all four jobs. ONE initial
        # login/bootstrap; the same fake session identity backs every job.
        assert len(created_adapters) == 1
        assert created_adapters[0] is adapter
        assert adapter.session is session
        assert session.bootstrap_calls == 1, session.bootstrap_calls

        # No browser/context relaunch between jobs: restart never triggered
        # (restart_required stayed False) and restart_browser was never called.
        assert "restart_browser" not in lifecycle, lifecycle
        assert session.restart_calls == 0

        # Safe cleanup ran between jobs: every extraction method runs the
        # controller cleanup checkpoint and marks the job processed (full_sync
        # runs two methods -- admissions capture + evolution extraction -- so
        # it checkpoints twice; the total is 5 for 4 runs). The threshold
        # (default 50) is never reached, so no restart is triggered.
        assert len(cleanup_checks) >= 4, len(cleanup_checks)
        assert adapter.controller.jobs_processed >= 4, (
            adapter.controller.jobs_processed
        )

        # Heterogeneous intents really executed: every job opened at least
        # one source tab through the single handle.
        assert lifecycle.count("open_tab") >= 4, lifecycle

        # No subprocess on the persistent per-job path (R6).
        assert spy_subprocess.call_count == 0


# ===========================================================================
# R6: forbidden lifecycle / artifact calls remain zero
# ===========================================================================


@pytest.mark.django_db
class TestPersistentPathForbiddenCalls:
    """The persistent per-job path never invokes forbidden lifecycle or
    artifact surfaces for any supported intent (C1-R4)."""

    @pytest.mark.parametrize(
        "intent",
        [
            "admissions_only",
            "demographics_only",
            "full_sync",
            "full_admission_sync",
        ],
    )
    def test_no_forbidden_calls_for_intent(self, intent: str) -> None:
        import subprocess
        import tempfile

        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        pr = f"FORBID-{intent}"
        _make_run(intent, pr, **_run_params_for(intent))
        source = _source_for(intent, pr)
        with ExitStack() as stack:
            for p in _persistent_patches(**source):
                stack.enter_context(p)
            with patch(
                "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"  # noqa: E501
                ".queue_demographics_only_run",
                return_value=MagicMock(),
            ), patch(
                "apps.ingestion.management.commands.process_ingestion_runs_persistent_session"  # noqa: E501
                ".enqueue_most_recent_admission_full_sync",
                return_value=MagicMock(),
            ), patch.object(
                subprocess, "run"
            ) as spy_run, patch.object(
                subprocess, "Popen"
            ) as spy_popen, patch.object(
                tempfile, "TemporaryDirectory"
            ) as spy_tmpdir, patch.object(
                Path, "write_text"
            ) as spy_write_text, patch.object(
                Path, "write_bytes"
            ) as spy_write_bytes, patch.object(
                PlaywrightSessionHandle, "start"
            ) as spy_handle_start, patch.object(
                PlaywrightSessionHandle, "restart_browser"
            ) as spy_handle_restart:
                call_command("process_ingestion_runs_persistent_session")

        # No subprocess on the persistent per-job path.
        assert spy_run.call_count == 0, intent
        assert spy_popen.call_count == 0, intent
        # No temporary JSON/file artifact.
        assert spy_tmpdir.call_count == 0, intent
        assert spy_write_text.call_count == 0, intent
        assert spy_write_bytes.call_count == 0, intent
        # No real handle startup or restart per job (factory is patched, so
        # the real handle is never instantiated; this confirms the per-job
        # path does not start/restart it).
        assert spy_handle_start.call_count == 0, intent
        assert spy_handle_restart.call_count == 0, intent


# C1-R4: static sentinel guard -- the parity module never embeds a literal
# synthetic real URL or real report-route string. Built by concatenation so
# the guard does not match its own definition.
def test_no_url_sentinel_in_parity_module() -> None:
    module_path = Path(__file__).read_text(encoding="utf-8")
    sentinels = [
        "http" + "://",
        "https" + "://",
        "/evolutions" + "/",
        "relatorioAna" + "Evo",
    ]
    for sentinel in sentinels:
        assert sentinel not in module_path, sentinel


# ===========================================================================
# R7: empty / unknown intents receive no source action
# ===========================================================================


@pytest.mark.django_db
class TestEmptyUnknownIntentNoSourceAction:
    """Empty/unknown intents are outside replacement scope: the persistent
    worker does not claim them and performs no source action (composed from
    PSW-S14; confirmed here for the parity suite)."""

    @pytest.mark.parametrize("intent", ["", "unknown_purpose"])
    def test_not_claimed_no_source_action(self, intent: str) -> None:
        """Normal polling never claims empty/unknown intents: the row stays
        queued with no attempt and no clinical/source side effect."""
        mock_adapter = MagicMock()
        IngestionRun.objects.create(
            status="queued", intent=intent,
            parameters_json={"patient_record": "Z1", "intent": intent},
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=mock_adapter
        ):
            call_command("process_ingestion_runs_persistent_session")

        # No source extraction was attempted for the unsupported intent.
        mock_adapter.get_admission_snapshot.assert_not_called()
        mock_adapter.get_demographics.assert_not_called()
        mock_adapter.extract_evolutions.assert_not_called()
        # The row was never claimed or mutated.
        run = IngestionRun.objects.get(intent=intent)
        assert run.status == "queued"
        assert run.attempt_count == 0
        assert not Patient.objects.filter(
            source_system="tasy", patient_source_key="Z1"
        ).exists()

    def test_unknown_intent_selected_rejects_without_adapter(self) -> None:
        run = IngestionRun.objects.create(
            status="queued", intent="bogus", max_attempts=3,
            parameters_json={"patient_record": "Z2", "intent": "bogus"},
        )
        with patch.object(
            PersistentWorkerCommand, "_create_adapter"
        ) as mock_create:
            call_command(
                "process_ingestion_runs_persistent_session", run_id=run.pk
            )
        # Explicit unsupported selection never creates the adapter/browser.
        mock_create.assert_not_called()
        run.refresh_from_db()
        assert run.status == "queued"
        assert run.attempt_count == 0
