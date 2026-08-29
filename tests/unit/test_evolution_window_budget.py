"""FX-S2: unit tests for the per-window evolution extraction budget.

Covers R1 (pure deterministic ``evolution_window_budget_seconds`` with base,
per-day growth, cap, sanitized invalid-date/parameter errors), R2 (the
persistent worker's evolution-gap loop passes the per-window scaled budget —
never a fixed 120s literal) and R3 (bounded behavior preserved: the real
``EvolutionPdfFlow`` under a short experimental budget still raises the typed
``EvolutionPdfTimeoutError``).

All fixtures are synthetic/anonymous and duck-typed — no real browser, no
network, no subprocess, no patient data.
"""

from __future__ import annotations

import time as time_mod
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from apps.ingestion.extractors.persistent_evolution_pdf import (
    EvolutionPdfError,
    EvolutionPdfFlow,
    EvolutionPdfTimeoutError,
)
from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (
    Command as PersistentWorkerCommand,
)
from apps.ingestion.models import IngestionRun

# Constant sanitized messages the budget function MUST emit (no input echo).
_EXPECTED_INVALID_DATE_MESSAGE = "Invalid date window for the evolution budget"
_EXPECTED_INVALID_PARAMETER_MESSAGE = "Invalid evolution budget parameters"

# Sentinel inputs that must NEVER appear in sanitized error messages.
_DATE_SENTINEL = "SENTINEL-NOT-A-DATE-987"
_PARAM_SENTINEL = -987


def _evolution_window_budget_seconds():
    """Lazy import so RED collection works before the function exists."""
    from apps.ingestion.extractors.persistent_evolution_pdf import (
        evolution_window_budget_seconds,
    )

    return evolution_window_budget_seconds


# ===========================================================================
# R1 — pure budget function
# ===========================================================================


class TestEvolutionWindowBudgetSeconds:
    """R1: base + per-day growth, capped; deterministic; sanitized errors."""

    def test_same_date_returns_base_seconds(self) -> None:
        budget = _evolution_window_budget_seconds()
        assert budget("2024-01-15", "2024-01-15") == 120

    def test_one_day_span_scales_by_seconds_per_day(self) -> None:
        budget = _evolution_window_budget_seconds()
        assert budget("2024-01-01", "2024-01-02") == 122

    def test_31_day_span_linear_growth(self) -> None:
        budget = _evolution_window_budget_seconds()
        assert budget("2024-01-01", "2024-02-01") == 182  # 120 + 2*31

    def test_large_span_is_capped_at_default_cap(self) -> None:
        budget = _evolution_window_budget_seconds()
        # 400-day span -> 120 + 2*400 = 920, capped at 600.
        assert budget("2023-01-01", "2024-02-05") == 600

    def test_custom_named_defaults_override_all_three(self) -> None:
        budget = _evolution_window_budget_seconds()
        assert (
            budget(
                "2024-01-01",
                "2024-02-01",
                base_seconds=60,
                seconds_per_day=3,
                cap_seconds=200,
            )
            == 153
        )  # 60 + 3*31 = 153 (below cap 200)

    def test_custom_cap_binds_below_linear_growth(self) -> None:
        budget = _evolution_window_budget_seconds()
        assert (
            budget(
                "2024-01-01",
                "2024-02-01",
                base_seconds=60,
                seconds_per_day=3,
                cap_seconds=100,
            )
            == 100
        )  # 60 + 3*31 = 153 -> capped

    def test_is_deterministic_for_same_inputs(self) -> None:
        budget = _evolution_window_budget_seconds()
        first = budget("2024-01-01", "2024-03-01")
        second = budget("2024-01-01", "2024-03-01")
        assert first == second == 240
        # And it actually varies with the span (not a constant).
        assert budget("2024-01-01", "2024-01-02") != first

    def test_invalid_date_raises_sanitized_constant_error(self) -> None:
        budget = _evolution_window_budget_seconds()
        with pytest.raises(EvolutionPdfError) as exc_info:
            budget(_DATE_SENTINEL, "2024-01-02")
        assert str(exc_info.value) == _EXPECTED_INVALID_DATE_MESSAGE
        assert _DATE_SENTINEL not in str(exc_info.value)

    def test_malformed_date_format_raises_sanitized_error(self) -> None:
        budget = _evolution_window_budget_seconds()
        with pytest.raises(EvolutionPdfError) as exc_info:
            budget("01/01/2024", "2024-01-02")  # wrong format
        assert str(exc_info.value) == _EXPECTED_INVALID_DATE_MESSAGE

    def test_inverted_dates_raise_sanitized_constant_error(self) -> None:
        budget = _evolution_window_budget_seconds()
        with pytest.raises(EvolutionPdfError) as exc_info:
            budget("2024-02-01", "2024-01-01")  # start after end
        assert str(exc_info.value) == _EXPECTED_INVALID_DATE_MESSAGE
        assert "2024-02-01" not in str(exc_info.value)
        assert "2024-01-01" not in str(exc_info.value)

    def test_non_positive_base_seconds_raises_sanitized_error(self) -> None:
        budget = _evolution_window_budget_seconds()
        with pytest.raises(EvolutionPdfError) as exc_info:
            budget("2024-01-01", "2024-01-02", base_seconds=0)
        assert str(exc_info.value) == _EXPECTED_INVALID_PARAMETER_MESSAGE

    def test_negative_cap_seconds_raises_sanitized_error_before_calculation(
        self,
    ) -> None:
        budget = _evolution_window_budget_seconds()
        with pytest.raises(EvolutionPdfError) as exc_info:
            budget(
                "2024-01-01",
                "2024-01-02",
                base_seconds=120,
                seconds_per_day=2,
                cap_seconds=_PARAM_SENTINEL,
            )
        assert str(exc_info.value) == _EXPECTED_INVALID_PARAMETER_MESSAGE
        # The offending value is never echoed.
        assert str(_PARAM_SENTINEL) not in str(exc_info.value)

    def test_non_positive_seconds_per_day_raises_sanitized_error(self) -> None:
        budget = _evolution_window_budget_seconds()
        with pytest.raises(EvolutionPdfError):
            budget("2024-01-01", "2024-01-02", seconds_per_day=0)


