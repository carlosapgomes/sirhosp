"""Tests for admission snapshot parsing (Slice S1 - RED phase).

TDD: tests first (RED), then implement (GREEN), then refactor.
These tests define the contract for admission snapshot extraction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apps.ingestion.extractors.errors import (
    ExtractionError,
    InvalidJsonError,
)

# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

SAMPLE_ADMISSION_SNAPSHOT_RAW: list[dict[str, Any]] = [
    {
        "admissionKey": "ADM001",
        "admissionStart": "2024-06-01",
        "admissionEnd": "2024-06-15",
        "ward": "UTI Adulto",
        "bed": "12",
        "rowIndex": 0,
    },
    {
        "admissionKey": "ADM002",
        "admissionStart": "2024-07-01",
        "admissionEnd": None,
        "ward": "Clínica Médica",
        "bed": "05",
        "rowIndex": 1,
    },
    {
        "admissionKey": "ADM003",
        "admissionStart": "2024-03-10",
        "admissionEnd": "2024-03-20",
        "ward": "",
        "bed": "",
        "rowIndex": 2,
    },
]

SAMPLE_ADMISSION_SNAPSHOT_WITH_MISSING_FIELDS: list[dict[str, Any]] = [
    {
        "admissionKey": "ADM001",
        "admissionStart": "2024-06-01",
        # missing admissionEnd
        # missing ward/bed
    },
]

SAMPLE_ADMISSION_SNAPSHOT_EMPTY: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Parser class tests
# ---------------------------------------------------------------------------

class TestAdmissionSnapshotParser:
    """Test AdmissionSnapshotParser normalises raw snapshot data."""

    def test_parses_valid_snapshot(self, tmp_path: Path):
        """Valid snapshot should produce normalised list of admissions."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        json_path = tmp_path / "admissions.json"
        json_path.write_text(json.dumps(SAMPLE_ADMISSION_SNAPSHOT_RAW))

        parser = AdmissionSnapshotParser()
        result = parser.parse_file(json_path)

        assert len(result) == 3
        assert result[0]["admission_key"] == "ADM001"
        assert result[0]["admission_start"] == "2024-06-01"
        assert result[0]["admission_end"] == "2024-06-15"
        assert result[0]["ward"] == "UTI Adulto"
        assert result[0]["bed"] == "12"

    def test_parses_minimal_admission_item(self, tmp_path: Path):
        """Item with only required fields should be accepted."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        minimal_item = [
            {
                "admissionKey": "ADM001",
                "admissionStart": "2024-06-01",
            }
        ]
        json_path = tmp_path / "admissions.json"
        json_path.write_text(json.dumps(minimal_item))

        parser = AdmissionSnapshotParser()
        result = parser.parse_file(json_path)

        assert len(result) == 1
        assert result[0]["admission_key"] == "ADM001"
        assert result[0]["admission_start"] == "2024-06-01"
        assert result[0]["admission_end"] is None
        assert result[0]["ward"] == ""
        assert result[0]["bed"] == ""

    def test_handles_null_admission_end(self, tmp_path: Path):
        """Null admissionEnd should become None in normalised output."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        json_path = tmp_path / "admissions.json"
        json_path.write_text(json.dumps(SAMPLE_ADMISSION_SNAPSHOT_RAW))

        parser = AdmissionSnapshotParser()
        result = parser.parse_file(json_path)

        # Second admission has no end date
        assert result[1]["admission_end"] is None

    def test_handles_empty_ward_and_bed(self, tmp_path: Path):
        """Empty ward/bed should be preserved as empty strings."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        json_path = tmp_path / "admissions.json"
        json_path.write_text(json.dumps(SAMPLE_ADMISSION_SNAPSHOT_RAW))

        parser = AdmissionSnapshotParser()
        result = parser.parse_file(json_path)

        # Third admission has no ward/bed
        assert result[2]["ward"] == ""
        assert result[2]["bed"] == ""

    def test_missing_file_raises_extraction_error(self, tmp_path: Path):
        """Missing snapshot file should raise ExtractionError."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        parser = AdmissionSnapshotParser()
        missing = tmp_path / "nonexistent.json"

        with pytest.raises(ExtractionError, match="not found"):
            parser.parse_file(missing)

    def test_invalid_json_raises_invalid_json_error(self, tmp_path: Path):
        """Non-JSON content should raise InvalidJsonError."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        json_path = tmp_path / "bad.json"
        json_path.write_text("NOT JSON {{{")

        parser = AdmissionSnapshotParser()

        with pytest.raises(InvalidJsonError):
            parser.parse_file(json_path)

    def test_json_object_raises_invalid_json_error(self, tmp_path: Path):
        """JSON root must be a list, not an object."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        json_path = tmp_path / "object.json"
        json_path.write_text('{"admissions": []}')

        parser = AdmissionSnapshotParser()

        with pytest.raises(InvalidJsonError, match="list"):
            parser.parse_file(json_path)

    def test_empty_list_returns_empty_list(self, tmp_path: Path):
        """Empty JSON array should return empty list."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        json_path = tmp_path / "empty.json"
        json_path.write_text("[]")

        parser = AdmissionSnapshotParser()
        result = parser.parse_file(json_path)

        assert result == []

    def test_missing_admission_key_raises_error(self, tmp_path: Path):
        """Item without admissionKey should raise error."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        invalid_item = [
            {
                "admissionStart": "2024-06-01",
            }
        ]
        json_path = tmp_path / "admissions.json"
        json_path.write_text(json.dumps(invalid_item))

        parser = AdmissionSnapshotParser()

        with pytest.raises(ExtractionError, match="admissionKey"):
            parser.parse_file(json_path)

    def test_missing_admission_start_raises_error(self, tmp_path: Path):
        """Item without admissionStart should raise error."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        invalid_item = [
            {
                "admissionKey": "ADM001",
            }
        ]
        json_path = tmp_path / "admissions.json"
        json_path.write_text(json.dumps(invalid_item))

        parser = AdmissionSnapshotParser()

        with pytest.raises(ExtractionError, match="admissionStart"):
            parser.parse_file(json_path)

    def test_empty_admission_key_raises_error(self, tmp_path: Path):
        """Item with empty admissionKey should raise error."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        invalid_item = [
            {
                "admissionKey": "",
                "admissionStart": "2024-06-01",
            }
        ]
        json_path = tmp_path / "admissions.json"
        json_path.write_text(json.dumps(invalid_item))

        parser = AdmissionSnapshotParser()

        with pytest.raises(ExtractionError, match="admissionKey"):
            parser.parse_file(json_path)

    def test_empty_admission_start_raises_error(self, tmp_path: Path):
        """Item with empty admissionStart should raise error."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        invalid_item = [
            {
                "admissionKey": "ADM001",
                "admissionStart": "",
            }
        ]
        json_path = tmp_path / "admissions.json"
        json_path.write_text(json.dumps(invalid_item))

        parser = AdmissionSnapshotParser()

        with pytest.raises(ExtractionError, match="admissionStart"):
            parser.parse_file(json_path)


# ---------------------------------------------------------------------------
# Parse from string tests
# ---------------------------------------------------------------------------

class TestAdmissionSnapshotParserFromString:
    """Test parsing from string input."""

    def test_parse_json_string(self):
        """Should parse JSON string directly."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        parser = AdmissionSnapshotParser()
        result = parser.parse_json_string(
            json.dumps(SAMPLE_ADMISSION_SNAPSHOT_RAW)
        )

        assert len(result) == 3
        assert result[0]["admission_key"] == "ADM001"

    def test_invalid_json_string_raises_error(self):
        """Invalid JSON string should raise InvalidJsonError."""
        from apps.ingestion.extractors.admission_snapshot_parser import (
            AdmissionSnapshotParser,
        )

        parser = AdmissionSnapshotParser()

        with pytest.raises(InvalidJsonError):
            parser.parse_json_string("NOT JSON")