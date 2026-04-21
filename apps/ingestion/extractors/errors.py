"""Domain errors for evolution extraction (Slice S1)."""

from __future__ import annotations


class ExtractionError(Exception):
    """Base error for evolution extraction failures."""


class ExtractionTimeoutError(ExtractionError):
    """Extraction exceeded the configured timeout."""


class InvalidJsonError(ExtractionError):
    """Extractor returned invalid or unparseable JSON."""
