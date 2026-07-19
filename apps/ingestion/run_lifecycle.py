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


# Stable category-specific constants used for command stdout/stderr failure
# lines. They never include ``str(exc)`` (which could carry a URL, cookie,
# credential, patient record, admission key, selector, or raw Playwright
# text). Persisted ``error_message``/``details_json`` fields continue to
# store ``str(exc)`` because source boundaries (PSW-S17 R2/R4) now raise
# typed exceptions with constant sanitized messages.
_FAILURE_TEXT: dict[str, str] = {
    "timeout": "source-system action timed out",
    "source_unavailable": "source-system action unavailable",
    "invalid_payload": "source-system payload invalid or unavailable",
    "validation_error": "source-system validation error",
    "unexpected_exception": "unexpected worker failure",
}
_UNKNOWN_FAILURE_TEXT = "worker failure"


def safe_failure_text(failure_reason: str) -> str:
    """Return the stable, sanitized failure-line text for a category.

    Used by command stdout/stderr failure summaries so operator logs never
    echo ``str(exc)`` for an unexpected/source exception. Persisted DB
    fields (``error_message``, ``details_json``) are governed by their own
    contracts and may keep ``str(exc)`` for typed domain exceptions whose
    messages are themselves sanitized constants.
    """
    return _FAILURE_TEXT.get(failure_reason, _UNKNOWN_FAILURE_TEXT)


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
