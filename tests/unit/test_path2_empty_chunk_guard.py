"""Unit tests for empty-chunk early-stop guard in path2 connector.

Covers two behaviors introduced for real-world edge cases:
1. Detect source warning text for chunks without evolutions.
2. Stop admission extraction after consecutive empty chunks.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_GUARD_FILE = (
    Path(__file__).resolve().parents[2]
    / "automation"
    / "source_system"
    / "medical_evolution"
    / "empty_chunk_guard.py"
)

_spec = importlib.util.spec_from_file_location("_empty_chunk_guard", _GUARD_FILE)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

is_no_evolutions_warning_message = _mod.is_no_evolutions_warning_message
update_empty_chunk_streak = _mod.update_empty_chunk_streak
EMPTY_CHUNK_STOP_THRESHOLD = _mod.EMPTY_CHUNK_STOP_THRESHOLD


class TestNoEvolutionsWarningMatcher:
    """Message matcher should be robust to spacing and wrappers."""

    def test_matches_exact_warning_text(self):
        text = "Não existem Evoluções registradas no período informado"
        assert is_no_evolutions_warning_message(text)

    def test_matches_warning_with_extra_whitespace(self):
        text = "  Não existem   Evoluções\nregistradas no período informado  "
        assert is_no_evolutions_warning_message(text)

    def test_matches_warning_inside_longer_message(self):
        text = (
            "Mensagens do Sistema: Não existem Evoluções registradas no período "
            "informado."
        )
        assert is_no_evolutions_warning_message(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Nenhuma internação foi encontrada para o prontuário informado",
            "Erro ao gerar relatório",
            "",
        ],
    )
    def test_does_not_match_other_messages(self, text: str):
        assert not is_no_evolutions_warning_message(text)


class TestEmptyChunkStreakHeuristic:
    """Two consecutive empty chunks should trigger early stop."""

    def test_first_empty_chunk_does_not_stop(self):
        streak, should_stop = update_empty_chunk_streak(
            previous_streak=0,
            chunk_has_report=False,
        )
        assert streak == 1
        assert not should_stop

    def test_second_consecutive_empty_chunk_stops(self):
        streak, should_stop = update_empty_chunk_streak(
            previous_streak=1,
            chunk_has_report=False,
        )
        assert streak == EMPTY_CHUNK_STOP_THRESHOLD
        assert should_stop

    def test_chunk_with_report_resets_streak(self):
        streak, should_stop = update_empty_chunk_streak(
            previous_streak=2,
            chunk_has_report=True,
        )
        assert streak == 0
        assert not should_stop

    def test_custom_threshold_supported(self):
        streak, should_stop = update_empty_chunk_streak(
            previous_streak=1,
            chunk_has_report=False,
            stop_threshold=3,
        )
        assert streak == 2
        assert not should_stop
