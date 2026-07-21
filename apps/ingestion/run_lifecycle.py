"""PSW-S17: shared run-lifecycle helpers for both ingestion workers.

This module is the single source of truth for the parts of the
``IngestionRun`` lifecycle that MUST stay identical between the current
worker (``process_ingestion_runs``) and the persistent-session worker
(``process_ingestion_runs_persistent_session``):

- :func:`classify_failure_reason` — normalized ``(failure_reason, timed_out)``
  taxonomy for any exception raised during a run.
- :func:`record_final_run_failure` — creates exactly one
  :class:`~apps.ingestion.models.FinalRunFailure` row when a run exhausts
  its retry budget.
- :func:`safe_failure_text` — stable category-specific error text for
  command stdout/stderr failure lines.

Scope discipline (PSW-S17 R7): only classification, finalization, and
failure-line text live here. Browser cleanup, tab management, retry backoff,
stage metrics, and extraction-specific error wrapping stay in the worker
commands and extractors.

Timeout contract (PSW-S17 R2/R3 correction): the classifier recognizes
typed domain timeouts ONLY — :class:`ExtractionTimeoutError`,
:class:`SubprocessTimeoutError`, the persistent
:class:`~apps.ingestion.extractors.legacy_navigation.NavigationTimeoutError`,
and :class:`~apps.ingestion.extractors.persistent_evolution_pdf.EvolutionPdfTimeoutError`.
Persistent source boundaries are responsible for raising a typed outer
exception (never a generic ``ExtractionError`` that happens to wrap a
Playwright timeout). The previous cause/context chain walker was removed
because it reinterpreted raw Playwright exceptions in the current worker,
changing its pre-S17 taxonomy (R8 violation).
"""

from __future__ import annotations

from typing import Any

from apps.ingestion.extractors.errors import (
    ExtractionError,
    ExtractionTimeoutError,
    InvalidJsonError,
    SnapshotContainerMissingError,
)
from apps.ingestion.extractors.persistent_evolution_pdf import (
    EvolutionPdfError,
    EvolutionPdfTimeoutError,
)
from apps.ingestion.extractors.subprocess_utils import SubprocessTimeoutError

# ---------------------------------------------------------------------------
# Failure taxonomy
# ---------------------------------------------------------------------------


def classify_failure_reason(exc: Exception) -> tuple[str, bool]:
    """Classify an exception into the normalized failure taxonomy.

    Returns:
        ``(failure_reason, timed_out)`` where ``failure_reason`` is one of
        the values allowed by ``IngestionRun.FAILURE_REASON_CHOICES``:

        - ``"timeout"`` — any typed domain timeout
          (``ExtractionTimeoutError``, ``SubprocessTimeoutError``,
          persistent ``NavigationTimeoutError``/``EvolutionPdfTimeoutError``).
        - ``"invalid_payload"`` — extractor produced data that could not be
          parsed/validated as a payload (``InvalidJsonError``,
          ``SnapshotContainerMissingError``, non-timeout
          ``EvolutionPdfError``).
        - ``"validation_error"`` — Django ``ValidationError``.
        - ``"source_unavailable"`` — any other ``ExtractionError`` (session
          not ready, renewal failed, navigation element missing, etc.).
        - ``"unexpected_exception"`` — anything else (including a raw
          Playwright ``TimeoutError`` that was not mapped to a typed domain
          timeout at a source boundary).

    R3 (correction): the classifier does NOT walk ``__cause__``/``__context__``
    and does NOT reinterpret raw Playwright exceptions. Persistent source
    boundaries must raise typed outer exceptions; the current worker's
    pre-S17 taxonomy is preserved verbatim (a raw Playwright ``TimeoutError``
    that surfaces directly is ``unexpected_exception``, not ``timeout``).
    """
    # R2/R3: typed domain timeouts. Order matters: EvolutionPdfTimeoutError
    # is both an EvolutionPdfError and an ExtractionTimeoutError; test the
    # timeout branch before the invalid_payload branch.
    if isinstance(
        exc,
        (ExtractionTimeoutError, SubprocessTimeoutError, EvolutionPdfTimeoutError),
    ):
        return ("timeout", True)

    # invalid_payload family (data-level failures).
    if isinstance(exc, InvalidJsonError):
        return ("invalid_payload", False)
    if isinstance(exc, SnapshotContainerMissingError):
        return ("invalid_payload", False)
    if isinstance(exc, EvolutionPdfError):
        return ("invalid_payload", False)

    # validation_error: Django domain validators.
    from django.core.exceptions import ValidationError

    if isinstance(exc, ValidationError):
        return ("validation_error", False)

    # source_unavailable: any other sanitized extraction error.
    if isinstance(exc, ExtractionError):
        return ("source_unavailable", False)

    return ("unexpected_exception", False)


