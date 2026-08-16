"""Unit tests for the Playwright census script sector helpers.

Covers the pure, deterministic helpers in
``automation/source_system/current_inpatients/extract_census.py``:

- sector label normalization and deduplication;
- aggregate sector summary counters;
- bounded dropdown collection that merges scrolled reads.

No Playwright browser is launched and no source system is contacted.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

# The script mutates sys.path at import time (it inserts its project and
# automation roots so standalone subprocess imports resolve). It also caches
# the top-level `source_system` module under the script's own resolution,
# which would otherwise shadow medical_evolution/source_system.py for later
# test collection (e.g. test_path2_signature_datetime_fallback.py). Snapshot
# and restore both sys.path and that module entry so this test module does
# not leak import state into the rest of the pytest process.
_SYS_PATH_BEFORE_IMPORT = list(sys.path)
_SOURCE_SYSTEM_MODULE_BEFORE = sys.modules.get("source_system")

from automation.source_system.current_inpatients import extract_census as ec  # noqa: E402

sys.path[:] = _SYS_PATH_BEFORE_IMPORT
if _SOURCE_SYSTEM_MODULE_BEFORE is None:
    sys.modules.pop("source_system", None)


class TestNormalizeSetorLabel:
    def test_drops_blank_labels(self) -> None:
        assert ec.normalize_setor_label("") == ""
        assert ec.normalize_setor_label("   ") == ""
        assert ec.normalize_setor_label("\t\n") == ""
        assert ec.normalize_setor_label(None) == ""

    def test_preserves_valid_labels(self) -> None:
        assert ec.normalize_setor_label("UTI A") == "UTI A"
        assert ec.normalize_setor_label("  UTI A  ") == "UTI A"
        assert ec.normalize_setor_label("0 T  -  SALA LARANJA") == "0 T - SALA LARANJA"
        assert ec.normalize_setor_label("ENF\nB") == "ENF B"


class TestDedupeSetores:
    def test_keeps_first_occurrence_order(self) -> None:
        labels = [
            "UTI A",
            " UTI A ",
            "",
            "ENF B",
            "UTI A",
            "0 T - SALA LARANJA",
        ]
        assert ec.dedupe_setores(labels) == [
            "UTI A",
            "ENF B",
            "0 T - SALA LARANJA",
        ]

    def test_empty_and_blank_only_input(self) -> None:
        assert ec.dedupe_setores([]) == []
        assert ec.dedupe_setores(["", "   "]) == []

    def test_case_is_preserved(self) -> None:
        assert ec.dedupe_setores(["uti a", "UTI A"]) == ["uti a", "UTI A"]


class TestSummarizeSectorResults:
    def test_reports_discovered_processed_empty_failed(self) -> None:
        results: list[dict[str, object]] = [
            {"setor": "UTI A", "pacientes": [{"prontuario": "100001"}]},
            {"setor": "ENF B", "pacientes": []},
            {"setor": "ENF C", "pacientes": [], "erro": "timeout"},
        ]
        counters = ec.summarize_sector_results(
            discovered=40,
            results=results,
        )
        assert counters == {
            "setores_found": 40,
            "setores_processed": 3,
            "setores_empty": 1,
            "setores_with_error": 1,
        }

    def test_empty_results(self) -> None:
        empty_results: list[dict[str, object]] = []
        counters = ec.summarize_sector_results(
            discovered=0,
            results=empty_results,
        )
        assert counters == {
            "setores_found": 0,
            "setores_processed": 0,
            "setores_empty": 0,
            "setores_with_error": 0,
        }


class TestFormatSectorSummary:
    def test_includes_aggregate_labels_and_values(self) -> None:
        counters = {
            "setores_found": 40,
            "setores_processed": 38,
            "setores_empty": 2,
            "setores_with_error": 1,
        }
        text = ec.format_sector_summary(counters)
        assert "Setores encontrados: 40" in text
        assert "Setores processados: 38" in text
        assert "Setores sem pacientes: 2" in text
        assert "Setores com erro: 1" in text

    def test_does_not_expose_identifiers_or_credentials(self) -> None:
        counters = {
            "setores_found": 40,
            "setores_processed": 38,
            "setores_empty": 2,
            "setores_with_error": 1,
        }
        text = ec.format_sector_summary(counters).lower()
        for forbidden in ("prontuario", "senha", "password", "credential"):
            assert forbidden not in text


class TestExtractSetoresCollection:
    def test_merges_scrolled_reads_and_dedupes(self) -> None:
        frame = MagicMock()
        page = MagicMock()
        reads = [
            ["UTI A", " UTI A "],
            ["ENF B", "UTI A"],
            [],
        ]
        scrolls = [False, False, True]

        with (
            patch.object(ec, "safe_click", return_value=True),
            patch.object(ec, "wait_ajax_idle"),
            patch.object(ec, "_read_setores_from_dom", side_effect=reads),
            patch.object(ec, "_scroll_setor_panel", side_effect=scrolls),
        ):
            result = ec.extract_setores(frame, page)

        assert result == ["UTI A", "ENF B"]

    def test_returns_empty_when_nothing_discovered(self) -> None:
        frame = MagicMock()
        page = MagicMock()
        with (
            patch.object(ec, "safe_click", return_value=True),
            patch.object(ec, "wait_ajax_idle"),
            patch.object(ec, "_read_setores_from_dom", return_value=["", "   "]),
        ):
            result = ec.extract_setores(frame, page)
        assert result == []

    def test_bounds_scroll_attempts(self) -> None:
        frame = MagicMock()
        page = MagicMock()
        with (
            patch.object(ec, "safe_click", return_value=True),
            patch.object(ec, "wait_ajax_idle"),
            patch.object(ec, "_read_setores_from_dom", return_value=["UTI A"]),
            patch.object(ec, "_scroll_setor_panel", return_value=False) as scroll,
        ):
            result = ec.extract_setores(frame, page)
        assert result == ["UTI A"]
        assert scroll.call_count <= ec.MAX_SETOR_PANEL_SCROLLS

    def test_scroll_panel_stops_at_bottom(self) -> None:
        frame = MagicMock()
        frame.evaluate.return_value = True
        page = MagicMock()
        assert ec._scroll_setor_panel(frame, page) is True
        page.wait_for_timeout.assert_not_called()
