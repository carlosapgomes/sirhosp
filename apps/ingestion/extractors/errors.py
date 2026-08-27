"""Domain errors for evolution extraction (Slice S1)."""

from __future__ import annotations

from typing import Any

_PLAYWRIGHT_TIMEOUT_ERROR: type[BaseException] | None = None
_PLAYWRIGHT_IMPORT_ATTEMPTED: bool = False


def _get_playwright_timeout_error() -> type[BaseException] | None:
    """Return Playwright's public ``TimeoutError`` type, or None if unavailable.

    PSW-S17 R1 (second corrective closure): the previous implementation
    detected Playwright timeouts by class name + module prefix, which is
    fragile and untestable with the real type. This helper imports the real
    public ``playwright.sync_api.TimeoutError`` lazily (no browser is
    launched at import time) and caches it.
    """
    global _PLAYWRIGHT_TIMEOUT_ERROR, _PLAYWRIGHT_IMPORT_ATTEMPTED
    if not _PLAYWRIGHT_IMPORT_ATTEMPTED:
        _PLAYWRIGHT_IMPORT_ATTEMPTED = True
        try:
            from playwright.sync_api import (  # noqa: PLC0415 - lazy import
                TimeoutError as _PlaywrightTimeoutError,
            )

            _PLAYWRIGHT_TIMEOUT_ERROR = _PlaywrightTimeoutError
        except ImportError:
            _PLAYWRIGHT_TIMEOUT_ERROR = None
    return _PLAYWRIGHT_TIMEOUT_ERROR


class ExtractionError(Exception):
    """Base error for evolution extraction failures."""


class ExtractionTimeoutError(ExtractionError):
    """Extraction exceeded the configured timeout.

    PSW-S17 R2/R3: shared typed timeout marker. Persistent source
    boundaries (``PlaywrightSessionHandle.open_tab``,
    ``RealHandleBridge``, ``EvolutionPdfFlow``, ``legacy_navigation``)
    MUST raise this (or a subclass) when a Playwright/playwright-budget
    timeout occurs so the shared classifier maps the run/attempt to
    ``("timeout", True)``.
    """


class InvalidJsonError(ExtractionError):
    """Extractor returned invalid or unparseable JSON."""


class SnapshotContainerMissingError(ExtractionError):
    """The expected admission snapshot data container was not found in the page.

    Raised when the page HTML does not contain the snapshot data element that
    the persistent extraction adapter reads. This is a *data-level* failure
    (a job tab was already opened) and must be distinguished from
    session-level failures so callers can run tab cleanup on the recoverable
    error path.
    """


class EmptyAdmissionsSnapshotError(SnapshotContainerMissingError):
    """A batch-bound admissions snapshot contained zero rows (RPAP-S2).

    An empty normalized snapshot is a legitimate standalone result, but it is
    INVALID for a run linked to a census/recovery batch: the batch represents
    an occupied patient who must have at least one admission. Subclassing
    :class:`SnapshotContainerMissingError` keeps the frozen failure taxonomy —
    the shared classifier already maps it to ``("invalid_payload", False)`` —
    so no new failure choice is introduced. The message is a fixed sanitized
    constant and never carries patient or clinical context.
    """

    SANITIZED_MESSAGE = "admissions snapshot empty for batch-bound capture"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.SANITIZED_MESSAGE)


def ensure_nonempty_batch_admissions(
    batch_id: int | None, snapshot: list[dict[str, Any]]
) -> None:
    """RPAP-S2 R2: shared contextual rule for BOTH ingestion workers.

    Raises :class:`EmptyAdmissionsSnapshotError` when a capture linked to a
    census/recovery batch (``batch_id is not None``) returns an empty
    normalized snapshot. Standalone captures (``batch_id is None``) keep the
    explicit empty-result contract. Call this immediately after extraction
    and BEFORE any persistence or success bookkeeping so the existing
    failure/retry/cleanup path runs with zero clinical effects.
    """
    if batch_id is not None and not snapshot:
        raise EmptyAdmissionsSnapshotError()


def is_playwright_timeout_error(exc: BaseException) -> bool:
    """Return True if ``exc`` is a Playwright ``TimeoutError``.

    PSW-S17 R1 (second corrective closure): uses ``isinstance()`` against
    the real public ``playwright.sync_api.TimeoutError`` type (lazy import,
    no browser launch). Returns ``False`` if Playwright is not installable
    in the runtime — never falls back to class-name/module-prefix duck
    typing.
    """
    pt = _get_playwright_timeout_error()
    return pt is not None and isinstance(exc, pt)
