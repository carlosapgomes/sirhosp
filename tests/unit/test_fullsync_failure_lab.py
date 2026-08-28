"""CFC-S2: unit tests for the synthetic full-sync failure lab harness.

Contracts (RED):

- H1 (timeout por volume/deadline): a synthetic long evolution list driven
  through the REAL ``EvolutionPdfFlow`` with a constrained deadline raises a
  typed timeout that the REAL classifier maps to ``timeout``; the experiment
  records the measured duration. A generous-deadline control completes and
  parses the expected number of synthetic events (no timeout).
- H2 (invalid_payload por conteúdo): every synthetic invalid-content fixture
  maps to ``invalid_payload`` through the real classification path, recording
  which validation triggered the mapping; a valid synthetic control does NOT
  map to ``invalid_payload``.
- Verdict artifacts: every experiment emits the full schema
  (hypothesis, fixture, params, measured_duration_seconds, reason, verdict,
  notes) and the runner consolidates ``verdicts.json`` deterministically.
- Isolation: fixtures are 100% synthetic (sentinels, no production strings);
  the harness imports from ``apps/`` only the real exercised points and is
  never imported by operational code; experiments never touch network,
  subprocess or Playwright (a real browser is never required).
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict
from pathlib import Path
from unittest import mock

import pytest

from automation.lab.playwright_experiments import fullsync_failure_lab as lab

LAB_FILE = Path(lab.__file__).resolve()
LAB_DIR = LAB_FILE.parent
FIXTURES_DIR = LAB_DIR / "fixtures"
REPO_ROOT = LAB_FILE.parents[3]

VERDICT_KEYS = {
    "hypothesis",
    "fixture",
    "params",
    "measured_duration_seconds",
    "reason",
    "verdict",
    "notes",
}
VERDICT_VALUES = {"confirmed", "refuted", "inconclusive"}
SENTINEL = lab.SYNTHETIC_SENTINEL
FORBIDDEN_TOKENS = (
    "tasy",
    "prontuario",
    "paciente",
    "hospital",
    "senha",
    "password",
    "token",
    "secret",
    "cookie",
)


class TestH1TimeoutByVolume:
    """R1: short deadline + synthetic long list -> reason ``timeout`` with
    measured duration; generous-deadline control does not time out."""

    def test_short_deadline_produces_timeout_with_measured_duration(self) -> None:
        verdict = lab.run_h1_timeout_experiment(
            item_count=120,
            deadline_seconds=1,
            latency_per_item_ms=10,
        )
        assert verdict.hypothesis == "H1-timeout-by-volume-deadline"
        assert verdict.reason == "timeout"
        assert verdict.verdict == "confirmed"
        assert verdict.measured_duration_seconds is not None
        assert verdict.measured_duration_seconds > 0.0
        # Parameters are recorded so a third party can re-run the exact case.
        assert verdict.params["item_count"] == 120
        assert verdict.params["deadline_seconds"] == 1
        assert verdict.params["latency_per_item_ms"] == 10

    def test_flow_bounded_the_download_by_the_deadline(self) -> None:
        verdict = lab.run_h1_timeout_experiment(
            item_count=120,
            deadline_seconds=1,
            latency_per_item_ms=10,
        )
        download_timeout_ms = verdict.params["download_timeout_ms"]
        assert download_timeout_ms is not None
        assert 0 < download_timeout_ms <= 1 * 1000

    def test_generous_deadline_control_does_not_timeout(self) -> None:
        verdict = lab.run_h1_control_experiment(
            item_count=12,
            deadline_seconds=60,
            latency_per_item_ms=10,
        )
        assert verdict.hypothesis == "H1-control-generous-deadline"
        assert verdict.reason is None
        assert verdict.verdict == "confirmed"
        assert "12" in verdict.notes  # the real flow parsed the N synthetic events


class TestH2InvalidPayloadByContent:
    """R2: synthetic content violating known validations maps to
    ``invalid_payload`` via the real classifier, with the triggered
    validation identified."""

    @pytest.mark.parametrize(
        "fixture",
        [f for f in lab.load_h2_fixtures() if not f.get("control")],
        ids=lambda f: f["id"],
    )
    def test_invalid_fixture_maps_to_invalid_payload(self, fixture: dict) -> None:
        verdict = lab.run_h2_experiment(fixture)
        assert verdict.reason == "invalid_payload"
        assert verdict.verdict == "confirmed"
        # Which real validation fired is recorded and matches the fixture.
        assert fixture["validation"] in verdict.notes
        assert verdict.params["exception_type"] == fixture["exception_type"]

    def test_valid_control_fixture_not_mapped_to_invalid_payload(self) -> None:
        control = next(f for f in lab.load_h2_fixtures() if f.get("control"))
        verdict = lab.run_h2_experiment(control)
        assert verdict.reason is None
        assert verdict.verdict == "confirmed"
        assert verdict.params["exception_type"] is None


class TestVerdictArtifact:
    """R3: every experiment emits the full verdict schema; the runner
    consolidates ``verdicts.json`` with a deterministic outcome."""

    def test_every_verdict_has_complete_schema(self) -> None:
        verdicts = lab.run_experiments(
            h1_item_count=110,
            h1_deadline_seconds=1,
            h1_latency_per_item_ms=10,
            h1_control_item_count=10,
            h1_control_deadline_seconds=60,
            h1_control_latency_per_item_ms=10,
        )
        assert len(verdicts) >= 7  # H1 + H1 control + 5 invalid H2 + H2 control
        for verdict in verdicts:
            data = asdict(verdict)
            assert VERDICT_KEYS <= set(data)
            assert data["verdict"] in VERDICT_VALUES
            assert isinstance(data["params"], dict)
            assert data["reason"] in {None, "timeout", "invalid_payload"}

    def test_consolidated_verdicts_json_is_written_with_schema(self, tmp_path: Path) -> None:
        out = tmp_path / "verdicts.json"
        verdicts = lab.run_experiments(
            output_path=out,
            h1_item_count=110,
            h1_deadline_seconds=1,
            h1_latency_per_item_ms=10,
            h1_control_item_count=10,
            h1_control_deadline_seconds=60,
            h1_control_latency_per_item_ms=10,
        )
        assert out.exists()
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["synthetic_sentinel"] == lab.ARTIFACT_SENTINEL
        assert len(payload["verdicts"]) == len(verdicts)
        for item in payload["verdicts"]:
            assert VERDICT_KEYS <= set(item)
            assert item["verdict"] in VERDICT_VALUES

    def test_verdict_is_deterministic_given_params(self) -> None:
        first = lab.run_experiments(
            h1_item_count=110,
            h1_deadline_seconds=1,
            h1_latency_per_item_ms=10,
            h1_control_item_count=10,
            h1_control_deadline_seconds=60,
            h1_control_latency_per_item_ms=10,
        )
        second = lab.run_experiments(
            h1_item_count=110,
            h1_deadline_seconds=1,
            h1_latency_per_item_ms=10,
            h1_control_item_count=10,
            h1_control_deadline_seconds=60,
            h1_control_latency_per_item_ms=10,
        )
        stable = [(v.hypothesis, v.fixture, v.reason, v.verdict) for v in first]
        assert stable == [
            (v.hypothesis, v.fixture, v.reason, v.verdict) for v in second
        ]


class TestLabIsolation:
    """R4: fixtures synthetic; harness imports only real exercised points;
    no operational code imports the harness; no network/subprocess/browser."""

    def test_operational_code_never_imports_the_lab(self) -> None:
        offenders: list[str] = []
        for path in (REPO_ROOT / "apps").rglob("*.py"):
            if "fullsync_failure_lab" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        assert offenders == []

    def test_lab_imports_from_apps_are_restricted_to_exercised_points(self) -> None:
        source = LAB_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        allowed = {
            "apps.ingestion.extractors.errors",
            "apps.ingestion.extractors.persistent_evolution_pdf",
            "apps.ingestion.extractors.persistent_extraction_adapter",
            "apps.ingestion.run_lifecycle",
        }
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("apps"):
                    imported.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("apps"):
                        imported.add(alias.name)
        assert imported <= allowed

    def test_harness_source_has_no_network_subprocess_or_playwright(self) -> None:
        source = LAB_FILE.read_text(encoding="utf-8")
        for forbidden in (
            "import subprocess",
            "subprocess.",
            "import requests",
            "urllib",
            "sync_playwright",
            "playwright.sync_api",
            "import socket",
            "http.client",
        ):
            assert forbidden not in source

    def test_experiments_never_call_network_subprocess_or_playwright(self) -> None:
        with (
            mock.patch("subprocess.Popen", side_effect=AssertionError("no subprocess")),
            mock.patch("subprocess.run", side_effect=AssertionError("no subprocess")),
            mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network")),
            mock.patch(
                "playwright.sync_api.sync_playwright",
                side_effect=AssertionError("no playwright"),
            ),
        ):
            lab.run_experiments(
                h1_item_count=110,
                h1_deadline_seconds=1,
                h1_latency_per_item_ms=10,
                h1_control_item_count=10,
                h1_control_deadline_seconds=60,
                h1_control_latency_per_item_ms=10,
            )


class TestSyntheticFixtures:
    """R4: fixtures contain only synthetic data (sentinels; no production
    strings, no real HTML/PDF files)."""

    def test_h2_fixture_records_are_synthetic_only(self) -> None:
        payload = json.loads(
            (FIXTURES_DIR / "fullsync_synthetic_content.json").read_text(
                encoding="utf-8"
            )
        )
        assert payload["synthetic_sentinel"] == lab.H2_FILE_SENTINEL
        assert len(payload["fixtures"]) >= 6
        for fixture in payload["fixtures"]:
            blob = json.dumps(fixture, ensure_ascii=False).casefold()
            assert SENTINEL.casefold() in blob
            for token in FORBIDDEN_TOKENS:
                assert token not in blob

    def test_h1_report_template_is_synthetic_only(self) -> None:
        template = (
            FIXTURES_DIR / "fullsync_synthetic_report_block.txt"
        ).read_text(encoding="utf-8")
        assert SENTINEL in template
        assert "CRM 99999" in template
        lowered = template.casefold()
        for token in FORBIDDEN_TOKENS:
            assert token not in lowered

    def test_no_real_html_pdf_or_binary_files_in_lab_fixtures(self) -> None:
        for path in FIXTURES_DIR.iterdir():
            assert path.suffix in {".json", ".txt"}, path.name
