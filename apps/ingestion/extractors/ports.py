"""Port interface for evolution extraction (Slice S1)."""

from __future__ import annotations

import abc
from typing import Any


class EvolutionExtractorPort(abc.ABC):
    """Abstract contract for extracting clinical evolutions.

    Implementations must:
    - Accept patient_record, start_date, end_date as parameters.
    - Return a list of normalised evolution dicts ready for ingestion.
    - Raise typed ExtractionError subclasses on failure.
    """

    @abc.abstractmethod
    def extract_evolutions(
        self,
        *,
        patient_record: str,
        start_date: str,
        end_date: str,
        timeout: int = 90,
    ) -> list[dict[str, Any]]:
        """Extract evolutions for a patient within a date interval.

        Args:
            patient_record: Patient record identifier (prontuário).
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
            timeout: Maximum execution time in seconds.

        Returns:
            List of normalised evolution dicts with canonical field names.

        Raises:
            ExtractionTimeoutError: When extraction exceeds timeout.
            ExtractionError: On any other extraction failure.
        """
        raise NotImplementedError
