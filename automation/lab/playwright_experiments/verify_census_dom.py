#!/usr/bin/env python3
"""Bounded synthetic verification of DOM census acquisition.

Runs the operational collector (``automation/source_system/current_inpatients/
extract_census.py``) and its real DOM seams against a local synthetic census
UI. Only true external edges (legacy login/bootstrap, census shell/icon and
proxy resolution) are controlled; table reading, sector selection, tooltip
association, pagination, CSV/summary production and the completeness counters
are the production implementations.

``--synthetic`` never reads ``.env``, hospital credentials or an external
source. Output is aggregate-only: counters, booleans, fixed reason codes and
timings. No row values, timestamps, identifiers or HTML are printed.

Database composition (command/parser/PostgreSQL) is proven separately by the
integration suite; this script is browser evidence only.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from automation.lab.playwright_experiments.census_dom_synthetic import (  # noqa: E402
    SyntheticCensusServer,
    build_failing_catalog,
    build_full_catalog,
    make_row,
    make_sector,
)

SUMMARY_FILENAME = "censo-extraction-summary.json"


def _isolate_environment() -> None:
    """Remove any real-source configuration before importing/starting."""
    import os

    for key in list(os.environ):
        if key.startswith("SOURCE_SYSTEM_") or key.startswith(
            "PLAYWRIGHT_PROXY"
        ):
            os.environ.pop(key, None)
    for key in ("DJANGO_SETTINGS_MODULE", "DEBUG", "PWDEBUG", "DEBUG_FILE"):
        os.environ.pop(key, None)


def _load_census() -> Any:
    from automation.source_system.current_inpatients import extract_census

    return extract_census


def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("spreadsheet acquisition must not run")


def _external_edges(
    ec: Any,
    url: str,
    requests: list[str],
) -> list[Any]:
    """Control only the true external shell; DOM logic stays production."""

    def bootstrap(page: Any, **_kwargs: Any) -> None:
        def record(request: Any) -> None:
            requests.append(request.url)

        page.on("request", record)
        page.goto(url)

    return [
        patch.object(ec, "bootstrap_legacy_session", bootstrap),
        patch.object(ec, "fechar_dialogos_iniciais", lambda _page: None),
        patch.object(ec, "click_censo_icon", lambda _page: None),
        patch.object(
            ec,
            "get_censo_frame",
            lambda page, timeout_ms=60_000: page.main_frame,
        ),
        patch.object(ec, "get_playwright_proxy", lambda: None),
    ]


def _run_operational(
    ec: Any,
    catalog: dict[str, Any],
    *,
    max_setores: int = 0,
    expected_success: bool,
) -> dict[str, Any]:
    requests: list[str] = []
    with (
        SyntheticCensusServer(catalog) as server,
        tempfile.TemporaryDirectory() as output_dir,
        patch.object(ec, "DOWNLOADS_DIR", Path(output_dir)),
        patch.object(ec, "export_setor_xlsx", _forbidden),
        patch.object(ec, "parse_setor_xlsx", _forbidden),
        patch.object(ec, "_click_export_button", _forbidden),
        patch.object(ec, "_click_xls_tudo", _forbidden),
    ):
        started = time.monotonic()
        with ExitStack() as stack:
            for edge in _external_edges(ec, server.url, requests):
                stack.enter_context(edge)
            exit_code = ec.run(
                source_system_url=server.url,
                username="synthetic-user",
                password="synthetic-password",
                headless=True,
                max_setores=max_setores,
                pause_ms=0,
                csv_only=True,
            )
        elapsed = round(time.monotonic() - started, 3)
        output = Path(output_dir)
        csv_files = sorted(output.glob("censo-*.csv"))
        summary_path = output / SUMMARY_FILENAME
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8"))
            if summary_path.exists()
            else None
        )
        artifacts = sorted(
            path.name for path in output.iterdir() if path.is_file()
        )
        csv_facts = _csv_facts(csv_files[0]) if len(csv_files) == 1 else None
        external_requests = [
            url for url in requests if not url.startswith(server.url)
        ]
    return {
        "exit_code": exit_code,
        "elapsed_seconds": elapsed,
        "csv_files": len(csv_files),
        "csv_facts": csv_facts,
        "summary": summary,
        "artifacts": artifacts,
        "external_requests": len(external_requests),
        "expected_success": expected_success,
    }


def _csv_facts(path: Path) -> dict[str, int]:
    """Aggregate-only facts about one produced transport CSV."""
    rows = _read_csv(path)
    positions: dict[tuple[str, ...], int] = {}
    for row in rows:
        key = (
            row.get("qrt_leito", ""),
            row.get("prontuario", ""),
            row.get("dt_int", ""),
            row.get("dt_mvt", ""),
        )
        positions[key] = positions.get(key, 0) + 1
    return {
        "rows": len(rows),
        "distinct_sectors": len(
            {row.get("setor", "") for row in rows if row.get("setor")}
        ),
        "bed_label_rows": sum(
            1 for row in rows if not (row.get("prontuario") or "").strip()
        ),
        "duplicate_position_rows": sum(
            count - 1 for count in positions.values() if count > 1
        ),
        "date_values_without_hour": sum(
            1
            for row in rows
            for field in ("dt_int", "dt_mvt")
            if (row.get(field) or "").strip()
            and ":" not in (row.get(field) or "")
        ),
        "both_timestamp_rows": sum(
            1
            for row in rows
            if ":" in (row.get("dt_int") or "")
            and ":" in (row.get("dt_mvt") or "")
        ),
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@contextlib.contextmanager
def _open_page(pw: Any, catalog: dict[str, Any]) -> Any:
    """Open one local synthetic census page; no external navigation."""
    manager = SyntheticCensusServer(catalog)
    manager.__enter__()
    browser = pw.chromium.launch(headless=True)
    try:
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.goto(manager.url)
        yield page
    finally:
        browser.close()
        manager.__exit__(None, None, None)


def _select_and_search(
    ec: Any, frame: Any, page: Any, label: str
) -> None:
    if not ec.select_setor(frame, page, label):
        raise RuntimeError("synthetic sector selection failed")
    info = ec.get_current_setor_info(frame)
    ec._confirm_selected_setor(label, info)
    previous = ec.census_result_state(frame, arm=True)
    if not ec.click_pesquisar(frame):
        raise RuntimeError("synthetic search failed")
    ec.wait_for_census_result_refresh(
        frame, page, previous, timeout_ms=30_000
    )


def _fixture_headers() -> list[str]:
    return [
        "Qrt/Leito",
        "Prontuário",
        "Nome/Situação",
        "Idade",
        "Dt Int",
        "Esp",
        "Médico",
        "Dt Mvt",
        "Alta",
        "Origem",
        "Tempo",
        "Convênio",
        "Transferência",
    ]


def _write_golden_workbook(
    path: Path, rows: list[dict[str, Any]]
) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(_fixture_headers())
    for row in rows:
        sheet.append(
            [
                row["leito"],
                row["prontuario"],
                row["nome"],
                row["idade"],
                row["dt_int"],
                row["esp"],
                "",
                row["dt_mvt"],
                row["alta"],
                row["origem"],
                row["tempo"],
                row["convenio"],
                "",
            ]
        )
    workbook.save(path)
    workbook.close()


def _normalize(field: str, value: Any) -> str:
    text = "" if value is None else " ".join(str(value).split())
    if field == "prontuario":
        return text.replace(".", "").replace("/", "")
    if field in {"idade", "tempo"} and text.endswith(".0"):
        return text[:-2]
    if field == "alta" and text in {"0", "0.0"}:
        return ""
    return text


def _date_matches(displayed: str, source_value: str) -> bool:
    """Compare a displayed date with the date component of a source value."""
    if not displayed:
        return not source_value
    return bool(source_value) and source_value.startswith(displayed)


def scenario_dom_only_run(ec: Any, pw: Any) -> dict[str, Any]:
    """R1: the operational run completes with no export surface."""
    catalog = {
        "sectors": [
            make_sector(
                "1 1",
                "ALA UM",
                [
                    make_row(
                        "LEITO-UM-A",
                        "SYN-R1-1",
                        "PACIENTE SINTÉTICO R1 A",
                        dt_int="01/02",
                        int_tip="01/02/2026 08:00",
                        dt_mvt="02/02",
                        mvt_tip="02/02/2026 09:00",
                    ),
                    make_row(
                        "LEITO-UM-B",
                        "",
                        "DESOCUPADO",
                        idade="",
                        tempo="",
                        convenio="",
                        dt_int="",
                        int_tip=None,
                        dt_mvt="",
                        mvt_tip=None,
                    ),
                ],
            ),
            make_sector(
                "1 2",
                "ALA DOIS",
                [
                    make_row(
                        "LEITO-DOIS-A",
                        "SYN-R1-2",
                        "PACIENTE SINTÉTICO R1 B",
                        dt_int="03/02",
                        int_tip="03/02/2026 10:15",
                        dt_mvt="04/02",
                        mvt_tip="04/02/2026 11:45",
                    )
                ],
            ),
        ]
    }
    result = _run_operational(
        ec, catalog, expected_success=True
    )
    artifacts = result["artifacts"]
    csv_artifacts = [
        name for name in artifacts if name.startswith("censo-") and name.endswith(".csv")
    ]
    ok = (
        result["exit_code"] == 0
        and result["csv_files"] == 1
        and len(csv_artifacts) == 1
        and SUMMARY_FILENAME in artifacts
        and len(artifacts) == 2
        and result["summary"] is not None
        and result["summary"]["scope_complete"] is True
        and result["external_requests"] == 0
    )
    return {
        "ok": ok,
        **{key: result[key] for key in (
            "exit_code",
            "csv_files",
            "elapsed_seconds",
            "external_requests",
        )},
        "summary": result["summary"],
        "artifacts": result["artifacts"],
    }


def scenario_full_catalog(ec: Any, pw: Any) -> dict[str, Any]:
    """R1/R2/R5/R6: full 43-sector catalog through the real run."""
    catalog = build_full_catalog()
    result = _run_operational(ec, catalog, expected_success=True)
    summary = result["summary"] or {}
    expected = {
        "summary_version": 1,
        "sectors_discovered": 43,
        "sectors_selected": 43,
        "sectors_processed": 43,
        "sectors_empty": 1,
        "sectors_failed": 0,
        "rows_read": 226,
        "rows_omitted": 1,
        "rows_emitted": 225,
        "pages_processed": 43,
        "scope_limited": False,
        "scope_complete": True,
    }
    facts = result["csv_facts"] or {}
    ok = (
        result["exit_code"] == 0
        and result["csv_files"] == 1
        and summary == expected
        and facts.get("rows") == 225
        and facts.get("distinct_sectors") == 42
        and facts.get("bed_label_rows") == 41
        and facts.get("duplicate_position_rows") == 2
        and facts.get("date_values_without_hour") == 0
        and result["external_requests"] == 0
    )
    return {
        "ok": ok,
        "exit_code": result["exit_code"],
        "csv_files": result["csv_files"],
        "elapsed_seconds": result["elapsed_seconds"],
        "external_requests": result["external_requests"],
        "summary": summary,
        "expected_summary": expected,
        "csv_facts": facts,
    }


def scenario_failure_after_forty(ec: Any, pw: Any) -> dict[str, Any]:
    """R6: a DOM sector failure after 40 successes never publishes a census."""
    catalog = build_failing_catalog(40)
    result = _run_operational(ec, catalog, expected_success=False)
    summary = result["summary"] or {}
    ok = (
        result["exit_code"] == 1
        and result["csv_files"] == 0
        and summary.get("sectors_discovered") == 41
        and summary.get("sectors_selected") == 41
        and summary.get("sectors_processed") == 41
        and summary.get("sectors_failed") == 1
        and summary.get("rows_emitted") == 80
        and summary.get("scope_complete") is False
        and result["external_requests"] == 0
    )
    return {
        "ok": ok,
        "exit_code": result["exit_code"],
        "csv_files": result["csv_files"],
        "elapsed_seconds": result["elapsed_seconds"],
        "external_requests": result["external_requests"],
        "summary": summary,
    }


def scenario_selection(ec: Any, pw: Any) -> dict[str, Any]:
    """R3: native accent, shared code, absent, ambiguous and wrong selection."""
    pediatric = make_sector(
        "4 8",
        "4C - CLINICA MÉDICA PEDIÁTRICA - HGRS",
        [make_row("P1", "SYN-SEL-1", "PACIENTE SINTÉTICO SEL 1")],
    )
    north = make_sector(
        "5 1", "ALA NORTE", [make_row("N1", "SYN-SEL-2", "P SINTÉTICO N")]
    )
    south = make_sector(
        "5 1", "ALA SUL", [make_row("S1", "SYN-SEL-3", "P SINTÉTICO S")]
    )
    shared_a = make_sector(
        "10 1",
        "SALA COMPARTILHADA",
        [make_row("C1", "SYN-SEL-4", "P SINTÉTICO C1")],
    )
    shared_b = make_sector(
        "10 2",
        "SALA COMPARTILHADA",
        [make_row("C2", "SYN-SEL-5", "P SINTÉTICO C2")],
    )
    wrong = make_sector(
        "7 7",
        "ALA ERRADA",
        [make_row("W1", "SYN-SEL-6", "P SINTÉTICO W")],
        click_selects="5 1 - ALA NORTE",
    )
    catalog = {
        "sectors": [
            pediatric,
            north,
            south,
            shared_a,
            shared_b,
            wrong,
        ]
    }
    checks: dict[str, bool] = {}
    with _open_page(pw, catalog) as page:
        frame = page.main_frame
        checks["accented_selected"] = ec.select_setor(
            frame, page, pediatric["label"]
        )
        info = ec.get_current_setor_info(frame)
        checks["accented_confirmed"] = (
            info.get("codigo") == "4 8"
            and "PEDIÁTRICA" in (info.get("nome") or "")
        )
        checks["shared_north"] = ec.select_setor(
            frame, page, north["label"]
        )
        north_info = ec.get_current_setor_info(frame)
        checks["shared_south"] = ec.select_setor(
            frame, page, south["label"]
        )
        south_info = ec.get_current_setor_info(frame)
        checks["shared_codes_distinct"] = (
            north_info.get("codigo") == "5 1"
            and south_info.get("codigo") == "5 1"
            and north_info.get("nome") != south_info.get("nome")
        )
        checks["absent_rejected"] = not ec.select_setor(
            frame, page, "99 9 - ALA INEXISTENTE"
        )
        checks["ambiguous_rejected"] = not ec.select_setor(
            frame, page, "SALA COMPARTILHADA"
        )
        checks["wrong_click_selected"] = ec.select_setor(
            frame, page, wrong["label"]
        )
        wrong_info = ec.get_current_setor_info(frame)
        try:
            ec._confirm_selected_setor(wrong["label"], wrong_info)
            checks["wrong_click_rejected"] = False
        except ec.CensusExtractionError as exc:
            checks["wrong_click_rejected"] = (
                exc.reason == "sector_selection_mismatch"
            )
    return {"ok": all(checks.values()), "checks": checks}


def scenario_header_variants(ec: Any, pw: Any) -> dict[str, Any]:
    """R3: hidden first Alta/Origem variants and reordered unrelated columns."""
    sector = make_sector(
        "3 3",
        "ALA CABEÇALHOS",
        [
            make_row(
                "CAB-1",
                "SYN-CAB-1",
                "PACIENTE SINTÉTICO CAB 1",
                esp="ESPECIALIDADE A",
                convenio="CONVENIO A",
                idade="2m12d",
                dt_int="01/02",
                int_tip="01/02/2026 08:15",
                dt_mvt="02/02",
                mvt_tip="02/02/2026 10:30",
                alta="1",
                alta_view="ALTA APRESENTACAO",
                origem="ORIGEM EXPORT",
                origem_view="ORIGEM APRESENTACAO",
            )
        ],
        header_variant="reordered",
    )
    catalog = {"sectors": [sector]}
    detail: dict[str, Any] = {}
    with _open_page(pw, catalog) as page:
        frame = page.main_frame
        _select_and_search(ec, frame, page, sector["label"])
        rows = ec.read_sector_rows(
            frame,
            page,
            setor_codigo=sector["code"],
            setor_nome=sector["description"],
        )
    patient = rows["pacientes"][0] if rows["pacientes"] else {}
    detail = {
        "rows": len(rows["pacientes"]),
        "alta_export_variant": patient.get("alta"),
        "origem_export_variant": patient.get("origem"),
        "esp": patient.get("esp"),
        "convenio": patient.get("convenio"),
        "idade": patient.get("idade"),
        "admission_has_time": ":" in (patient.get("dt_int") or ""),
        "movement_has_time": ":" in (patient.get("dt_mvt") or ""),
        "pages": rows["pages"],
    }
    ok = (
        detail["rows"] == 1
        and detail["alta_export_variant"] == "1"
        and detail["origem_export_variant"] == "ORIGEM EXPORT"
        and detail["esp"] == "ESPECIALIDADE A"
        and detail["convenio"] == "CONVENIO A"
        and detail["idade"] == "2m12d"
        and detail["admission_has_time"]
        and detail["movement_has_time"]
    )
    return {"ok": ok, "detail": detail}


def _tooltip_catalog() -> dict[str, Any]:
    correct = make_sector(
        "20 1",
        "TOOLTIP CORRETO",
        [
            make_row(
                "T-1",
                "SYN-T-1",
                "PACIENTE SINTÉTICO T1",
                dt_int="01/02",
                int_tip="01/02/2026 08:15",
                dt_mvt="02/02",
                mvt_tip="02/02/2026 10:30",
            )
        ],
    )
    empty = make_sector(
        "20 2",
        "TOOLTIP VAZIO",
        [
            make_row(
                "T-2",
                "SYN-T-2",
                "PACIENTE SINTÉTICO T2",
                dt_int="",
                int_tip=None,
                dt_mvt="",
                mvt_tip=None,
            )
        ],
    )
    attribute = make_sector(
        "20 3",
        "TOOLTIP ATRIBUTO",
        [
            make_row(
                "T-3",
                "SYN-T-3",
                "PACIENTE SINTÉTICO T3",
                dt_int="01/02",
                int_tip=None,
                int_attr="01/02/2026 07:00",
                dt_mvt="02/02",
                mvt_tip=None,
                mvt_attr="02/02/2026 09:00",
            )
        ],
    )
    delayed = make_sector(
        "20 4",
        "TOOLTIP ATRAZADO",
        [
            make_row(
                "T-4",
                "SYN-T-4",
                "PACIENTE SINTÉTICO T4",
                dt_int="01/02",
                int_tip="01/02/2026 06:00",
                dt_mvt="02/02",
                mvt_tip="02/02/2026 07:00",
            )
        ],
        tooltip_delay_ms=2500,
    )
    ambiguous = make_sector(
        "20 5",
        "TOOLTIP AMBIGUO",
        [
            make_row(
                "T-5",
                "SYN-T-5",
                "PACIENTE SINTÉTICO T5",
                dt_int="01/02",
                int_tip="01/02/2026 08:15",
                int_extra=["01/02/2026 09:15"],
                dt_mvt="02/02",
                mvt_tip="02/02/2026 10:30",
            )
        ],
    )
    invalid = make_sector(
        "20 6",
        "TOOLTIP INVALIDO",
        [
            make_row(
                "T-6",
                "SYN-T-6",
                "PACIENTE SINTÉTICO T6",
                dt_int="01/02",
                int_tip="31/02/2026 08:15",
                dt_mvt="02/02",
                mvt_tip="02/02/2026 10:30",
            )
        ],
    )
    mismatched = make_sector(
        "20 7",
        "TOOLTIP DESENCONTRADO",
        [
            make_row(
                "T-7",
                "SYN-T-7",
                "PACIENTE SINTÉTICO T7",
                dt_int="01/02",
                int_tip="02/02/2026 08:15",
                dt_mvt="02/02",
                mvt_tip="02/02/2026 10:30",
            )
        ],
    )
    missing = make_sector(
        "20 8",
        "TOOLTIP AUSENTE",
        [
            make_row(
                "T-8",
                "SYN-T-8",
                "PACIENTE SINTÉTICO T8",
                dt_int="01/02",
                int_tip=None,
                dt_mvt="02/02",
                mvt_tip="02/02/2026 10:30",
            )
        ],
        global_tip="01/02/2026 23:59",
    )
    foreign = make_sector(
        "20 9",
        "TOOLTIP OUTRA LINHA",
        [
            make_row(
                "T-9A",
                "SYN-T-9A",
                "PACIENTE SINTÉTICO T9A",
                dt_int="01/02",
                int_tip="01/02/2026 01:11",
                dt_mvt="02/02",
                mvt_tip="02/02/2026 02:22",
            ),
            make_row(
                "T-9B",
                "SYN-T-9B",
                "PACIENTE SINTÉTICO T9B",
                dt_int="01/02",
                int_tip="01/02/2026 03:33",
                dt_mvt="02/02",
                mvt_tip="02/02/2026 04:44",
            ),
        ],
        global_tip="05/05/2026 05:55",
    )
    return {
        "sectors": [
            correct,
            empty,
            attribute,
            delayed,
            ambiguous,
            invalid,
            mismatched,
            missing,
            foreign,
        ]
    }


def scenario_tooltips(ec: Any, pw: Any) -> dict[str, Any]:
    """R4: cell-associated tooltips, delays, empties and explicit failures."""
    catalog = _tooltip_catalog()
    results: dict[str, Any] = {}
    with _open_page(pw, catalog) as page:
        frame = page.main_frame
        for sector in catalog["sectors"]:
            name = sector["description"]
            _select_and_search(ec, frame, page, sector["label"])
            if sector["code"] in {"20 5", "20 6", "20 7", "20 8"}:
                try:
                    ec.read_sector_rows(
                        frame,
                        page,
                        setor_codigo=sector["code"],
                        setor_nome=sector["description"],
                    )
                    results[name] = {"ok": False, "reason": "accepted"}
                except ec.CensusExtractionError as exc:
                    results[name] = {"ok": True, "reason": exc.reason}
            else:
                started = time.monotonic()
                rows = ec.read_sector_rows(
                    frame,
                    page,
                    setor_codigo=sector["code"],
                    setor_nome=sector["description"],
                )
                patients = rows["pacientes"]
                if sector["code"] == "20 2":
                    results[name] = {
                        "ok": len(patients) == 1
                        and patients[0]["dt_int"] == ""
                        and patients[0]["dt_mvt"] == "",
                        "reason": "empty_preserved",
                    }
                elif sector["code"] == "20 3":
                    results[name] = {
                        "ok": bool(patients)
                        and patients[0]["dt_int"] == "01/02/2026 07:00"
                        and patients[0]["dt_mvt"] == "02/02/2026 09:00",
                        "reason": "attribute_associated",
                    }
                elif sector["code"] == "20 4":
                    results[name] = {
                        "ok": bool(patients)
                        and patients[0]["dt_int"] == "01/02/2026 06:00"
                        and round(time.monotonic() - started, 3) >= 2.0,
                        "reason": "delayed_initialization",
                    }
                elif sector["code"] == "20 9":
                    results[name] = {
                        "ok": len(patients) == 2
                        and patients[0]["dt_int"] == "01/02/2026 01:11"
                        and patients[1]["dt_int"] == "01/02/2026 03:33",
                        "reason": "same_cell_only",
                    }
                else:
                    results[name] = {
                        "ok": bool(patients)
                        and ":" in (patients[0]["dt_int"] or "")
                        and ":" in (patients[0]["dt_mvt"] or ""),
                        "reason": "both_timestamps",
                    }
    expected_reasons = {
        "TOOLTIP AMBIGUO": "tooltip_ambiguous",
        "TOOLTIP INVALIDO": "tooltip_invalid",
        "TOOLTIP DESENCONTRADO": "tooltip_date_mismatch",
        "TOOLTIP AUSENTE": "tooltip_not_ready",
    }
    for name, reason in expected_reasons.items():
        entry = results.get(name, {})
        entry["ok"] = entry.get("ok") and entry.get("reason") == reason
        entry["expected_reason"] = reason
    return {"ok": all(entry.get("ok") for entry in results.values()), "scenarios": results}


def _pagination_catalog() -> dict[str, Any]:
    def numbered(count: int, code: str) -> list[dict[str, Any]]:
        return [
            make_row(
                f"{code}-{index:03d}",
                f"SYN{code}{index:03d}",
                f"PACIENTE SINTÉTICO {code} {index}",
            )
            for index in range(1, count + 1)
        ]

    rows_45 = numbered(45, "P45")
    rows_101 = numbered(101, "P101")
    # The last physical row repeats the second one across the page boundary and
    # one earlier row has both identities empty (omitted, counted).
    rows_101.insert(50, make_row(
        "P101-OMIT", "", "", esp="", idade="", tempo="", convenio="",
        dt_int="", int_tip=None, dt_mvt="", mvt_tip=None,
    ))
    while len(rows_101) > 101:
        rows_101.pop()
    rows_101[-1] = dict(rows_101[1])
    long_rows = numbered(5100, "PLONG")
    return {
        "sectors": [
            make_sector("30 1", "PAGINA 45", rows_45, page_options=(20, 100)),
            make_sector("30 2", "PAGINA 101", rows_101, page_options=(20, 100)),
            make_sector(
                "30 3",
                "PAGINA SEM OPCAO",
                numbered(5, "PNO"),
                page_options=(10, 20),
            ),
            make_sector(
                "30 4",
                "PAGINA REPETE",
                numbered(150, "PREP"),
                page_options=(100,),
                next_mode="repeat",
            ),
            make_sector(
                "30 5",
                "PAGINA SEM TERMINAL",
                numbered(150, "PTERM"),
                page_options=(100,),
                next_mode="missing",
            ),
            make_sector(
                "30 6",
                "PAGINA SEM TOTAL",
                numbered(45, "PTOT"),
                page_options=(100,),
                total_mode="absent",
            ),
            make_sector(
                "30 7",
                "PAGINA TOTAL ERRADO",
                numbered(45, "PBAD"),
                page_options=(100,),
                total_mode="override",
                total_override=46,
            ),
            make_sector(
                "30 8",
                "PAGINA LIMITE",
                long_rows,
                page_options=(100,),
            ),
        ]
    }


def scenario_pagination(ec: Any, pw: Any) -> dict[str, Any]:
    """R5: long page, multiple pages, totals and bounded failure modes."""
    catalog = _pagination_catalog()
    results: dict[str, Any] = {}
    with _open_page(pw, catalog) as page:
        frame = page.main_frame
        expected_errors = {
            "PAGINA SEM OPCAO": "page_size_unsupported",
            "PAGINA REPETE": "pagination_no_progress",
            "PAGINA SEM TERMINAL": "pagination_state_unknown",
            "PAGINA TOTAL ERRADO": "source_total_mismatch",
            "PAGINA LIMITE": "pagination_limit",
        }
        for sector in catalog["sectors"]:
            name = sector["description"]
            _select_and_search(ec, frame, page, sector["label"])
            started = time.monotonic()
            if name in expected_errors:
                try:
                    ec.read_sector_rows(
                        frame,
                        page,
                        setor_codigo=sector["code"],
                        setor_nome=sector["description"],
                    )
                    results[name] = {"ok": False, "reason": "accepted"}
                except ec.CensusExtractionError as exc:
                    results[name] = {
                        "ok": exc.reason == expected_errors[name],
                        "reason": exc.reason,
                        "expected_reason": expected_errors[name],
                        "seconds": round(time.monotonic() - started, 3),
                    }
            else:
                rows = ec.read_sector_rows(
                    frame,
                    page,
                    setor_codigo=sector["code"],
                    setor_nome=sector["description"],
                )
                if name == "PAGINA 45":
                    ok = len(rows["pacientes"]) == 45 and rows["pages"] == 1
                    detail = {
                        "rows": len(rows["pacientes"]),
                        "pages": rows["pages"],
                    }
                elif name == "PAGINA 101":
                    ok = (
                        len(rows["pacientes"]) == 100
                        and rows["rows_omitted"] == 1
                        and rows["pages"] == 2
                    )
                    detail = {
                        "rows": len(rows["pacientes"]),
                        "omitted": rows["rows_omitted"],
                        "pages": rows["pages"],
                    }
                else:  # PAGINA SEM TOTAL
                    ok = len(rows["pacientes"]) == 45 and rows["pages"] == 1
                    detail = {
                        "rows": len(rows["pacientes"]),
                        "pages": rows["pages"],
                        "source_total_available": rows["source_total"]
                        is not None,
                    }
                results[name] = {
                    "ok": ok,
                    "reason": "completed",
                    "seconds": round(time.monotonic() - started, 3),
                    **detail,
                }
    return {"ok": all(entry["ok"] for entry in results.values()), "scenarios": results}


def scenario_xlsx_reference_parity(ec: Any, pw: Any) -> dict[str, Any]:
    """R2: DOM rows match the real XLSX parser reference without its hours."""
    source_rows = [
        make_row(
            "PAR-1",
            "SYN-PAR-1",
            "PACIENTE SINTÉTICO PAR 1",
            esp="CLÍNICA",
            idade="43",
            tempo=5,
            convenio="SUS",
            dt_int="01/02",
            int_tip="01/02/2026 08:15",
            dt_mvt="02/02",
            mvt_tip="02/02/2026 10:30",
            alta="1",
            origem="ORIGEM",
        ),
        make_row(
            "PAR-2",
            "",
            "RESERVA",
            esp="",
            idade="",
            tempo="",
            convenio="",
            dt_int="",
            int_tip=None,
            dt_mvt="03/02",
            mvt_tip="03/02/2026 12:00",
        ),
        make_row(
            "PAR-3",
            "SYN-PAR-3",
            "PACIENTE SINTÉTICO PAR 3",
            idade="2m12d",
            dt_int="",
            int_tip=None,
            dt_mvt="04/02",
            mvt_tip="04/02/2026 13:30",
        ),
    ]
    sector = make_sector("40 1", "ALA PARIDADE", source_rows)
    catalog = {"sectors": [sector]}
    with _open_page(pw, catalog) as page:
        frame = page.main_frame
        _select_and_search(ec, frame, page, sector["label"])
        dom = ec.read_sector_rows(
            frame,
            page,
            setor_codigo=sector["code"],
            setor_nome=sector["description"],
        )
    with tempfile.TemporaryDirectory() as directory:
        workbook_path = Path(directory) / "golden.xlsx"
        _write_golden_workbook(workbook_path, source_rows)
        parsed = ec.parse_setor_xlsx(
            workbook_path, sector["code"], sector["description"]
        )
    hours_in_workbook = sum(
        1
        for row in parsed
        for field in ("dt_int", "dt_mvt")
        if ":" in (row.get(field) or "")
    )
    mismatches: dict[str, int] = {}
    dates_mismatched = 0
    for index, (dom_row, xlsx_row) in enumerate(
        zip(dom["pacientes"], parsed, strict=True)
    ):
        for field in (
            "qrt_leito",
            "prontuario",
            "nome",
            "esp",
            "tempo",
            "idade",
            "convenio",
            "alta",
            "origem",
        ):
            if _normalize(field, dom_row.get(field)) != _normalize(
                field, xlsx_row.get(field)
            ):
                mismatches[field] = mismatches.get(field, 0) + 1
        for field in ("dt_int", "dt_mvt"):
            displayed = source_rows[index][field]
            if not _date_matches(displayed, dom_row.get(field) or ""):
                dates_mismatched += 1
    ok = (
        len(dom["pacientes"]) == 3
        and len(parsed) == 3
        and not mismatches
        and dates_mismatched == 0
        and hours_in_workbook == 0
        and dom["rows_omitted"] == 0
    )
    return {
        "ok": ok,
        "rows": len(dom["pacientes"]),
        "field_mismatches": mismatches,
        "dates_mismatched": dates_mismatched,
        "xlsx_hour_values": hours_in_workbook,
        "dom_rows_with_hours": sum(
            1
            for row in dom["pacientes"]
            for field in ("dt_int", "dt_mvt")
            if ":" in (row.get(field) or "")
        ),
    }


SCENARIOS: dict[str, Callable[[Any, Any], dict[str, Any]]] = {
    "dom_only_run": scenario_dom_only_run,
    "full_catalog": scenario_full_catalog,
    "failure_after_forty": scenario_failure_after_forty,
    "selection": scenario_selection,
    "header_variants": scenario_header_variants,
    "tooltips": scenario_tooltips,
    "pagination": scenario_pagination,
    "xlsx_reference_parity": scenario_xlsx_reference_parity,
}

# These scenarios call ``ec.run``, which owns its own sync Playwright context.
RUN_SCENARIOS = frozenset(
    {"dom_only_run", "full_catalog", "failure_after_forty"}
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Required: run the local synthetic browser scenarios",
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=sorted(SCENARIOS),
        default=None,
        help="Run only the named scenario (repeatable; default: all)",
    )
    args = parser.parse_args()
    if not args.synthetic:
        parser.error("--synthetic is required; no external source mode exists")

    _isolate_environment()
    ec = _load_census()
    selected = args.only or list(SCENARIOS)
    results: list[dict[str, Any]] = []

    for name in selected:
        started = time.monotonic()
        try:
            if name in RUN_SCENARIOS:
                outcome = SCENARIOS[name](ec, None)
            else:
                from playwright.sync_api import sync_playwright

                with sync_playwright() as active_pw:
                    outcome = SCENARIOS[name](ec, active_pw)
        except Exception as exc:  # noqa: BLE001 - fixed safe diagnostics
            reason = getattr(exc, "reason", type(exc).__name__)
            outcome = {"ok": False, "reason": str(reason) if reason else ""}
        outcome["name"] = name
        outcome["elapsed_seconds"] = round(time.monotonic() - started, 3)
        results.append(outcome)
        print(json.dumps(outcome, ensure_ascii=False), file=sys.stderr)
    payload = {
        "mode": "synthetic",
        "status": "passed" if all(item["ok"] for item in results) else "failed",
        "scenarios": [
            {
                "name": item["name"],
                "ok": item["ok"],
                "elapsed_seconds": item["elapsed_seconds"],
                **{
                    key: value
                    for key, value in item.items()
                    if key
                    not in {
                        "name",
                        "ok",
                        "elapsed_seconds",
                    }
                },
            }
            for item in results
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
