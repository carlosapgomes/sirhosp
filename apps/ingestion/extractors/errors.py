"""Domain errors for evolution extraction (Slice S1)."""

from __future__ import annotations


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


def is_playwright_timeout_error(exc: BaseException) -> bool:
    """Return True if ``exc`` is a Playwright ``TimeoutError``.

    Playwright is not a hard import dependency of this module (the workers
    must remain importable without a running browser stack), so detection is
    done by class name AND module prefix. Real Playwright raises
    ``playwright._impl._errors.TimeoutError``.

    Used at source boundaries (``open_tab``, ``_download_pdf``,
    ``_wait_for_report``) to MAP a Playwright timeout to a typed domain
    timeout (``ExtractionTimeoutError`` subclass) so the outer exception
    crossing the adapter/command boundary is itself typed — not via a
    classifier-side cause/context chain walk (PSW-S17 R2/R3 correction).
    """
    cls = type(exc)
    if cls.__name__ != "TimeoutError":
        return False
    module = getattr(cls, "__module__", "") or ""
    return module.startswith("playwright")
