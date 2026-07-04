"""Domain errors for evolution extraction (Slice S1)."""

from __future__ import annotations


class ExtractionError(Exception):
    """Base error for evolution extraction failures."""


class ExtractionTimeoutError(ExtractionError):
    """Extraction exceeded the configured timeout."""


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
