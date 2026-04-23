"""Admission snapshot parser (Slice S1 - GREEN phase).

Parses the raw JSON snapshot of patient admissions produced by path2.py
and normalises it to canonical format for ingestion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.ingestion.extractors.errors import (
    ExtractionError,
    InvalidJsonError,
)

# ---------------------------------------------------------------------------
# Canonical field names
# ---------------------------------------------------------------------------

_CANONICAL_FIELDS = {
    "admission_key": "admissionKey",
    "admission_start": "admissionStart",
    "admission_end": "admissionEnd",
    "ward": "ward",
    "bed": "bed",
}

_REQUIRED_FIELDS = frozenset(["admissionKey", "admissionStart"])


class AdmissionSnapshotParser:
    """Parse and normalise admission snapshot JSON from path2.py."""

    def parse_file(self, json_path: Path) -> list[dict[str, Any]]:
        """Read and parse a JSON file containing admission snapshot.

        Args:
            json_path: Path to JSON file with admission snapshot.

        Returns:
            List of normalised admission dicts.

        Raises:
            ExtractionError: If file is not found.
            InvalidJsonError: If JSON is invalid or not a list.
            ExtractionError: If a required field is missing in an item.
        """
        if not json_path.exists():
            raise ExtractionError(
                f"Admission snapshot file not found: {json_path}"
            )
        return self.parse_json_string(json_path.read_text(encoding="utf-8"))

    def parse_json_string(self, json_text: str) -> list[dict[str, Any]]:
        """Parse JSON string containing admission snapshot.

        Args:
            json_text: Raw JSON string with admission snapshot.

        Returns:
            List of normalised admission dicts.

        Raises:
            InvalidJsonError: If JSON is invalid or not a list.
            ExtractionError: If a required field is missing in an item.
        """
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise InvalidJsonError(
                f"Invalid JSON in admission snapshot: {exc}"
            ) from exc

        if not isinstance(data, list):
            raise InvalidJsonError(
                f"Admission snapshot JSON root must be a list, got {type(data).__name__}"
            )

        result: list[dict[str, Any]] = []
        for idx, item in enumerate(data):
            normalised = self._normalise_item(item, index=idx)
            result.append(normalised)

        return result

    def _normalise_item(
        self,
        item: dict[str, Any],
        *,
        index: int = 0,
    ) -> dict[str, Any]:
        """Normalise a single admission item.

        Args:
            item: Raw admission dict from snapshot.
            index: Index of item in the list (for error messages).

        Returns:
            Normalised dict with canonical field names.

        Raises:
            ExtractionError: If required fields are missing or empty.
        """
        # Validate required fields
        missing: list[str] = []
        for field in _REQUIRED_FIELDS:
            value = item.get(field)
            if value is None or (isinstance(value, str) and value.strip() == ""):
                missing.append(field)

        if missing:
            raise ExtractionError(
                f"Missing required field(s) in admission item[{index}]: {', '.join(missing)}"
            )

        # Normalise optional fields with safe defaults
        return {
            "admission_key": item["admissionKey"],
            "admission_start": item["admissionStart"],
            "admission_end": item.get("admissionEnd") or None,
            "ward": item.get("ward") or "",
            "bed": item.get("bed") or "",
        }