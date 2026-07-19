"""PSW-S17: shared run-lifecycle helpers for both ingestion workers.

This module is the single source of truth for the parts of the
``IngestionRun`` lifecycle that MUST stay identical between the current
worker (``process_ingestion_runs``) and the persistent-session worker
(``process_ingestion_runs_persistent_session``):

- :func:`classify_failure_reason` — normalized ``(failure_reason, timed_out)``
  taxonomy for any exception raised during a run.
- :func:`record_final_run_failure` — creates exactly one
  :class:`~apps.ingestion.models.FinalRunFailure` row when a run exhausts
  its retry budget, with the same conditions and fields in both workers.

Scope discipline (PSW-S17 R7): only classification and finalization live
here. Browser cleanup, tab management, retry backoff, stage metrics, and
extraction-specific error wrapping stay in the worker commands and
extractors.

Timeout coverage (PSW-S17 R2/R3): the classifier recognizes every typed
timeout in the project — :class:`ExtractionTimeoutError`,
:class:`SubprocessTimeoutError`, and the persistent navigation
:class:`~apps.ingestion.extractors.legacy_navigation.NavigationTimeoutError`
— plus Playwright's own ``TimeoutError`` reached through a wrapping chain
(``__cause__`` or ``__context__``). The chain walk lets a typed timeout
survive the sanitizing ``except Exception: raise ExtractionError(...) from exc``
boundaries used by the persistent adapter and bridge, so the externally
visible ``failure_reason`` is ``"timeout"`` regardless of which worker
raised the failure.
"""

from __future__ import annotations

from typing import Any

from apps.ingestion.extractors.errors import (
    ExtractionError,
    ExtractionTimeoutError,
    InvalidJsonError,
    SnapshotContainerMissingError,
)
from apps.ingestion.extractors.persistent_evolution_pdf import EvolutionPdfError
from apps.ingestion.extractors.subprocess_utils import SubprocessTimeoutError

# ---------------------------------------------------------------------------
# Failure taxonomy
# ---------------------------------------------------------------------------


def _is_playwright_timeout(exc: Any) -> bool:
    """Return True if ``exc`` looks like Playwright's ``TimeoutError``.

    Playwright is not a hard import dependency of this module (the workers
    must remain importable without a running browser stack), so detection is
    done by class name AND module prefix. Real Playwright raises
    ``playwright._impl._errors.TimeoutError``; tests inject duck-typed
    subclasses with the same qualified shape.
    """
    cls = type(exc)
    if cls.__name__ != "TimeoutError":
        return False
    module = getattr(cls, "__module__", "") or ""
    return "playwright" in module


def _walk_chain_for_timeout(exc: Any) -> bool:
    """Walk ``__cause__`` then ``__context__`` looking for a typed timeout.

    Sanitizing boundaries in the persistent path wrap the original error
    (``raise ExtractionError(...) from exc`` or ``raise X from None``). The
    original is still reachable through ``__cause__`` (when ``from exc``) or
    ``__context__`` (always set when raised inside an ``except`` block, even
    when ``from None`` suppresses its display).

    Defends against cycles via a visited set bounded by chain length.
    """
    seen: set[int] = set()
    cur: Any = exc
    # Bound the walk to avoid pathological chains; 32 levels is far more
    # than any real wrapping stack.
    for _ in range(32):
        if cur is None:
            return False
        cur_id = id(cur)
        if cur_id in seen:
            return False
        seen.add(cur_id)
        if isinstance(cur, (ExtractionTimeoutError, SubprocessTimeoutError)):
            return True
        if _is_playwright_timeout(cur):
            return True
        # Prefer __cause__ (explicit chain); fall back to __context__ so
        # ``raise X from None`` does not hide the underlying timeout.
        nxt = getattr(cur, "__cause__", None)
        if nxt is None:
            nxt = getattr(cur, "__context__", None)
        cur = nxt
    return False


def classify_failure_reason(exc: Exception) -> tuple[str, bool]:
    """Classify an exception into the normalized failure taxonomy.

    Returns:
        ``(failure_reason, timed_out)`` where ``failure_reason`` is one of
        the values allowed by ``IngestionRun.FAILURE_REASON_CHOICES``:

        - ``"timeout"`` — any typed timeout (``ExtractionTimeoutError``,
          ``SubprocessTimeoutError``, persistent
          ``NavigationTimeoutError``) or a Playwright ``TimeoutError``
          reached through a wrapping chain.
        - ``"invalid_payload"`` — extractor produced data that could not be
          parsed/validated as a payload (``InvalidJsonError``,
          ``SnapshotContainerMissingError``, ``EvolutionPdfError``).
        - ``"validation_error"`` — Django ``ValidationError`` raised by
          domain validators.
        - ``"source_unavailable"`` — any other ``ExtractionError`` (session
          not ready, renewal failed, navigation element missing, etc.).
        - ``"unexpected_exception"`` — anything else.

    This function MUST be used by both worker commands so they produce
    identical externally observable classifications for the same failure.
    """
    # R2/R3: timeouts first — a typed timeout must never be collapsed into
    # source_unavailable or invalid_payload by an outer wrapper.
    if isinstance(exc, (ExtractionTimeoutError, SubprocessTimeoutError)):
        return ("timeout", True)
    if _walk_chain_for_timeout(exc):
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

    # Same conditions as the current worker: only census-batched runs with
    # a resolvable patient record get a row.
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
