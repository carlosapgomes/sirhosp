"""Historical recovery planning and result contracts.

Provides planning logic and command-level result dataclasses for the
historical recovery orchestrator. This module does NOT call extractor
services — Slice C3-S1 focuses exclusively on contracts and planning.

The orchestrator (Slice C3-S2) will import these dataclasses and the
plan-building helpers to manage service execution.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from apps.ingestion.historical_extraction import ExtractionResult

# ---------------------------------------------------------------------------
# Default extractor order (mirrors legacy shell script behaviour)
# ---------------------------------------------------------------------------

DEFAULT_EXTRACTOR_ORDER: list[str] = [
    "discharges",
    "admissions",
    "deaths",
    "official_census",
]

_VALID_EXTRACTORS: set[str] = set(DEFAULT_EXTRACTOR_ORDER)

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

_DATE_FORMAT = "%d/%m/%Y"


def _date_to_str(d: date) -> str:
    """Format a ``date`` as ``DD/MM/AAAA``."""
    return d.strftime(_DATE_FORMAT)


def _parse_date(date_str: str) -> date:
    """Parse a ``DD/MM/AAAA`` date string into a ``datetime.date``.

    Args:
        date_str: Date string in ``DD/MM/AAAA`` format.

    Returns:
        A ``date`` instance.

    Raises:
        ValueError: If ``date_str`` is not valid ``DD/MM/AAAA`` or
            represents an impossible date (e.g. 31/02/2026).
    """
    if not isinstance(date_str, str) or not date_str.strip():
        raise ValueError(f"Invalid date: {date_str!r}")

    try:
        parsed = datetime.strptime(date_str.strip(), _DATE_FORMAT).date()
    except ValueError:
        # strptime wraps the original error; raise with the input for clarity.
        # `from None` suppresses the noisy strptime traceback for operators.
        raise ValueError(f"Invalid date: {date_str!r}") from None

    return parsed


def build_date_range(start: date, end: date) -> list[date]:
    """Build an inclusive list of dates from ``start`` to ``end``.

    Args:
        start: Inclusive start date.
        end: Inclusive end date.

    Returns:
        A list of ``date`` objects from ``start`` through ``end``,
        inclusive of both.

    Raises:
        ValueError: If ``end`` is before ``start``.
    """
    if end < start:
        raise ValueError(
            f"End date {end} is before start date {start}"
        )

    total_days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(total_days)]


# ---------------------------------------------------------------------------
# Extractor selection helpers
# ---------------------------------------------------------------------------


def validate_extractors(selected: list[str] | None = None) -> list[str]:
    """Validate and sort extractor names into default order.

    Args:
        selected: A list of extractor names, or ``None`` / empty list
            to select all extractors.

    Returns:
        A list of extractor names sorted in
        :data:`DEFAULT_EXTRACTOR_ORDER`.

    Raises:
        ValueError: If any name in ``selected`` is not a recognised
            extractor.
    """
    if not selected:
        return list(DEFAULT_EXTRACTOR_ORDER)

    unknown = [name for name in selected if name not in _VALID_EXTRACTORS]
    if unknown:
        raise ValueError(
            f"Unknown extractor(s): {', '.join(unknown)}"
        )

    return [name for name in DEFAULT_EXTRACTOR_ORDER if name in set(selected)]


# ---------------------------------------------------------------------------
# Service registry
# ---------------------------------------------------------------------------


def make_service_registry() -> dict[str, Callable[..., "ExtractionResult"]]:
    """Build the default service registry with lazy-imported extractors.

    Each entry is a callable with signature ``(date_str: str, headless: bool)``
    that returns an ``ExtractionResult``.

    Returns:
        A dict mapping extractor names to their service callables.
    """
    # Lazy imports — avoid loading Playwright dependencies at module level.
    from apps.admissions.services import run_admission_extraction
    from apps.census.services import run_official_census_extraction
    from apps.deaths.services import run_death_extraction
    from apps.discharges.extraction_service import run_discharge_extraction

    def _discharge(
        date_str: str, headless: bool = True
    ) -> "ExtractionResult":
        return run_discharge_extraction(date=date_str, headless=headless)

    def _admission(
        date_str: str, headless: bool = True
    ) -> "ExtractionResult":
        return run_admission_extraction(
            start_date=date_str, end_date=date_str, headless=headless
        )

    def _death(
        date_str: str, headless: bool = True
    ) -> "ExtractionResult":
        return run_death_extraction(
            start_date=date_str, end_date=date_str, headless=headless
        )

    def _census(
        date_str: str, headless: bool = True
    ) -> "ExtractionResult":
        return run_official_census_extraction(date=date_str, headless=headless)

    return {
        "discharges": _discharge,
        "admissions": _admission,
        "deaths": _death,
        "official_census": _census,
    }


# ---------------------------------------------------------------------------
# Orchestration engine
# ---------------------------------------------------------------------------


def execute_recovery_plan(
    plan: RecoveryPlan,
    *,
    headless: bool = True,
    service_registry: dict[str, Callable[..., "ExtractionResult"]] | None = None,
) -> RecoveryRunResult:
    """Execute a ``RecoveryPlan`` by calling extractor services directly.

    Iterates over each date in ``plan.dates`` and each extractor name in
    ``plan.extractors``, calls the matching service function, and collects
    per-step results into a ``RecoveryRunResult``.

    When ``plan.dry_run`` is ``True``, no service functions are called --
    each step is recorded as skipped with ``success=True`` and empty metrics.

    When ``plan.fail_fast`` is ``True``, execution stops immediately after
    the first failed step (service result with ``success=False`` or an
    unexpected exception). By default, all steps are executed and failures
    are aggregated.

    Unexpected Python exceptions from service calls are converted into
    failed steps with ``failure_reason="unexpected_error"`` and a generic
    safe message.

    Args:
        plan: The plan describing dates, extractors, and execution flags.
        headless: Whether to run Playwright in headless mode.
        service_registry: Optional dict of extractor-name -> callable.
            Defaults to the result of :func:`make_service_registry`.

    Returns:
        A ``RecoveryRunResult`` aggregating all step outcomes.

    Raises:
        ValueError: If an extractor name in the plan is not in the registry.
    """
    if service_registry is None:
        service_registry = make_service_registry()

    # Sort plan extractors into deterministic default order.
    ordered_extractors = validate_extractors(plan.extractors)

    unknown = [e for e in ordered_extractors if e not in service_registry]
    if unknown:
        raise ValueError(f"Unknown extractor(s) in plan: {', '.join(unknown)}")

    steps: list[RecoveryStepResult] = []
    should_stop = False

    for day in plan.dates:
        if should_stop:
            break

        date_label = _date_to_str(day)

        for extractor_name in ordered_extractors:
            if plan.dry_run:
                step = RecoveryStepResult(
                    date=day,
                    date_label=date_label,
                    extractor=extractor_name,
                    success=True,
                    extraction_type=f"{extractor_name}_extraction",
                    metrics={},
                    skipped=True,
                    failure_reason="",
                    error_message="",
                    ingestion_run_id=None,
                )
                steps.append(step)
                continue

            service_fn = service_registry[extractor_name]

            try:
                service_result = service_fn(date_label, headless=headless)
                step = RecoveryStepResult(
                    date=day,
                    date_label=date_label,
                    extractor=extractor_name,
                    success=service_result.success,
                    extraction_type=service_result.extraction_type,
                    metrics=dict(service_result.metrics),
                    skipped=False,
                    failure_reason=service_result.failure_reason,
                    error_message=service_result.error_message,
                    ingestion_run_id=service_result.ingestion_run_id,
                )
            except Exception:
                # Catch unexpected exceptions from service calls and convert
                # them into a safe failed step with a generic credential-safe
                # message instead of raw traceback text.
                step = RecoveryStepResult(
                    date=day,
                    date_label=date_label,
                    extractor=extractor_name,
                    success=False,
                    extraction_type=f"{extractor_name}_extraction",
                    metrics={},
                    skipped=False,
                    failure_reason="unexpected_error",
                    error_message="Unexpected extractor failure.",
                    ingestion_run_id=None,
                )

            steps.append(step)

            if plan.fail_fast and not step.success:
                should_stop = True
                break

    return RecoveryRunResult(
        start_date=plan.dates[0] if plan.dates else date.min,
        end_date=plan.dates[-1] if plan.dates else date.min,
        steps=steps,
    )


# ---------------------------------------------------------------------------
# Per-step result contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryStepResult:
    """Result of a single date/extractor recovery step.

    Attributes:
        date: The target date of this step.
        date_label: Human-readable ``DD/MM/AAAA`` label.
        extractor: The extractor name (e.g. ``"discharges"``).
        success: Whether the extraction succeeded.
        extraction_type: The machine-readable extraction type
            (e.g. ``"discharge_extraction"``).
        metrics: Counters from the extractor result
            (e.g. ``{"total_records": 42}``). Empty dict when
            no metrics are available.
        skipped: Whether this step was a dry-run placeholder
            (no actual extraction executed).
        failure_reason: Normalised failure category when
            ``success`` is ``False``.
        error_message: Safe, user-readable error description.
        ingestion_run_id: Optional primary key of the associated
            ``IngestionRun``.
    """

    date: date
    date_label: str
    extractor: str
    success: bool
    extraction_type: str

    metrics: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False
    failure_reason: str = ""
    error_message: str = ""
    ingestion_run_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Aggregated run result contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryRunResult:
    """Aggregated result for an entire historical recovery run.

    Attributes:
        start_date: Inclusive start date of the recovery period.
        end_date: Inclusive end date of the recovery period.
        steps: Ordered list of per-step results.
    """

    start_date: date
    end_date: date
    steps: list[RecoveryStepResult] = field(default_factory=list)

    # -- computed properties ------------------------------------------------

    @property
    def success(self) -> bool:
        """``True`` when no non-skipped step has ``success=False``."""
        return all(
            step.success or step.skipped for step in self.steps
        )

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def successful_steps(self) -> int:
        return sum(1 for s in self.steps if s.success)

    @property
    def failed_steps(self) -> int:
        return sum(1 for s in self.steps if not s.success and not s.skipped)

    @property
    def skipped_steps(self) -> int:
        return sum(1 for s in self.steps if s.skipped)

    @property
    def summary(self) -> str:
        """Human-readable one-line summary of results."""
        return (
            f"Days: {len(set(s.date for s in self.steps))} | "
            f"Steps: {self.total_steps} | "
            f"Succeeded: {self.successful_steps} | "
            f"Failed: {self.failed_steps} | "
            f"Skipped: {self.skipped_steps}"
        )


# ---------------------------------------------------------------------------
# Plan contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryPlan:
    """Immutable plan describing what to execute.

    Attributes:
        dates: Date sequence to process (inclusive range).
        extractors: Ordered list of extractor names to run.
        dry_run: When ``True``, show plan without executing.
        fail_fast: When ``True``, stop after first failure.
    """

    dates: list[date]
    extractors: list[str]
    dry_run: bool = False
    fail_fast: bool = False

    @property
    def total_dates(self) -> int:
        return len(self.dates)

    @property
    def date_count_label(self) -> str:
        return "1 day" if self.total_dates == 1 else f"{self.total_dates} days"