# ---------------------------------------------------------------------------
# Safe failure-line text (R4)
# ---------------------------------------------------------------------------


# Stable category-specific constants used as the single source of truth for
# BOTH command stdout/stderr failure lines AND persisted ``error_message`` /
# ``details_json`` error text. PSW-S17 final closure (D4/R2): no ``str(exc)``
# is persisted for any exception class — these constants are the only error
# text that reaches run/attempt/stage error fields. They never include a
# URL, cookie, credential, patient record, admission key, selector, raw
# Playwright text, or subprocess preview.
_FAILURE_TEXT: dict[str, str] = {
    "timeout": "source-system action timed out",
    "source_unavailable": "source-system action unavailable",
    "invalid_payload": "source-system payload invalid or unavailable",
    "validation_error": "source-system validation error",
    "unexpected_exception": "unexpected worker failure",
}
_UNKNOWN_FAILURE_TEXT = "worker failure"


def safe_failure_text(failure_reason: str) -> str:
    """Return the stable, sanitized failure text for a category.

    PSW-S17 final closure (D4/R2): this is the single source of truth for
    all persisted and emitted error text. Both worker commands, stage
    metrics, run/attempt ``error_message``, and command stdout/stderr use
    this constant so no ``str(exc)`` ever reaches a persisted or emitted
    surface.
    """
    return _FAILURE_TEXT.get(failure_reason, _UNKNOWN_FAILURE_TEXT)


def safe_error_message(exc: BaseException, failure_reason: str) -> str:
    """Return the safe ``error_message`` text to persist for ``exc``.

    PSW-S17 final closure (D4/R2): strict normalized sanitization.
    Derives storage text solely from the normalized failure category.
    No ``str(exc)`` is persisted for ANY exception class — not even
    typed :class:`ExtractionError` subclasses. This guarantees no URL,
    cookie, credential, patient record, admission key, selector, raw
    Playwright text, or subprocess preview can reach persisted error
    fields regardless of what a source boundary includes in its
    exception message.
    """
    return safe_failure_text(failure_reason)


def safe_error_type(exc: BaseException, failure_reason: str) -> str:
    """Return the safe ``error_type`` label to persist for ``exc``.

    PSW-S17 final closure (D4/R2): strict normalized sanitization.
    Returns the normalized failure category — never a dynamic exception
    class name (which could carry misleading context or leak internal
    structure). Both worker commands consume this for stage-level
    ``error_type`` so the field is identical across workers for the same
    category.
    """
    return failure_reason


# ---------------------------------------------------------------------------
# Terminal finalization
# ---------------------------------------------------------------------------


def record_final_run_failure(run: Any) -> None:
    """Create the terminal ``FinalRunFailure`` row for ``run`` if applicable.

    Mirrors the current worker's terminal-failure condition so both workers
    produce exactly one row under the same circumstances and with the same
    fields:

    - The run must have a ``batch`` (legacy census batches only).
    - ``parameters_json.patient_record`` (or empty) must be non-empty.
    - ``FinalRunFailure`` is created via ``get_or_create(run=run)`` so
      repeated calls (e.g. retry recovery plus worker) never duplicate the
      row.

    Intent resolution matches the current worker: prefer
    ``parameters_json.intent``; fall back to ``run.intent``.

    Args:
        run: A terminal (status="failed") ``IngestionRun`` instance.
    """
    from apps.ingestion.models import FinalRunFailure

    params = getattr(run, "parameters_json", None) or {}
    patient_record = params.get("patient_record", "")
    batch = getattr(run, "batch", None)

    if batch is None or not patient_record:
        return

    intent = params.get("intent", "") or getattr(run, "intent", "") or ""

    FinalRunFailure.objects.get_or_create(
        run=run,
        defaults={
            "batch": batch,
            "patient_record": patient_record,
            "intent": intent,
            "attempts_exhausted": run.attempt_count,
        },
    )