# ===========================================================================
# R2 — persistent worker call site passes the per-window budget
# ===========================================================================

_ADMISSION_SNAPSHOT_DATA = [
    {
        "admission_key": "ADM-001",
        "admission_start": "2024-01-15",
        "admission_end": "2024-01-20",
        "ward": "Enfermaria A",
        "bed": "001",
    },
]


@pytest.mark.django_db
class TestPersistentWorkerWindowBudgetCallSite:
    """R2: the evolution-gap loop of the persistent worker passes
    ``timeout=evolution_window_budget_seconds(window start/end)`` — a 60-day
    window receives 240s (never the fixed 120 literal); a same-day window
    keeps the base 120."""

    def _run_full_sync_with_windows(self, windows: list[dict]) -> MagicMock:
        run = IngestionRun.objects.create(
            status="queued",
            intent="full_sync",
            max_attempts=1,
            parameters_json={
                "patient_record": "FS001",
                "intent": "full_sync",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
        )
        adapter = MagicMock()
        adapter.get_admission_snapshot.return_value = _ADMISSION_SNAPSHOT_DATA
        adapter.extract_evolutions.return_value = []
        adapter.cleanup_after_failure = MagicMock()
        adapter.ensure_session_ready = MagicMock(return_value=True)
        adapter.controller = MagicMock()
        adapter.controller.restart_required.return_value = False
        adapter.controller.mark_job_processed = MagicMock()
        adapter.controller.close_job_tab_if_present = MagicMock()
        adapter.controller.reset_after_restart = MagicMock()
        adapter.controller.jobs_processed = 0
        adapter.controller.consecutive_failures = 0

        plan = {
            "windows": windows,
            "gaps": windows,
            "skip_extraction": False,
        }
        with (
            patch.object(
                PersistentWorkerCommand, "_create_adapter", return_value=adapter
            ),
            patch(
                "apps.ingestion.management.commands."
                "process_ingestion_runs_persistent_session.plan_extraction_windows",
                return_value=plan,
            ),
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "succeeded"
        return adapter

    def test_60_day_window_receives_scaled_budget_not_120(self) -> None:
        adapter = self._run_full_sync_with_windows(
            [{"start_date": "2024-01-01", "end_date": "2024-03-01"}]
        )
        adapter.extract_evolutions.assert_called_once()
        kwargs = adapter.extract_evolutions.call_args.kwargs
        assert kwargs["start_date"] == "2024-01-01"
        assert kwargs["end_date"] == "2024-03-01"
        # 60-day span -> base 120 + 2*60 = 240 (never the fixed literal 120).
        assert kwargs["timeout"] == 240
        assert kwargs["timeout"] != 120

    def test_same_day_window_keeps_base_budget(self) -> None:
        adapter = self._run_full_sync_with_windows(
            [{"start_date": "2024-05-01", "end_date": "2024-05-01"}]
        )
        kwargs = adapter.extract_evolutions.call_args.kwargs
        assert kwargs["timeout"] == 120

    def test_mixed_windows_each_receive_their_own_budget(self) -> None:
        adapter = self._run_full_sync_with_windows(
            [
                {"start_date": "2024-01-01", "end_date": "2024-03-01"},
                {"start_date": "2024-05-01", "end_date": "2024-05-01"},
            ]
        )
        calls = adapter.extract_evolutions.call_args_list
        assert [call.kwargs["timeout"] for call in calls] == [240, 120]
        # The scaled window did not silently reuse the fixed literal.
        assert calls[0].kwargs["timeout"] != 120


# ===========================================================================
# R3 — bounded behavior preserved (typed timeout under a short budget)
# ===========================================================================


def _build_pdf_bytes(text: str = "FX-S2 anonymous synthetic text") -> bytes:
    """Build an in-memory anonymous PDF whose extracted text equals ``text``."""
    import pymupdf

    document = pymupdf.open()
    document.new_page()
    document[0].insert_text((72, 72), text)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


class _Clock:
    """Controlled monotonic clock for deadline-boundary tests."""

    def __init__(self) -> None:
        self._t = 1000.0

    def monotonic(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


class _FakeLocator:
    def __init__(self, *, count_value: int = 0, attribute: str | None = None):
        self._count = count_value
        self._attribute = attribute
        self.first = self

    def count(self) -> int:
        return self._count

    def get_attribute(self, name: str, **kwargs) -> str | None:
        return self._attribute


class _FakeResponse:
    def __init__(self, body: bytes = b""):
        self.ok = True
        self.headers: dict[str, str] = {}
        self._body = body

    def body(self) -> bytes:
        return self._body


class _FakeRequest:
    def __init__(self, response: _FakeResponse, on_get=None):
        self._response = response
        self._on_get = on_get

    def get(self, url: str, **kwargs) -> _FakeResponse:
        if self._on_get is not None:
            self._on_get()
        return self._response


class _FakeContext:
    def __init__(self, request: _FakeRequest):
        self.request = request


class _FakePage:
    """Minimal duck-typed Playwright page with a present PDF object."""

    url = "https://legacy.example/relatorio.xhtml"
    frames: list = []

    def __init__(self, request: _FakeRequest):
        self.context = _FakeContext(request)

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(
            count_value=1, attribute="https://legacy.example/report.pdf"
        )


class TestBoundedBudgetRegression:
    """R3: the flow's bounded semantics are untouched by FX-S2 — a short
    experimental budget still yields the typed timeout (CFC fake technique,
    no browser)."""

    def test_short_budget_still_raises_typed_timeout(self) -> None:
        clock = _Clock()
        response = _FakeResponse(body=_build_pdf_bytes())
        request = _FakeRequest(response, on_get=lambda: clock.advance(20.0))
        page = _FakePage(request)
        flow = EvolutionPdfFlow(page)

        with patch.object(time_mod, "monotonic", clock.monotonic):
            with pytest.raises(EvolutionPdfTimeoutError) as exc_info:
                flow.extract(
                    start_date="2024-01-01",
                    end_date="2024-01-02",
                    timeout=5,
                )

        # Typed timeout is also an EvolutionPdfError (sanitized taxonomy).
        assert isinstance(exc_info.value, EvolutionPdfError)
        assert "timed out" in str(exc_info.value).lower()

    def test_request_get_never_exceeds_short_budget(self) -> None:
        clock = _Clock()
        response = _FakeResponse(body=_build_pdf_bytes())
        get_kwargs: dict = {}

        def _capture_on_get():
            pass

        request = _FakeRequest(response, on_get=_capture_on_get)
        original_get = request.get

        def _get(url: str, **kwargs):
            get_kwargs.update(kwargs)
            return original_get(url, **kwargs)

        request.get = _get  # type: ignore[method-assign]
        page = _FakePage(request)
        flow = EvolutionPdfFlow(page)

        with patch.object(time_mod, "monotonic", clock.monotonic):
            flow.extract(
                start_date="2024-01-01",
                end_date="2024-01-02",
                timeout=5,
            )

        # The 5s caller budget bounds the download request (never 120s).
        assert 1 <= get_kwargs["timeout"] <= 5_000
