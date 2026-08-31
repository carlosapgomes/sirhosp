"""PFIF-S2: current-versus-persistent parity for the encounter fallback.

PFIF-S1 gave the persistent worker a conditional, read-only ``Atendimentos``
fallback after a batch-bound empty admissions capture. PFIF-S2 closes the
parity: the classic worker (``process_ingestion_runs`` + ``path2.py``
subprocess) must reach the SAME external outcomes.

Scenario matrix (each row executed through BOTH worker commands with
equivalent synthetic sources, comparing only externally visible effects):

- ``recent``: empty admissions + today encounter -> succeeded, zero clinical
  effect, ``encounter_fallback`` stage with the closed outcome/recency enum,
  batch drains, no follow-ups.
- ``boundary`` / ``stale`` / ``none``: empty admissions with non-recent or
  absent evidence -> existing fail-closed ``invalid_payload`` preserved.
- ``capture_error``: encounter evidence capture failure -> shared
  ``source_unavailable`` retry taxonomy, requeued, no persistence.
- ``nonempty``: valid admissions capture -> old persistence/full-sync path.
- ``standalone_empty``: batch-less empty capture -> explicit success with
  ``seen=0`` and no fallback.

Path2 sidecar (R1) and classic extractor (R2) behaviors are proven at their
own layer: the optional ``--encounters-output`` sidecar is consulted ONLY for
an empty admissions-only capture explicitly requesting it, the historical
admissions JSON list output stays byte/shape compatible, and ONE subprocess
per job serves both artifacts through a job-scoped cache.

Normalization: patient-record tokens differ per worker (CUR/PER suffixes) and
are never compared; follow-up comparison uses call counts; worker-specific
``error_message``/stdout text is not compared. All fixtures are synthetic.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from contextlib import ExitStack, contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.ingestion.extractors.errors import ExtractionError
from apps.ingestion.extractors.patient_flow_snapshot import (
    EncounterRecency,
    PatientFlowSnapshot,
)
from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
    Command as PersistentWorkerCommand,
)
from apps.ingestion.models import (
    CensusExecutionBatch,
    IngestionRun,
    IngestionRunAttempt,
    IngestionRunStageMetric,
)
from apps.patients.models import Admission, Patient

# ---------------------------------------------------------------------------
# path2.py module loader (same recipe as test_path2_signature_datetime_fallback)
# ---------------------------------------------------------------------------

_PATH2_DIR = (
    Path(__file__).resolve().parents[2]
    / "automation"
    / "source_system"
    / "medical_evolution"
)
_PATH2_FILE = _PATH2_DIR / "path2.py"

if str(_PATH2_DIR) not in sys.path:
    sys.path.insert(0, str(_PATH2_DIR))

_config_spec = importlib.util.spec_from_file_location(
    "config",
    _PATH2_DIR / "config.py",
)
assert _config_spec is not None
assert _config_spec.loader is not None
_config_mod = importlib.util.module_from_spec(_config_spec)
_config_spec.loader.exec_module(_config_mod)

_previous_config_module = sys.modules.get("config")
try:
    sys.modules["config"] = _config_mod
    _spec = importlib.util.spec_from_file_location("_path2_pfif_s2", _PATH2_FILE)
    assert _spec is not None
    assert _spec.loader is not None
    _path2 = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_path2)
finally:
    if _previous_config_module is not None:
        sys.modules["config"] = _previous_config_module
    else:
        sys.modules.pop("config", None)


# ---------------------------------------------------------------------------
# R1: path2.py optional encounter sidecar
# ---------------------------------------------------------------------------


class _FakeEncountersFrame:
    """Synthetic frame returning fixed rows from ``eval_on_selector_all``."""

    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows
        self.selector_seen: str | None = None

    def eval_on_selector_all(self, selector: str, _script: str):
        self.selector_seen = selector
        return self._rows


class TestPath2EncounterSidecar:
    """R1: sidecar is optional, conditional and shape-compatible."""

    def _write_sidecar(
        self,
        tmp_path: Path,
        rows: list[dict[str, Any]],
    ) -> Path:
        frame = _FakeEncountersFrame(rows)
        sidecar_path = tmp_path / "encounters.json"
        with patch.object(_path2, "wait_encounters_table", return_value=frame):
            dates = _path2.read_encounter_dates(page=MagicMock())
        _path2.salvar_encounter_dates_json(dates, sidecar_path)
        return sidecar_path

    def test_read_encounter_dates_sorts_and_filters_structurally(self, tmp_path):
        """Out-of-order valid dates are sorted; rows without four cells or
        with an invalid DD/MM/AAAA first cell are ignored (S1 semantics)."""
        frame = _FakeEncountersFrame(
            [
                {
                    "cells": [
                        "13/05/2025",
                        "TIPO-B",
                        "SERVICO-B",
                        "PROFISSIONAL-B",
                    ]
                },
                {
                    "cells": [
                        "12/05/2025",
                        "TIPO-A",
                        "SERVICO-A",
                        "PROFISSIONAL-A",
                    ]
                },
                # Invalid date in the first cell -> ignored.
                {"cells": ["data-invalida", "T", "S", "P"]},
                # Fewer than four cells -> ignored.
                {"cells": ["11/05/2025", "TIPO-C"]},
                # Empty cells -> ignored.
                {"cells": []},
            ]
        )
        with patch.object(_path2, "wait_encounters_table", return_value=frame):
            dates = _path2.read_encounter_dates(page=MagicMock())
        assert dates == [date(2025, 5, 12), date(2025, 5, 13)]
        assert frame.selector_seen == _path2.ATENDIMENTOS_TABLE_ROWS_SELECTOR

    def test_sidecar_artifact_carries_iso_dates_only(self, tmp_path):
        """The sidecar is a minimal ``{"encounter_dates": [...]}`` object with
        ISO dates only — no row text, type, specialty or professional."""
        sidecar_path = self._write_sidecar(
            tmp_path,
            [
                {"cells": ["13/05/2025", "TIPO-B", "S-B", "P-B"]},
                {"cells": ["12/05/2025", "TIPO-A", "S-A", "P-A"]},
            ],
        )
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert payload == {
            "encounter_dates": ["2025-05-12", "2025-05-13"]
        }

    def test_empty_admissions_with_option_consults_atendimentos(self, tmp_path):
        """Empty admissions-only capture + explicit option -> the
        Atendimentos table is consulted and the sidecar is written."""
        sidecar_path = tmp_path / "encounters.json"
        dates = [date(2025, 5, 12)]
        with patch.object(
            _path2, "read_encounter_dates", return_value=dates
        ) as read_mock:
            _path2._capture_encounter_sidecar(
                MagicMock(),
                all_admissions=[],
                admissions_only=True,
                encounters_output_path=sidecar_path,
            )
        read_mock.assert_called_once()
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert payload == {"encounter_dates": ["2025-05-12"]}

    def test_nonempty_admissions_never_consults_atendimentos(self, tmp_path):
        """A non-empty admission snapshot must NOT reach Atendimentos and no
        sidecar is written."""
        sidecar_path = tmp_path / "encounters.json"
        admissions = [{"admissionKey": "K-1", "admissionStart": "2025-05-01"}]
        with patch.object(
            _path2, "read_encounter_dates"
        ) as read_mock:
            _path2._capture_encounter_sidecar(
                MagicMock(),
                all_admissions=admissions,
                admissions_only=True,
                encounters_output_path=sidecar_path,
            )
        read_mock.assert_not_called()
        assert not sidecar_path.exists()

    def test_missing_option_never_consults_atendimentos(self, tmp_path):
        """CLI compatibility: without the new option the behavior is exactly
        the historical one — no Atendimentos consultation, no sidecar."""
        sidecar_path = tmp_path / "encounters.json"
        with patch.object(
            _path2, "read_encounter_dates"
        ) as read_mock:
            _path2._capture_encounter_sidecar(
                MagicMock(),
                all_admissions=[],
                admissions_only=True,
                encounters_output_path=None,
            )
            _path2._capture_encounter_sidecar(
                MagicMock(),
                all_admissions=[],
                admissions_only=False,
                encounters_output_path=sidecar_path,
            )
        read_mock.assert_not_called()
        assert not sidecar_path.exists()

    def test_admissions_output_stays_a_json_list_alongside_sidecar(
        self, tmp_path
    ):
        """Byte/shape compatibility: the historical admissions artifact stays
        a JSON LIST while the sidecar is written beside it."""
        admissions = [
            {
                "admissionKey": "K-1",
                "admissionStart": "2025-05-01",
                "admissionEnd": None,
                "ward": "W",
                "bed": "B",
            }
        ]
        admissions_path = tmp_path / "admissions.json"
        sidecar_path = tmp_path / "encounters.json"
        _path2.salvar_admissions_json(admissions, admissions_path)
        with patch.object(
            _path2,
            "read_encounter_dates",
            return_value=[date(2025, 5, 12)],
        ):
            _path2._capture_encounter_sidecar(
                MagicMock(),
                all_admissions=[],
                admissions_only=True,
                encounters_output_path=sidecar_path,
            )
        loaded = json.loads(admissions_path.read_text(encoding="utf-8"))
        assert isinstance(loaded, list)
        assert loaded == admissions
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert set(sidecar.keys()) == {"encounter_dates"}

    def test_cli_accepts_optional_encounters_output(self):
        """The new CLI option parses and defaults to None (no option = old
        behavior)."""
        argv = [
            "path2.py",
            "--admissions-output",
            "admissions.json",
            "--admissions-only",
            "--encounters-output",
            "encounters.json",
        ]
        with patch.object(sys, "argv", argv):
            args = _path2.parse_args()
        assert args.encounters_output == Path("encounters.json")

        with patch.object(sys, "argv", ["path2.py"]):
            args_default = _path2.parse_args()
        assert args_default.encounters_output is None

    def test_encounters_output_requires_admissions_only_mode(self, tmp_path):
        """Requesting the sidecar outside admissions-only mode is rejected
        before any browser/session work."""
        with pytest.raises(RuntimeError, match="admissions-only"):
            _path2.run(
                source_system_url="https://source.invalid.test",
                username="user",
                password="password",
                patient_record="1",
                start_date="01/01/2024",
                end_date="02/01/2024",
                internacao_index=-1,
                output_path=tmp_path / "out.pdf",
                debug_output_path=tmp_path / "debug.html",
                txt_output_path=tmp_path / "out.txt",
                normalized_txt_output_path=tmp_path / "norm.txt",
                processed_txt_output_path=tmp_path / "proc.txt",
                sorted_txt_output_path=tmp_path / "sorted.txt",
                json_output_path=tmp_path / "out.json",
                admissions_output_path=tmp_path / "admissions.json",
                admissions_only=False,
                encounters_output_path=tmp_path / "encounters.json",
                headless=True,
            )


# ---------------------------------------------------------------------------
# R2: classic extractor enriched API
# ---------------------------------------------------------------------------

_EXTRACTOR_MODULE = "apps.ingestion.extractors.playwright_extractor"


def _extractor_fake_run(
    calls: list[list[str]],
    *,
    admissions: list[dict[str, Any]] | None = None,
    encounter_dates: list[str] | None = None,
    returncode: int = 0,
):
    """Build a ``run_subprocess`` fake that writes path2-style artifacts."""

    def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
        calls.append(list(cmd))

        def artifact_path(flag: str) -> Path:
            return Path(cmd[cmd.index(flag) + 1])

        admissions_path = artifact_path("--admissions-output")
        admissions_path.parent.mkdir(parents=True, exist_ok=True)
        admissions_path.write_text(
            json.dumps(admissions if admissions is not None else []),
            encoding="utf-8",
        )
        if encounter_dates is not None:
            sidecar_path = artifact_path("--encounters-output")
            sidecar_path.write_text(
                json.dumps({"encounter_dates": encounter_dates}),
                encoding="utf-8",
            )
        result = MagicMock()
        result.returncode = returncode
        result.stdout = ""
        result.stderr = ""
        return result

    return fake_run


def _camel_admissions() -> list[dict[str, Any]]:
    return [
        {
            "admissionKey": "ADM-FLOW-1",
            "admissionStart": "2026-05-01",
            "admissionEnd": None,
            "ward": "ENFERMARIA-A",
            "bed": "01",
        }
    ]


class TestClassicExtractorFlowSnapshot:
    """R2: ONE subprocess per job, sidecar read from tmpdir, sanitized
    failures, admissions list API preserved."""

    def _extractor(self, tmp_path: Path) -> Any:
        from apps.ingestion.extractors.playwright_extractor import (
            PlaywrightEvolutionExtractor,
        )

        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        return PlaywrightEvolutionExtractor(script_path=str(fake_script))

    def test_one_subprocess_serves_admissions_and_sidecar(self, tmp_path):
        """The enriched flow API reuses the job's single admissions
        subprocess: exactly one invocation serves both artifacts, and the
        tmpdir artifacts are gone after the call."""
        extractor = self._extractor(tmp_path)
        today = date(2026, 5, 20)
        calls: list[list[str]] = []
        with patch(
            f"{_EXTRACTOR_MODULE}.run_subprocess",
            side_effect=_extractor_fake_run(
                calls, admissions=[], encounter_dates=["2026-05-20"]
            ),
        ):
            admissions = extractor.get_admission_snapshot(
                patient_record="PR-ONE",
                start_date="2000-01-01",
                end_date="2026-05-20",
                include_encounter_sidecar=True,
            )
            flow = extractor.get_patient_flow_snapshot(
                patient_record="PR-ONE", today=today
            )
        assert len(calls) == 1
        assert admissions == []
        assert flow.is_empty is True
        assert flow.encounter_recency is EncounterRecency.RECENT_CONFIRMED
        # One subprocess requested both artifacts.
        assert calls[0].count("--admissions-output") == 1
        assert calls[0].count("--encounters-output") == 1
        assert "--admissions-only" in calls[0]
        # tmpdir cleanup: artifacts removed with the TemporaryDirectory.
        admissions_artifact = Path(
            calls[0][calls[0].index("--admissions-output") + 1]
        )
        assert not admissions_artifact.exists()

    def test_standalone_flow_snapshot_runs_one_subprocess(self, tmp_path):
        """A direct ``get_patient_flow_snapshot`` is self-contained with a
        single subprocess invocation."""
        extractor = self._extractor(tmp_path)
        today = date(2026, 5, 20)
        calls: list[list[str]] = []
        with patch(
            f"{_EXTRACTOR_MODULE}.run_subprocess",
            side_effect=_extractor_fake_run(
                calls, admissions=[], encounter_dates=["2026-05-18"]
            ),
        ):
            flow = extractor.get_patient_flow_snapshot(
                patient_record="PR-STANDALONE", today=today
            )
        assert len(calls) == 1
        assert flow.encounter_recency is EncounterRecency.BOUNDARY

    def test_nonempty_capture_ignores_sidecar(self, tmp_path):
        """A non-empty admissions capture never binds encounter evidence —
        the fallback contract only applies to empty captures."""
        extractor = self._extractor(tmp_path)
        calls: list[list[str]] = []
        with patch(
            f"{_EXTRACTOR_MODULE}.run_subprocess",
            side_effect=_extractor_fake_run(
                calls,
                admissions=_camel_admissions(),
                encounter_dates=["2026-05-20"],
            ),
        ):
            flow = extractor.get_patient_flow_snapshot(
                patient_record="PR-NONEMPTY", today=date(2026, 5, 20)
            )
        assert flow.is_empty is False
        assert flow.encounter_recency is EncounterRecency.NONE
        assert flow.admissions[0]["admission_key"] == "ADM-FLOW-1"

    @pytest.mark.parametrize(
        "offset, expected_recency",
        [
            (0, EncounterRecency.RECENT_CONFIRMED),
            (1, EncounterRecency.RECENT_CONFIRMED),
            (2, EncounterRecency.BOUNDARY),
            (30, EncounterRecency.STALE),
        ],
    )
    def test_sidecar_dates_map_to_s1_recency_buckets(
        self, tmp_path, offset: int, expected_recency: EncounterRecency
    ):
        """The classic path reuses the S1 classifier: date buckets are
        computed by the shared contract, not reimplemented."""
        extractor = self._extractor(tmp_path)
        today = date(2026, 5, 20)
        encounter_day = today - timedelta(days=offset)
        calls: list[list[str]] = []
        with patch(
            f"{_EXTRACTOR_MODULE}.run_subprocess",
            side_effect=_extractor_fake_run(
                calls,
                admissions=[],
                encounter_dates=[encounter_day.isoformat()],
            ),
        ):
            flow = extractor.get_patient_flow_snapshot(
                patient_record="PR-BUCKET", today=today
            )
        assert flow.encounter_recency is expected_recency

    def test_sidecar_without_valid_dates_maps_to_none(self, tmp_path):
        extractor = self._extractor(tmp_path)
        today = date(2026, 5, 20)
        calls: list[list[str]] = []
        with patch(
            f"{_EXTRACTOR_MODULE}.run_subprocess",
            side_effect=_extractor_fake_run(
                calls, admissions=[], encounter_dates=[]
            ),
        ):
            flow = extractor.get_patient_flow_snapshot(
                patient_record="PR-NONE", today=today
            )
        assert flow.encounter_recency is EncounterRecency.NONE

    def test_missing_sidecar_for_empty_capture_fails_sanitized(self, tmp_path):
        """Empty admissions + requested sidecar absent -> sanitized typed
        failure with a constant message (no paths, no record tokens)."""
        extractor = self._extractor(tmp_path)
        calls: list[list[str]] = []
        with patch(
            f"{_EXTRACTOR_MODULE}.run_subprocess",
            side_effect=_extractor_fake_run(
                calls, admissions=[], encounter_dates=None
            ),
        ):
            with pytest.raises(ExtractionError) as excinfo:
                extractor.get_admission_snapshot(
                    patient_record="PR-SENTINEL-RECORD-7777",
                    start_date="2000-01-01",
                    end_date="2026-05-20",
                    include_encounter_sidecar=True,
                )
        message = str(excinfo.value)
        assert "sidecar" in message
        assert "PR-SENTINEL-RECORD-7777" not in message
        assert str(tmp_path) not in message

    @pytest.mark.parametrize(
        "sidecar_body",
        [
            "not-json-at-all",
            "[\"wrong-root\"]",
            "{\"unexpected\": []}",
            "{\"encounter_dates\": \"wrong-type\"}",
            "{\"encounter_dates\": [\"20/05/2026\"]}",
        ],
    )
    def test_malformed_sidecar_fails_sanitized(
        self, tmp_path, sidecar_body: str
    ):
        extractor = self._extractor(tmp_path)
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            calls.append(list(cmd))
            admissions_path = Path(cmd[cmd.index("--admissions-output") + 1])
            admissions_path.parent.mkdir(parents=True, exist_ok=True)
            admissions_path.write_text("[]", encoding="utf-8")
            sidecar_path = Path(cmd[cmd.index("--encounters-output") + 1])
            sidecar_path.write_text(sidecar_body, encoding="utf-8")
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            f"{_EXTRACTOR_MODULE}.run_subprocess", side_effect=fake_run
        ):
            with pytest.raises(ExtractionError) as excinfo:
                extractor.get_admission_snapshot(
                    patient_record="PR-MALFORMED",
                    start_date="2000-01-01",
                    end_date="2026-05-20",
                    include_encounter_sidecar=True,
                )
        assert "PR-MALFORMED" not in str(excinfo.value)

    def test_default_admission_api_has_no_sidecar_and_keeps_list(self, tmp_path):
        """Historical contract: without the flag, no ``--encounters-output``
        is passed and the list result is unchanged."""
        extractor = self._extractor(tmp_path)
        calls: list[list[str]] = []
        with patch(
            f"{_EXTRACTOR_MODULE}.run_subprocess",
            side_effect=_extractor_fake_run(
                calls, admissions=_camel_admissions()
            ),
        ):
            admissions = extractor.get_admission_snapshot(
                patient_record="PR-LEGACY",
                start_date="2000-01-01",
                end_date="2026-05-20",
            )
        assert calls[0].count("--encounters-output") == 0
        assert isinstance(admissions, list)
        assert admissions[0]["admission_key"] == "ADM-FLOW-1"


# ---------------------------------------------------------------------------
# R3/R4: worker parity matrix
# ---------------------------------------------------------------------------

_CURRENT_EXTRACTOR_PATH = (
    "apps.ingestion.management.commands.process_ingestion_runs"
    ".PlaywrightEvolutionExtractor"
)

# Closed scenario rows: recency buckets, capture failure, non-empty capture
# and standalone empty capture.
_SCENARIOS = [
    "recent",
    "boundary",
    "stale",
    "none",
    "capture_error",
    "nonempty",
    "standalone_empty",
]

_RECENT_OFFSETS = {"recent": (0,), "boundary": (2,), "stale": (30,)}

_BATCH_BOUND = {"recent", "boundary", "stale", "none", "capture_error", "nonempty"}


def _snake_admissions(pr: str) -> list[dict[str, Any]]:
    """Synthetic non-empty admissions snapshot (worker-level, snake_case)."""
    return [
        {
            "admission_key": f"ADM-PF-A-{pr}",
            "admission_start": "2026-05-01 00:00:00",
            "admission_end": None,
            "ward": "ENFERMARIA-A",
            "bed": "01",
        },
        {
            "admission_key": f"ADM-PF-B-{pr}",
            "admission_start": "2026-05-10 00:00:00",
            "admission_end": None,
            "ward": "ENFERMARIA-B",
            "bed": "02",
        },
    ]


class _FollowupRecorder:
    """Counts follow-up enqueues without creating real runs."""

    def __init__(self) -> None:
        self.demo_calls: list[str] = []
        self.fullsync_calls: list[str] = []

    def demo(self, *args: Any, **kwargs: Any) -> MagicMock:
        self.demo_calls.append(kwargs.get("patient_record", ""))
        return MagicMock()

    def fullsync(self, *args: Any, **kwargs: Any) -> MagicMock:
        self.fullsync_calls.append("called")
        return MagicMock()

    def as_dict(self) -> dict[str, int]:
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


@pytest.mark.django_db
class TestEncounterFallbackParityMatrix:
    """Each scenario runs through BOTH workers with equivalent synthetic
    sources; externally visible effects must compare equal."""

    def _build_source(self, scenario: str, pr: str) -> tuple[Any, Any]:
        """Return (admissions_snapshot, flow_snapshot) for the scenario."""
        today = timezone.localdate()
        if scenario == "nonempty":
            admissions: list[dict[str, Any]] = _snake_admissions(pr)
            flow = PatientFlowSnapshot.build(
                admissions=admissions, encounter_dates=[], today=today
            )
            return admissions, flow
        empty_admissions: list[dict[str, Any]] = []
        offsets = _RECENT_OFFSETS.get(scenario, ())
        flow = PatientFlowSnapshot.build(
            admissions=[],
            encounter_dates=[today - timedelta(days=o) for o in offsets],
            today=today,
        )
        return empty_admissions, flow

    def _execute(
        self, scenario: str, worker: str, pr: str
    ) -> tuple[IngestionRun, _FollowupRecorder, MagicMock]:
        admissions, flow = self._build_source(scenario, pr)
        flow_error = (
            ExtractionError("Encounter evidence capture failed.")
            if scenario == "capture_error"
            else None
        )

        batch = (
            CensusExecutionBatch.objects.create(status="running")
            if scenario in _BATCH_BOUND
            else None
        )
        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            max_attempts=3,
            parameters_json={"patient_record": pr, "intent": "admissions_only"},
        )
        rec = _FollowupRecorder()

        source_mock = MagicMock()
        source_mock.get_admission_snapshot.return_value = admissions
        if flow_error is not None:
            source_mock.get_patient_flow_snapshot.side_effect = flow_error
        else:
            source_mock.get_patient_flow_snapshot.return_value = flow

        if worker == "current":
            patches = [
                patch(_CURRENT_EXTRACTOR_PATH, return_value=source_mock)
            ]
            followups_cm = _isolate_current_followups(rec)
            command = "process_ingestion_runs"
        else:
            source_mock.get_demographics.return_value = {}
            source_mock.extract_evolutions.return_value = []
            source_mock.ensure_session_ready.return_value = True
            source_mock.cleanup_after_failure = MagicMock()
            source_mock.controller = MagicMock()
            source_mock.controller.restart_required.return_value = False
            patches = [
                patch.object(
                    PersistentWorkerCommand,
                    "_create_adapter",
                    return_value=source_mock,
                )
            ]
            followups_cm = _isolate_persistent_followups(rec)
            command = "process_ingestion_runs_persistent_session"

        with ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            stack.enter_context(followups_cm)
            call_command(command)
        return run, rec, source_mock

    def _observable(self, run: IngestionRun, pr: str) -> dict[str, Any]:
        run.refresh_from_db()
        stages: dict[str, dict[str, Any]] = {}
        for stage in IngestionRunStageMetric.objects.filter(run=run):
            stages[stage.stage_name] = {
                "status": stage.status,
                "details_json": stage.details_json,
            }
        attempts = list(IngestionRunAttempt.objects.filter(run=run))
        latest = (
            max(attempts, key=lambda a: a.attempt_number) if attempts else None
        )
        batch = run.batch
        return {
            "status": run.status,
            "failure_reason": run.failure_reason,
            "timed_out": run.timed_out,
            "attempt_count": run.attempt_count,
            "attempt_status": latest.status if latest else None,
            "attempt_failure_reason": (
                latest.failure_reason if latest else None
            ),
            "admissions_seen": run.admissions_seen,
            "admissions_created": run.admissions_created,
            "admissions_updated": run.admissions_updated,
            "events_processed": run.events_processed,
            "events_created": run.events_created,
            "events_skipped": run.events_skipped,
            "events_revised": run.events_revised,
            "stages": stages,
            "patient_exists": Patient.objects.filter(
                source_system="tasy", patient_source_key=pr
            ).exists(),
            "admission_count": Admission.objects.filter(
                patient__patient_source_key=pr
            ).count(),
            "next_retry_at_present": run.next_retry_at is not None,
            "finished_present": run.finished_at is not None,
            "batch_status": batch.status if batch else None,
            "batch_closed": (
                batch.finished_at is not None if batch else None
            ),
        }

    def _assert_expected(
        self,
        scenario: str,
        obs: dict[str, Any],
        rec: _FollowupRecorder,
        source_mock: MagicMock,
    ) -> None:
        """Independent expected-value checks (not worker equality)."""
        if scenario == "recent":
            assert obs["status"] == "succeeded"
            assert obs["failure_reason"] == ""
            assert obs["admissions_seen"] == 0
            assert obs["admissions_created"] == 0
            assert obs["events_created"] == 0
            assert set(obs["stages"]) == {
                "admissions_capture",
                "encounter_fallback",
            }
            assert obs["stages"]["encounter_fallback"] == {
                "status": "succeeded",
                "details_json": {
                    "outcome": "recent_encounter_without_admission",
                    "recency": "recent_confirmed",
                },
            }
            assert obs["attempt_status"] == "succeeded"
            assert obs["patient_exists"] is False
            assert obs["admission_count"] == 0
            assert obs["batch_status"] == "succeeded"
            assert obs["batch_closed"] is True
            assert rec.as_dict() == {
                "demo_call_count": 0,
                "fullsync_call_count": 0,
            }
            # Exactly one evidence consultation per job.
            assert source_mock.get_patient_flow_snapshot.call_count == 1
            assert source_mock.get_admission_snapshot.call_count == 1
        elif scenario in ("boundary", "stale", "none"):
            assert obs["status"] == "failed"
            assert obs["failure_reason"] == "invalid_payload"
            assert obs["timed_out"] is False
            assert obs["next_retry_at_present"] is False
            assert list(obs["stages"]) == ["admissions_capture"]
            assert obs["stages"]["admissions_capture"]["status"] == "failed"
            assert obs["patient_exists"] is False
            assert obs["admission_count"] == 0
            assert obs["batch_status"] == "failed"
            assert obs["batch_closed"] is True
            assert rec.as_dict() == {
                "demo_call_count": 0,
                "fullsync_call_count": 0,
            }
        elif scenario == "capture_error":
            assert obs["failure_reason"] == "source_unavailable"
            assert obs["status"] == "queued"
            assert obs["next_retry_at_present"] is True
            assert list(obs["stages"]) == ["admissions_capture"]
            assert obs["stages"]["admissions_capture"]["status"] == "failed"
            assert obs["patient_exists"] is False
            assert obs["batch_status"] == "running"
            assert rec.as_dict() == {
                "demo_call_count": 0,
                "fullsync_call_count": 0,
            }
        elif scenario == "nonempty":
            assert obs["status"] == "succeeded"
            assert obs["admissions_seen"] == 2
            assert obs["patient_exists"] is True
            assert obs["admission_count"] == 2
            assert obs["batch_status"] == "succeeded"
            # Non-empty captures never consult the fallback.
            source_mock.get_patient_flow_snapshot.assert_not_called()
            # Batch-bound runs own their demographics; full-sync follows.
            assert rec.as_dict() == {
                "demo_call_count": 0,
                "fullsync_call_count": 1,
            }
        elif scenario == "standalone_empty":
            assert obs["status"] == "succeeded"
            assert obs["admissions_seen"] == 0
            assert list(obs["stages"]) == ["admissions_capture"]
            assert obs["stages"]["admissions_capture"]["status"] == "succeeded"
            assert obs["batch_status"] is None
            # Explicit standalone contract kept: no fallback, demographics
            # follow-up enqueued, and no full-sync candidate is created (the
            # enqueuer is invoked but finds no admission).
            source_mock.get_patient_flow_snapshot.assert_not_called()
            assert rec.as_dict() == {
                "demo_call_count": 1,
                "fullsync_call_count": 1,
            }
            assert not IngestionRun.objects.filter(
                intent="full_sync",
                parameters_json__patient_record=rec.demo_calls[0],
            ).exists()

    @pytest.mark.parametrize("scenario", _SCENARIOS)
    def test_current_and_persistent_outcomes_are_equivalent(
        self, scenario: str
    ) -> None:
        run_cur, rec_cur, mock_cur = self._execute(
            scenario, "current", f"ENC-CUR-{scenario}"
        )
        run_per, rec_per, mock_per = self._execute(
            scenario, "persistent", f"ENC-PER-{scenario}"
        )
        obs_cur = self._observable(run_cur, f"ENC-CUR-{scenario}")
        obs_per = self._observable(run_per, f"ENC-PER-{scenario}")
        assert obs_cur == obs_per, (
            f"Scenario {scenario} observable mismatch:\n"
            f"current={obs_cur}\npersistent={obs_per}"
        )
        # Follow-up enqueue patterns must match too (counts only; PR tokens
        # differ per worker and are never compared).
        assert rec_cur.as_dict() == rec_per.as_dict(), (
            f"Scenario {scenario} follow-up mismatch: "
            f"current={rec_cur.as_dict()} persistent={rec_per.as_dict()}"
        )
        self._assert_expected(scenario, obs_cur, rec_cur, mock_cur)
        self._assert_expected(scenario, obs_per, rec_per, mock_per)

    def test_capture_error_cleans_persistent_session(self) -> None:
        """On fallback failure the persistent worker still runs its cleanup;
        the classic worker cleanup is the tmpdir lifecycle proven at the
        extractor layer."""
        _, _, mock_per = self._execute(
            "capture_error", "persistent", "ENC-PER-CLEAN"
        )
        mock_per.cleanup_after_failure.assert_called_once()


# ---------------------------------------------------------------------------
# R5: privacy sentinels
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEncounterFallbackPrivacySentinels:
    """No patient-record sentinel, professional or raw payload reaches any
    persisted or emitted output in either worker."""

    @pytest.mark.parametrize("worker", ["current", "persistent"])
    def test_sentinels_absent_from_outputs(self, worker: str, capsys) -> None:
        sentinel = "SENTINEL-RECORD-7777"
        pr = f"ENC-{'CUR' if worker == 'current' else 'PER'}-{sentinel}"
        run, _rec, _mock = TestEncounterFallbackParityMatrix()._execute(
            "recent", worker, pr
        )

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert sentinel not in combined
        assert "PROFISSIONAL-XYZ" not in combined

        run.refresh_from_db()
        assert sentinel not in (run.error_message or "")
        for stage in IngestionRunStageMetric.objects.filter(run=run):
            serialized = json.dumps(stage.details_json or {})
            assert sentinel not in serialized
            assert "PROFISSIONAL-XYZ" not in serialized
            # Stage details stay enum-only for the fallback stage.
            if stage.stage_name == "encounter_fallback":
                assert set(stage.details_json) == {"outcome", "recency"}
