"""Shared contract for historical extraction services.

Provides the `ExtractionResult` dataclass used by admission and death
historical extraction services to return structured success/failure
metadata without relying on CLI exit codes or stdout parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass
class ExtractionResult:
    """Structured result for a single historical extraction execution.

    Attributes:
        extraction_type: Machine-readable extraction identifier
            (e.g. ``"admission_extraction"``, ``"death_extraction"``).
        target_start: Inclusive start date of the extraction period.
        target_end: Inclusive end date of the extraction period.
        success: Whether the extraction completed without unrecoverable
            errors.
        metrics: Arbitrary key-value counters from the extraction and
            persistence stages (e.g. ``{"total_records": 42}``).
        failure_reason: Normalized failure category when ``success`` is
            ``False`` (e.g. ``"timeout"``, ``"source_unavailable"``).
            Empty string when ``success`` is ``True``.
        error_message: Safe, user-readable error description. Must not
            contain credentials or sensitive context.
        ingestion_run_id: Optional primary key of the associated
            ``IngestionRun``, if one was created.
    """

    extraction_type: str
    target_start: date
    target_end: date
    success: bool

    metrics: dict[str, Any] = field(default_factory=dict)
    failure_reason: str = ""
    error_message: str = ""
    ingestion_run_id: Optional[int] = None
