"""ECD-S3 integration: real DOM browser transport -> command -> PostgreSQL.

The producer is the operational ``run`` with only true external browser edges
(login shell, census icon/frame and proxy resolution) controlled. The census
table, sector selection, tooltip association, pagination, CSV and version-1
summary are real. The real management command, parser, completeness validator
and transaction persist the produced artifacts in isolated PostgreSQL.

Only the acquisition subprocess transport is faked, because the browser has
already produced the actual handoff files. All data is synthetic and local.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.census.models import CensusSnapshot, PatientMovement
from apps.census.services import process_census_snapshot, upsert_patient_movements
from apps.ingestion.models import (
    CensusExecutionBatch,
    IngestionRun,
)
from apps.patients.models import Admission, Patient, StaleAdmissionCase
from automation.lab.playwright_experiments.census_dom_synthetic import (
    SyntheticCensusServer,
    generic_sector,
    make_sector,
)
from automation.source_system.current_inpatients import extract_census as ec
from tests.census_artifacts import SUMMARY_FILENAME


def _fast_sector(sector: dict) -> dict:
    """Keep the native long page applied immediately after the search."""
    sector["page_options"] = [100]
    sector["default_page_size"] = 100
    sector["tooltip_delay_ms"] = 40
    return sector


def _success_catalog() -> dict:
    sectors = [_fast_sector(generic_sector(index)) for index in range(1, 41)]
    sectors.append(
        make_sector("9 9", "ALA SEM PACIENTES", [], empty=True)
    )
    return {"sectors": sectors}


def _failure_catalog() -> dict:
    sectors = [_fast_sector(generic_sector(index)) for index in range(1, 41)]
    broken = generic_sector(41)
    broken["page_options"] = [10, 20]
    broken["default_page_size"] = 20
    sectors.append(broken)
    return {"sectors": sectors}


def _run_browser_producer(
    monkeypatch: pytest.MonkeyPatch,
    catalog: dict,
    output_dir: Path,
) -> int:
    requests: list[str] = []
    monkeypatch.setattr(ec, "DOWNLOADS_DIR", output_dir)
    for key in (
        "SOURCE_SYSTEM_URL",
        "SOURCE_SYSTEM_USERNAME",
        "SOURCE_SYSTEM_PASSWORD",
        "PLAYWRIGHT_PROXY_SERVER",
    ):
        monkeypatch.delenv(key, raising=False)

    def bootstrap(page, **_kwargs) -> None:
        page.on("request", lambda request: requests.append(request.url))
        page.goto(url)

    with SyntheticCensusServer(catalog) as server:
        url = server.url
        monkeypatch.setattr(ec, "bootstrap_legacy_session", bootstrap)
        monkeypatch.setattr(
            ec, "fechar_dialogos_iniciais", lambda _page: None
        )
        monkeypatch.setattr(ec, "click_censo_icon", lambda _page: None)
        monkeypatch.setattr(
            ec,
            "get_censo_frame",
            lambda page, timeout_ms=60_000: page.main_frame,
        )
        monkeypatch.setattr(ec, "get_playwright_proxy", lambda: None)
        exit_code = ec.run(
            source_system_url=url,
            username="synthetic-user",
            password="synthetic-password",
            headless=True,
            max_setores=0,
            pause_ms=0,
            csv_only=True,
        )
    assert requests
    assert all(request.startswith(url) for request in requests)
    return exit_code


def _run_command_on(
    directory: Path,
    *,
    returncode: int = 0,
    expect_exit: bool = False,
) -> IngestionRun:
    from unittest.mock import MagicMock, patch

    fake_result = MagicMock()
    fake_result.returncode = returncode
    fake_result.stderr = ""
    fake_tmp_ctx = MagicMock()
    fake_tmp_ctx.__enter__.return_value = str(directory)

    with (
        patch(
            "apps.census.management.commands.extract_census.run_subprocess",
            return_value=fake_result,
        ),
        patch("tempfile.TemporaryDirectory", return_value=fake_tmp_ctx),
    ):
        if expect_exit:
            with pytest.raises(SystemExit):
                call_command("extract_census")
        else:
            call_command("extract_census")

    return IngestionRun.objects.filter(intent="census_extraction").latest("pk")


def _counts() -> dict[str, int]:
    return {
        "snapshots": CensusSnapshot.objects.count(),
        "batches": CensusExecutionBatch.objects.count(),
        "patients": Patient.objects.count(),
        "admissions": Admission.objects.count(),
        "movements": PatientMovement.objects.count(),
        "stale_cases": StaleAdmissionCase.objects.count(),
        "queues": IngestionRun.objects.filter(
            intent__in=("admissions_only", "demographics_only")
        ).count(),
    }


@pytest.mark.django_db
def test_browser_dom_handoff_and_rejection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    success_dir = tmp_path / "success"
    success_dir.mkdir()
    assert (
        _run_browser_producer(monkeypatch, _success_catalog(), success_dir)
        == 0
    )
    csv_files = list(success_dir.glob("censo-*.csv"))
    assert len(csv_files) == 1
    assert (success_dir / SUMMARY_FILENAME).exists()

    run = _run_command_on(success_dir)
    assert run.status == "succeeded"

    snapshots = CensusSnapshot.objects.filter(ingestion_run=run)
    assert snapshots.count() == 80
    occupied = snapshots.exclude(prontuario="")
    beds = snapshots.filter(prontuario="")
    assert occupied.count() == 40
    assert beds.count() == 40

    sample = occupied.get(leito="LEITO01A")
    assert sample.source_admission_at is not None
    assert sample.source_movement_at is not None
    assert timezone.is_aware(sample.source_admission_at)
    assert sample.data_internacao == "05/02/2026"
    assert sample.data_movimentacao == "06/02/2026"

    bed = beds.get(leito="LEITO01B")
    assert bed.source_admission_at is None
    assert bed.source_movement_at is None
    assert bed.bed_status == "empty"

    # A newer census run exists while the older run is processed explicitly.
    newer = IngestionRun.objects.create(
        status="succeeded",
        intent="census_extraction",
        queued_at=timezone.now(),
        processing_started_at=timezone.now(),
        finished_at=timezone.now(),
    )
    CensusSnapshot.objects.bulk_create(
        [
            CensusSnapshot(
                captured_at=timezone.now(),
                ingestion_run=newer,
                setor="SETOR NOVO",
                setor_codigo="999",
                leito=f"NOVO-{index}",
                prontuario=f"NEW-{index}",
                nome=f"PACIENTE NOVO {index}",
                data_internacao="01/01/2026",
                data_movimentacao="01/01/2026",
                bed_status="occupied",
            )
            for index in range(1, 41)
        ]
    )

    result = process_census_snapshot(run_id=run.pk)

    assert result["rejected"] is False
    assert result["patients_total"] == 40
    assert result["runs_enqueued"] == 40
    assert Patient.objects.count() == 40
    assert not Patient.objects.filter(
        patient_source_key__startswith="NEW-"
    ).exists()
    assert not Patient.objects.filter(name="DESOCUPADO").exists()
    assert Admission.objects.count() == 0
    assert StaleAdmissionCase.objects.count() == 0

    # The concurrent newer run is removed after the isolation assertion; the
    # legacy movement helper consumes the latest captured census.
    CensusSnapshot.objects.filter(ingestion_run=newer).delete()
    newer.delete()

    first = upsert_patient_movements()
    second = upsert_patient_movements()
    assert first["movements_created"] == 40
    assert second["movements_created"] == 0
    movement = PatientMovement.objects.get(
        patient__patient_source_key="SYN-G001",
        sector="ALA SINTÉTICA 01",
    )
    assert movement.movement_date == date(2026, 2, 6)

    accepted_counts = _counts()
    accepted_snapshot_count = CensusSnapshot.objects.filter(
        ingestion_run=run
    ).count()

    failed_dir = tmp_path / "failed"
    failed_dir.mkdir()
    assert (
        _run_browser_producer(monkeypatch, _failure_catalog(), failed_dir)
        == 1
    )
    assert list(failed_dir.glob("censo-*.csv")) == []

    rejected = _run_command_on(failed_dir, returncode=0, expect_exit=True)

    assert rejected.status == "failed"
    assert CensusSnapshot.objects.filter(ingestion_run=rejected).count() == 0
    assert CensusSnapshot.objects.filter(
        ingestion_run=run
    ).count() == accepted_snapshot_count
    assert _counts() == accepted_counts
    assert (
        IngestionRun.objects.filter(
            intent="census_extraction", status="succeeded"
        )
        .latest("pk")
        .pk
        == run.pk
    )

    rejected_result = process_census_snapshot(run_id=rejected.pk)
    assert rejected_result["rejected"] is True
    assert rejected_result["batch_id"] is None
    assert _counts() == accepted_counts
