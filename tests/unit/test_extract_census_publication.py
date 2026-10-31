"""ECD-S2/S3: producer completion, publication and privacy of the census handoff.

These tests exercise the real production ``run`` loop with controlled browser
and source boundaries. Acquisition is a deterministic synthetic DOM read
(``read_sector_rows``); the handoff files, counters, retries and privacy are
real. Browser-level DOM behavior is verified by
``automation/lab/playwright_experiments/verify_census_dom.py``.

No hospital, network, credential or real patient data is used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

# The script mutates sys.path at import time; restore it like the existing
# script tests do so the rest of the suite keeps its import state.
_SYS_PATH_BEFORE_IMPORT = list(sys.path)
_SOURCE_SYSTEM_MODULE_BEFORE = sys.modules.get("source_system")

from automation.source_system.current_inpatients import extract_census as ec  # noqa: E402

sys.path[:] = _SYS_PATH_BEFORE_IMPORT
if _SOURCE_SYSTEM_MODULE_BEFORE is None:
    sys.modules.pop("source_system", None)

from tests.census_artifacts import SUMMARY_FILENAME  # noqa: E402


def _synthetic_dom_rows(
    *,
    index: int,
    omitted_rows: int,
    sentinel: str | None,
) -> dict[str, object]:
    record = sentinel or f"SYN-{index:04d}"
    name = sentinel or f"PACIENTE SINTETICO {index}"
    rows = [
        {
            "setor_codigo": f"{index:03d}",
            "setor": f"SETOR {index:03d}",
            "qrt_leito": f"LEITO{index:03d}A",
            "prontuario": record,
            "nome": name,
            "esp": "CLI",
            "dt_int": "01/02/2026 07:00",
            "tempo": 3,
            "idade": "40",
            "convenio": "",
            "dt_mvt": "02/02/2026 09:00",
            "alta": "",
            "origem": "",
        },
        {
            "setor_codigo": f"{index:03d}",
            "setor": f"SETOR {index:03d}",
            "qrt_leito": f"LEITO{index:03d}B",
            "prontuario": "",
            "nome": "DESOCUPADO",
            "esp": "",
            "dt_int": "",
            "tempo": None,
            "idade": "",
            "convenio": "",
            "dt_mvt": "",
            "alta": "",
            "origem": "",
        },
    ]
    return {
        "pacientes": rows,
        "rows_omitted": omitted_rows,
        "pages": 1,
        "source_total": len(rows) + omitted_rows,
        "page_size": 100,
    }


def _forbidden_spreadsheet(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("operational run must not export or parse a spreadsheet")



def _run_producer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    sectors: list[str],
    fail_on: str | None = None,
    raise_on: str | None = None,
    exception_text: str | None = None,
    max_setores: int = 0,
    empty_sectors: set[str] | None = None,
    omitted_rows: int = 0,
    sentinel: str | None = None,
    csv_only: bool = True,
    attempts_out: dict[str, int] | None = None,
    discovery_complete: bool = True,
) -> int | None:
    """Run the real producer loop with only acquisition edges controlled."""
    monkeypatch.setattr(ec, "DOWNLOADS_DIR", tmp_path)
    empty_sectors = empty_sectors or set()
    state: dict[str, object] = {"current": None, "attempts": {}}
    positions = {name: position for position, name in enumerate(sectors, start=1)}

    def select_setor(_frame, _page, setor: str) -> bool:
        attempts = state["attempts"]
        assert isinstance(attempts, dict)
        attempts[setor] = attempts.get(setor, 0) + 1
        if setor == raise_on:
            raise RuntimeError(exception_text or "raw browser failure")
        if setor == fail_on:
            return False
        state["current"] = setor
        return True

    def get_current_setor_info(_frame) -> dict[str, str]:
        current = str(state["current"])
        return {"codigo": f"{positions[current]:03d}", "nome": current}

    def result_state(_frame, arm: bool = False) -> dict[str, object]:
        del arm
        current = state["current"]
        empty = current in empty_sectors
        return {
            "has_patient_rows": not empty,
            "empty_message": empty,
            "tbody_exists": True,
            "row_count": 0 if empty else 3,
            "first_row_cell_count": 0 if empty else 13,
            "queue_empty": True,
            "loading_visible": False,
        }

    def read_rows(
        _frame, _page, *, setor_codigo, setor_nome
    ) -> dict[str, object]:
        current = str(state["current"])
        return _synthetic_dom_rows(
            index=positions[current],
            omitted_rows=omitted_rows,
            sentinel=sentinel,
        )

    def extract(_frame, _page, status=None) -> list[str]:
        if status is not None:
            status["complete"] = discovery_complete
        return sectors

    manager = MagicMock()
    playwright = MagicMock()
    manager.__enter__.return_value = playwright
    manager.__exit__.return_value = False

    with (
        patch.object(ec, "sync_playwright", return_value=manager),
        patch.object(ec, "bootstrap_legacy_session"),
        patch.object(ec, "fechar_dialogos_iniciais"),
        patch.object(ec, "click_censo_icon"),
        patch.object(ec, "get_censo_frame", return_value=MagicMock()),
        patch.object(ec, "wait_ajax_idle"),
        patch.object(ec, "extract_setores", side_effect=extract),
        patch.object(ec, "select_setor", side_effect=select_setor),
        patch.object(ec, "clear_setor"),
        patch.object(ec, "click_pesquisar", return_value=True),
        patch.object(ec, "census_result_state", side_effect=result_state),
        patch.object(
            ec,
            "wait_for_census_result_refresh",
            side_effect=lambda _frame, _page, _before, timeout_ms=0: result_state(
                _frame
            ),
        ),
        patch.object(
            ec,
            "get_current_setor_info",
            side_effect=get_current_setor_info,
        ),
        patch.object(ec, "read_sector_rows", side_effect=read_rows),
        patch.object(ec, "export_setor_xlsx", _forbidden_spreadsheet),
        patch.object(ec, "parse_setor_xlsx", _forbidden_spreadsheet),
    ):
        exit_code = ec.run(
            source_system_url="https://source.invalid/login",
            username="synthetic-user",
            password="synthetic-password",
            headless=True,
            max_setores=max_setores,
            pause_ms=0,
            csv_only=csv_only,
        )
    if attempts_out is not None:
        attempts_out.update(cast(dict[str, int], state["attempts"]))
    return exit_code


def _summary(tmp_path: Path) -> dict:
    return json.loads((tmp_path / SUMMARY_FILENAME).read_text(encoding="utf-8"))


def _sectors(count: int) -> list[str]:
    return [f"SETOR {index:03d}" for index in range(1, count + 1)]


def test_failure_after_forty_successes_does_not_publish_success_csv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exit_code = _run_producer(
        monkeypatch,
        tmp_path,
        sectors=_sectors(41),
        fail_on="SETOR 041",
    )

    assert exit_code == 1
    assert list(tmp_path.glob("censo-*.csv")) == []
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []
    summary = _summary(tmp_path)
    assert summary["summary_version"] == 1
    assert summary["sectors_discovered"] == 41
    assert summary["sectors_selected"] == 41
    assert summary["sectors_processed"] == 41
    assert summary["sectors_failed"] == 1
    assert summary["sectors_empty"] == 0
    assert summary["rows_emitted"] == 80
    assert summary["scope_complete"] is False
    assert summary["scope_limited"] is False


def test_exhausted_retry_is_counted_as_failure_and_attempts_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    attempts: dict[str, int] = {}
    exit_code = _run_producer(
        monkeypatch,
        tmp_path,
        sectors=_sectors(41),
        raise_on="SETOR 041",
        attempts_out=attempts,
    )

    assert exit_code == 1
    assert attempts["SETOR 041"] == 3
    assert list(tmp_path.glob("censo-*.csv")) == []
    summary = _summary(tmp_path)
    assert summary["sectors_failed"] == 1
    assert summary["scope_complete"] is False


def test_incomplete_discovery_never_publishes_an_operational_census(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exit_code = _run_producer(
        monkeypatch,
        tmp_path,
        sectors=_sectors(41),
        discovery_complete=False,
    )

    assert exit_code == 1
    assert list(tmp_path.glob("censo-*.csv")) == []
    summary = _summary(tmp_path)
    assert summary["sectors_discovered"] == 41
    assert summary["sectors_selected"] == 0
    assert summary["sectors_processed"] == 0
    assert summary["scope_complete"] is False


def test_successful_run_publishes_canonical_csv_and_aggregate_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exit_code = _run_producer(
        monkeypatch,
        tmp_path,
        sectors=_sectors(40),
    )

    assert exit_code == 0
    csv_files = list(tmp_path.glob("censo-*.csv"))
    assert len(csv_files) == 1
    csv_lines = csv_files[0].read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 81  # header + 40 occupied + 40 bed labels

    summary = _summary(tmp_path)
    assert summary == {
        "summary_version": 1,
        "sectors_discovered": 40,
        "sectors_selected": 40,
        "sectors_processed": 40,
        "sectors_empty": 0,
        "sectors_failed": 0,
        "rows_read": 80,
        "rows_omitted": 0,
        "rows_emitted": 80,
        "pages_processed": 40,
        "scope_limited": False,
        "scope_complete": True,
    }
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_valid_empty_sector_counts_as_processed_without_fabricated_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exit_code = _run_producer(
        monkeypatch,
        tmp_path,
        sectors=_sectors(41),
        empty_sectors={"SETOR 041"},
    )

    assert exit_code == 0
    summary = _summary(tmp_path)
    assert summary["sectors_processed"] == 41
    assert summary["sectors_empty"] == 1
    assert summary["sectors_failed"] == 0
    assert summary["rows_emitted"] == 80
    assert summary["scope_complete"] is True

    csv_lines = list(tmp_path.glob("censo-*.csv"))[0].read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(csv_lines) == 81


def test_omitted_rows_are_counted_separately_from_emitted_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exit_code = _run_producer(
        monkeypatch,
        tmp_path,
        sectors=_sectors(1),
        omitted_rows=2,
    )

    assert exit_code == 0
    summary = _summary(tmp_path)
    assert summary["rows_read"] == 4
    assert summary["rows_omitted"] == 2
    assert summary["rows_emitted"] == 2


def test_limited_diagnostic_scope_is_marked_and_not_operationally_complete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exit_code = _run_producer(
        monkeypatch,
        tmp_path,
        sectors=_sectors(41),
        max_setores=40,
    )

    assert exit_code == 0
    summary = _summary(tmp_path)
    assert summary["sectors_discovered"] == 41
    assert summary["sectors_selected"] == 40
    assert summary["scope_limited"] is True
    assert summary["scope_complete"] is True


def test_success_output_keeps_synthetic_patient_values_out_of_summary_and_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel = "SENTINEL-SYNTHETIC-PATIENT-42"
    exit_code = _run_producer(
        monkeypatch,
        tmp_path,
        sectors=_sectors(40),
        sentinel=sentinel,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    summary_text = (tmp_path / SUMMARY_FILENAME).read_text(encoding="utf-8")
    assert sentinel not in summary_text
    assert sentinel not in captured.out
    assert sentinel not in captured.err
    # The temporary transport is the only artifact allowed to carry row values.
    csv_text = list(tmp_path.glob("censo-*.csv"))[0].read_text(
        encoding="utf-8"
    )
    assert sentinel in csv_text


def test_raw_browser_exception_text_never_reaches_output_or_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel = "SENTINEL-RAW-BROWSER-ERROR-99"
    exit_code = _run_producer(
        monkeypatch,
        tmp_path,
        sectors=_sectors(41),
        raise_on="SETOR 041",
        exception_text=f"{sentinel} patient=SENTINEL-PATIENT",
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    combined = captured.out + captured.err
    assert sentinel not in combined
    assert "SENTINEL-PATIENT" not in combined
    summary_text = (tmp_path / SUMMARY_FILENAME).read_text(encoding="utf-8")
    assert sentinel not in summary_text
    assert "SENTINEL-PATIENT" not in summary_text
