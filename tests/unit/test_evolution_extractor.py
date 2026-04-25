"""Tests for EvolutionExtractorPort and PlaywrightEvolutionExtractor (Slice S1 + S1.5).

TDD: tests first (RED), then implement (GREEN), then refactor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from apps.ingestion.extractors.errors import (
    ExtractionError,
    ExtractionTimeoutError,
    InvalidJsonError,
)
from apps.ingestion.extractors.playwright_extractor import PlaywrightEvolutionExtractor
from apps.ingestion.extractors.ports import EvolutionExtractorPort

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_PATH2_ITEM: dict[str, Any] = {
    "createdAt": "2024-06-10T08:30:00",
    "signedAt": "2024-06-10T08:35:00",
    "content": "Paciente estável, sem intercorrências.",
    "createdBy": "Dr. Carlos",
    "type": "medical",
    "sourceIndex": 1,
    "confidence": "high",
    "signatureLine": "Dr. Carlos CRM-SP 123456 em: 10/06/2024 08:35:00",
    "admissionKey": "ADM001",
    "admissionRowIndex": 0,
    "admissionStart": "2024-06-01",
    "admissionEnd": "2024-06-15",
    "chunkStart": "2024-06-01",
    "chunkEnd": "2024-06-15",
    "requestedStart": "2024-06-01",
    "requestedEnd": "2024-06-15",
}

SAMPLE_PATH2_ITEM_LEGACY_TYPE: dict[str, Any] = {
    "createdAt": "2024-06-10T10:00:00",
    "signedAt": "",
    "content": "Sessão de fisioterapia realizada.",
    "createdBy": "Ana Fisio",
    "type": "phisiotherapy",
    "sourceIndex": 2,
    "confidence": "high",
    "signatureLine": "Ana CREFITO-3 78901 em: 10/06/2024 10:00:00",
    "admissionKey": "ADM001",
    "admissionRowIndex": 0,
    "admissionStart": "2024-06-01",
    "admissionEnd": None,
    "chunkStart": "2024-06-01",
    "chunkEnd": "2024-06-15",
    "requestedStart": "2024-06-01",
    "requestedEnd": "2024-06-15",
}


def _build_extractor(tmp_path: Path) -> PlaywrightEvolutionExtractor:
    """Create an extractor pointing to a fake script path."""
    fake_script = tmp_path / "path2.py"
    fake_script.write_text("# placeholder")
    return PlaywrightEvolutionExtractor(script_path=str(fake_script))


def _write_json_output(tmp_path: Path, items: list[dict[str, Any]]) -> Path:
    """Write a JSON file simulating path2 output."""
    json_path = tmp_path / "output.json"
    json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    return json_path


# ---------------------------------------------------------------------------
# 1. Port contract tests (interface behaviour)
# ---------------------------------------------------------------------------


class TestEvolutionExtractorPortContract:
    """Verify EvolutionExtractorPort defines the expected interface."""

    def test_is_abstract(self):
        """EvolutionExtractorPort should not be instantiable directly."""
        with pytest.raises(TypeError):
            EvolutionExtractorPort()  # type: ignore[abstract]

    def test_has_extract_method(self):
        """Port must define extract_evolutions method."""
        assert hasattr(EvolutionExtractorPort, "extract_evolutions")

    def test_subclass_must_implement_extract(self):
        """Subclass without extract_evolutions raises TypeError."""

        class IncompleteExtractor(EvolutionExtractorPort):
            pass

        with pytest.raises(TypeError):
            IncompleteExtractor()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# 2. PlaywrightEvolutionExtractor — normalisation tests
# ---------------------------------------------------------------------------


class TestNormalizeEvolutionItem:
    """Test normalisation of a single path2.py JSON item."""

    def test_maps_required_fields(self, tmp_path: Path):
        """Normalised item must have canonical field names."""
        extractor = _build_extractor(tmp_path)
        result = extractor._normalize_item(SAMPLE_PATH2_ITEM)

        assert result["happened_at"] == "2024-06-10T08:30:00"
        assert result["signed_at"] == "2024-06-10T08:35:00"
        assert result["content_text"] == "Paciente estável, sem intercorrências."
        assert result["author_name"] == "Dr. Carlos"
        assert result["profession_type"] == "medica"
        assert result["signature_line"] == SAMPLE_PATH2_ITEM["signatureLine"]
        assert result["admission_key"] == "ADM001"
        assert result["source_system"] == "tasy"

    def test_preserves_raw_payload(self, tmp_path: Path):
        """Raw original item should be preserved for audit."""
        extractor = _build_extractor(tmp_path)
        result = extractor._normalize_item(SAMPLE_PATH2_ITEM)
        assert result["raw_payload"] == SAMPLE_PATH2_ITEM

    def test_maps_chunk_metadata(self, tmp_path: Path):
        """Chunk window metadata should be preserved."""
        extractor = _build_extractor(tmp_path)
        result = extractor._normalize_item(SAMPLE_PATH2_ITEM)
        assert result["chunk_start"] == "2024-06-01"
        assert result["chunk_end"] == "2024-06-15"

    def test_empty_signed_at_becomes_none(self, tmp_path: Path):
        """Empty signedAt string should normalise to None."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM, "signedAt": ""}
        result = extractor._normalize_item(item)
        assert result["signed_at"] is None

    def test_none_signed_at_stays_none(self, tmp_path: Path):
        """None signedAt should stay None."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM, "signedAt": None}
        result = extractor._normalize_item(item)
        assert result["signed_at"] is None

    def test_legacy_phisiotherapy_type_maps_to_fisioterapia(self, tmp_path: Path):
        """Legacy 'phisiotherapy' token must be normalized to 'fisioterapia'."""
        extractor = _build_extractor(tmp_path)
        result = extractor._normalize_item(SAMPLE_PATH2_ITEM_LEGACY_TYPE)
        assert result["profession_type"] == "fisioterapia"

    def test_type_medical_maps_to_medica(self, tmp_path: Path):
        """'medical' should map to 'medica'."""
        extractor = _build_extractor(tmp_path)
        result = extractor._normalize_item(SAMPLE_PATH2_ITEM)
        assert result["profession_type"] == "medica"

    def test_type_nursing_maps_to_enfermagem(self, tmp_path: Path):
        """'nursing' should map to 'enfermagem'."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM, "type": "nursing"}
        result = extractor._normalize_item(item)
        assert result["profession_type"] == "enfermagem"

    def test_type_nutrition_maps_to_nutricao(self, tmp_path: Path):
        """'nutrition' should map to 'nutricao'."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM, "type": "nutrition"}
        result = extractor._normalize_item(item)
        assert result["profession_type"] == "nutricao"

    def test_type_speech_therapy_maps_to_fonoaudiologia(self, tmp_path: Path):
        """'speech_therapy' should map to 'fonoaudiologia'."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM, "type": "speech_therapy"}
        result = extractor._normalize_item(item)
        assert result["profession_type"] == "fonoaudiologia"

    def test_type_dentistry_maps_to_odontologia(self, tmp_path: Path):
        """'dentistry' should map to 'odontologia'."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM, "type": "dentistry"}
        result = extractor._normalize_item(item)
        assert result["profession_type"] == "odontologia"

    def test_unknown_type_maps_to_other(self, tmp_path: Path):
        """Unknown type should map to 'other'."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM, "type": "unknown_specialty"}
        result = extractor._normalize_item(item)
        assert result["profession_type"] == "other"


# ---------------------------------------------------------------------------
# 3. PlaywrightEvolutionExtractor — collection normalisation
# ---------------------------------------------------------------------------


class TestNormalizeCollection:
    """Test normalisation of a list of path2.py JSON items."""

    def test_empty_list(self, tmp_path: Path):
        extractor = _build_extractor(tmp_path)
        assert extractor._normalize_collection([]) == []

    def test_multiple_items(self, tmp_path: Path):
        extractor = _build_extractor(tmp_path)
        items = [SAMPLE_PATH2_ITEM, SAMPLE_PATH2_ITEM_LEGACY_TYPE]
        result = extractor._normalize_collection(items)
        assert len(result) == 2
        assert result[0]["profession_type"] == "medica"
        assert result[1]["profession_type"] == "fisioterapia"

    def test_ordering_preserved(self, tmp_path: Path):
        extractor = _build_extractor(tmp_path)
        item_a = {**SAMPLE_PATH2_ITEM, "createdAt": "2024-06-10T08:00:00"}
        item_b = {**SAMPLE_PATH2_ITEM, "createdAt": "2024-06-10T09:00:00"}
        result = extractor._normalize_collection([item_a, item_b])
        assert result[0]["happened_at"] == "2024-06-10T08:00:00"
        assert result[1]["happened_at"] == "2024-06-10T09:00:00"


# ---------------------------------------------------------------------------
# 4. PlaywrightEvolutionExtractor — JSON validation
# ---------------------------------------------------------------------------


class TestJsonValidation:
    """Test that invalid JSON from subprocess raises proper errors."""

    def test_invalid_json_raises_invalid_json_error(self, tmp_path: Path):
        extractor = _build_extractor(tmp_path)
        bad_path = tmp_path / "bad.json"
        bad_path.write_text("NOT JSON {{{")

        with pytest.raises(InvalidJsonError):
            extractor._parse_json_output(bad_path)

    def test_json_not_list_raises_invalid_json_error(self, tmp_path: Path):
        """JSON must be a list, not an object."""
        extractor = _build_extractor(tmp_path)
        obj_path = tmp_path / "object.json"
        obj_path.write_text('{"key": "value"}')

        with pytest.raises(InvalidJsonError):
            extractor._parse_json_output(obj_path)

    def test_missing_file_raises_invalid_json_error(self, tmp_path: Path):
        extractor = _build_extractor(tmp_path)
        missing = tmp_path / "does_not_exist.json"

        with pytest.raises(InvalidJsonError):
            extractor._parse_json_output(missing)


# ---------------------------------------------------------------------------
# 5. PlaywrightEvolutionExtractor — subprocess error handling
# ---------------------------------------------------------------------------


class TestSubprocessErrors:
    """Test that subprocess failures map to proper domain errors."""

    def test_timeout_raises_extraction_timeout_error(self, tmp_path: Path):
        """Subprocess timeout should raise ExtractionTimeoutError."""
        extractor = _build_extractor(tmp_path)

        with patch("apps.ingestion.extractors.playwright_extractor.subprocess.run") as mock_run:
            import subprocess

            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["python"], timeout=90)

            with pytest.raises(ExtractionTimeoutError) as exc_info:
                extractor.extract_evolutions(
                    patient_record="123",
                    start_date="2024-06-01",
                    end_date="2024-06-15",
                )

            assert "90" in str(exc_info.value)

    def test_timeout_includes_stdout_stderr_preview(self, tmp_path: Path):
        """Timeout message should include partial stdout/stderr for diagnosis."""
        extractor = _build_extractor(tmp_path)

        with patch("apps.ingestion.extractors.playwright_extractor.subprocess.run") as mock_run:
            import subprocess

            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["python"],
                timeout=300,
                output="log parcial de progresso",
                stderr="erro parcial",
            )

            with pytest.raises(ExtractionTimeoutError) as exc_info:
                extractor.extract_evolutions(
                    patient_record="123",
                    start_date="2024-06-01",
                    end_date="2024-06-15",
                )

            message = str(exc_info.value)
            assert "timed out" in message
            assert "stdout" in message
            assert "stderr" in message
            assert "log parcial de progresso" in message
            assert "erro parcial" in message

    def test_nonzero_exit_raises_extraction_error(self, tmp_path: Path):
        """Non-zero exit code should raise ExtractionError."""
        extractor = _build_extractor(tmp_path)

        with patch("apps.ingestion.extractors.playwright_extractor.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "Playwright crash"
            mock_run.return_value = mock_result

            with pytest.raises(ExtractionError) as exc_info:
                extractor.extract_evolutions(
                    patient_record="123",
                    start_date="2024-06-01",
                    end_date="2024-06-15",
                )

            assert "code 1" in str(exc_info.value)

    def test_nonzero_exit_includes_stdout_stderr_preview(self, tmp_path: Path):
        """Non-zero exit should include partial stdout/stderr for diagnosis."""
        extractor = _build_extractor(tmp_path)

        with patch("apps.ingestion.extractors.playwright_extractor.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = "stdout parcial"
            mock_result.stderr = "stderr parcial"
            mock_run.return_value = mock_result

            with pytest.raises(ExtractionError) as exc_info:
                extractor.extract_evolutions(
                    patient_record="123",
                    start_date="2024-06-01",
                    end_date="2024-06-15",
                )

            message = str(exc_info.value)
            assert "code 1" in message
            assert "stdout" in message
            assert "stderr" in message
            assert "stdout parcial" in message
            assert "stderr parcial" in message

    def test_generic_exception_raises_extraction_error(self, tmp_path: Path):
        """Generic exceptions should be wrapped in ExtractionError."""
        extractor = _build_extractor(tmp_path)

        with patch("apps.ingestion.extractors.playwright_extractor.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("No such file")

            with pytest.raises(ExtractionError):
                extractor.extract_evolutions(
                    patient_record="123",
                    start_date="2024-06-01",
                    end_date="2024-06-15",
                )


# ---------------------------------------------------------------------------
# 6. PlaywrightEvolutionExtractor — happy path (mocked subprocess)
# ---------------------------------------------------------------------------


class TestExtractEvolutionsHappyPath:
    """Test full extraction flow with mocked subprocess."""

    def test_returns_normalised_items(self, tmp_path: Path):
        """Successful extraction returns normalised evolution items."""
        json_output = tmp_path / "output.json"
        json_output.write_text(
            json.dumps([SAMPLE_PATH2_ITEM], ensure_ascii=False, indent=2)
        )

        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")

        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            # Simulate path2 writing JSON to --json-output path
            json_arg_idx = cmd.index("--json-output") + 1
            target_path = Path(cmd[json_arg_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(json.dumps([SAMPLE_PATH2_ITEM], ensure_ascii=False, indent=2))
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            results = extractor.extract_evolutions(
                patient_record="1234567",
                start_date="2024-06-01",
                end_date="2024-06-15",
            )

        assert len(results) == 1
        assert results[0]["happened_at"] == "2024-06-10T08:30:00"
        assert results[0]["content_text"] == "Paciente estável, sem intercorrências."
        assert results[0]["profession_type"] == "medica"
        assert results[0]["admission_key"] == "ADM001"

    def test_empty_result_returns_empty_list(self, tmp_path: Path):
        """When path2 returns empty list, extractor returns empty list."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            json_arg_idx = cmd.index("--json-output") + 1
            target_path = Path(cmd[json_arg_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text("[]")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            results = extractor.extract_evolutions(
                patient_record="123",
                start_date="2024-06-01",
                end_date="2024-06-15",
            )

        assert results == []

    def test_propagates_patient_source_key(self, tmp_path: Path):
        """patient_record must appear as patient_source_key in each normalised item."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            json_arg_idx = cmd.index("--json-output") + 1
            target_path = Path(cmd[json_arg_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                json.dumps([SAMPLE_PATH2_ITEM], ensure_ascii=False, indent=2)
            )
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            results = extractor.extract_evolutions(
                patient_record="1234567",
                start_date="2024-06-01",
                end_date="2024-06-15",
            )

        assert len(results) == 1
        assert results[0]["patient_source_key"] == "1234567"

    def test_date_conversion_to_ddmmyyyy(self, tmp_path: Path):
        """start_date and end_date in YYYY-MM-DD must be converted to DD/MM/YYYY for path2."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        captured_cmd: list[str] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured_cmd.extend(cmd)
            json_arg_idx = cmd.index("--json-output") + 1
            target_path = Path(cmd[json_arg_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text("[]")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            extractor.extract_evolutions(
                patient_record="123",
                start_date="2024-06-01",
                end_date="2024-06-15",
            )

        start_idx = captured_cmd.index("--start-date") + 1
        end_idx = captured_cmd.index("--end-date") + 1
        assert captured_cmd[start_idx] == "01/06/2024"
        assert captured_cmd[end_idx] == "15/06/2024"

    def test_extract_evolutions_uses_longer_default_timeout(self, tmp_path: Path):
        """Default timeout should allow slow report generation windows."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        captured_kwargs: dict[str, Any] = {}

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            captured_kwargs.update(kwargs)
            json_arg_idx = cmd.index("--json-output") + 1
            target_path = Path(cmd[json_arg_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text("[]")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            extractor.extract_evolutions(
                patient_record="123",
                start_date="2024-06-01",
                end_date="2024-06-15",
            )

        assert captured_kwargs.get("timeout") == 600

    def test_date_conversion_single_digit_days(self, tmp_path: Path):
        """Dates with single-digit days/months should be zero-padded in DD/MM/YYYY."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        captured_cmd: list[str] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured_cmd.extend(cmd)
            json_arg_idx = cmd.index("--json-output") + 1
            target_path = Path(cmd[json_arg_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text("[]")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            extractor.extract_evolutions(
                patient_record="123",
                start_date="2024-03-05",
                end_date="2024-12-25",
            )

        start_idx = captured_cmd.index("--start-date") + 1
        end_idx = captured_cmd.index("--end-date") + 1
        assert captured_cmd[start_idx] == "05/03/2024"
        assert captured_cmd[end_idx] == "25/12/2024"

    def test_date_conversion_in_happy_path(self, tmp_path: Path):
        """Verify date conversion works end-to-end in the happy path test."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        captured_cmd: list[str] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured_cmd.extend(cmd)
            json_arg_idx = cmd.index("--json-output") + 1
            target_path = Path(cmd[json_arg_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                json.dumps([SAMPLE_PATH2_ITEM], ensure_ascii=False, indent=2)
            )
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            results = extractor.extract_evolutions(
                patient_record="1234567",
                start_date="2024-06-01",
                end_date="2024-06-15",
            )

        assert len(results) == 1
        # Also verify dates were converted in the command
        start_idx = captured_cmd.index("--start-date") + 1
        assert captured_cmd[start_idx] == "01/06/2024"
        # And patient_source_key is present
        assert results[0]["patient_source_key"] == "1234567"


class TestRequiredFieldValidation:
    """Test that items missing required fields raise InvalidJsonError."""

    def test_missing_created_at_raises_error(self, tmp_path: Path):
        """Item without createdAt must fail validation."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM}
        del item["createdAt"]

        with pytest.raises(InvalidJsonError, match="createdAt"):
            extractor._normalize_item(item)

    def test_missing_content_raises_error(self, tmp_path: Path):
        """Item without content must fail validation."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM}
        del item["content"]

        with pytest.raises(InvalidJsonError, match="content"):
            extractor._normalize_item(item)

    def test_missing_admission_key_raises_error(self, tmp_path: Path):
        """Item without admissionKey must fail validation."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM}
        del item["admissionKey"]

        with pytest.raises(InvalidJsonError, match="admissionKey"):
            extractor._normalize_item(item)

    def test_missing_type_raises_error(self, tmp_path: Path):
        """Item without type must fail validation."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM}
        del item["type"]

        with pytest.raises(InvalidJsonError, match="type"):
            extractor._normalize_item(item)

    def test_empty_created_at_raises_error(self, tmp_path: Path):
        """Item with empty createdAt must fail validation."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM, "createdAt": ""}

        with pytest.raises(InvalidJsonError, match="createdAt"):
            extractor._normalize_item(item)

    def test_empty_admission_key_raises_error(self, tmp_path: Path):
        """Item with empty admissionKey must fail validation."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM, "admissionKey": ""}

        with pytest.raises(InvalidJsonError, match="admissionKey"):
            extractor._normalize_item(item)

    def test_valid_item_passes_validation(self, tmp_path: Path):
        """A complete valid item should pass without errors."""
        extractor = _build_extractor(tmp_path)
        # Should not raise
        result = extractor._normalize_item(SAMPLE_PATH2_ITEM)
        assert result["happened_at"] == "2024-06-10T08:30:00"

    def test_collection_fails_on_first_invalid_item(self, tmp_path: Path):
        """_normalize_collection should fail if any item is invalid."""
        extractor = _build_extractor(tmp_path)
        bad_item = {**SAMPLE_PATH2_ITEM}
        del bad_item["admissionKey"]

        with pytest.raises(InvalidJsonError):
            extractor._normalize_collection([SAMPLE_PATH2_ITEM, bad_item])


# ---------------------------------------------------------------------------
# 7. Required field validation — createdBy and signatureLine (S1.6)
# ---------------------------------------------------------------------------


class TestCreatedByAndSignatureLineValidation:
    """Test that createdBy and signatureLine are required fields."""

    def test_missing_created_by_raises_error(self, tmp_path: Path):
        """Item without createdBy must fail validation."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM}
        del item["createdBy"]

        with pytest.raises(InvalidJsonError, match="createdBy"):
            extractor._normalize_item(item)

    def test_missing_signature_line_raises_error(self, tmp_path: Path):
        """Item without signatureLine must fail validation."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM}
        del item["signatureLine"]

        with pytest.raises(InvalidJsonError, match="signatureLine"):
            extractor._normalize_item(item)

    def test_empty_created_by_raises_error(self, tmp_path: Path):
        """Item with empty createdBy must fail validation."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM, "createdBy": ""}

        with pytest.raises(InvalidJsonError, match="createdBy"):
            extractor._normalize_item(item)

    def test_empty_signature_line_raises_error(self, tmp_path: Path):
        """Item with empty signatureLine must fail validation."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM, "signatureLine": ""}

        with pytest.raises(InvalidJsonError, match="signatureLine"):
            extractor._normalize_item(item)

    def test_error_message_lists_all_missing_fields(self, tmp_path: Path):
        """Error message should name all missing fields."""
        extractor = _build_extractor(tmp_path)
        item = {**SAMPLE_PATH2_ITEM}
        del item["createdBy"]
        del item["signatureLine"]

        with pytest.raises(InvalidJsonError, match="createdBy") as exc_info:
            extractor._normalize_item(item)

        assert "signatureLine" in str(exc_info.value)
        assert "createdBy" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 8. PlaywrightEvolutionExtractor — admission snapshot tests (Slice S1)


# ---------------------------------------------------------------------------
# 8. PlaywrightEvolutionExtractor — admission snapshot tests (Slice S1)
# ---------------------------------------------------------------------------


class TestGetAdmissionSnapshot:
    """Test get_admission_snapshot method for explicit admission snapshot extraction."""

    SAMPLE_ADMISSION_SNAPSHOT: list[dict[str, Any]] = [
        {
            "admissionKey": "ADM001",
            "admissionStart": "2024-06-01",
            "admissionEnd": "2024-06-15",
            "ward": "UTI Adulto",
            "bed": "12",
        },
        {
            "admissionKey": "ADM002",
            "admissionStart": "2024-07-01",
            "admissionEnd": None,
            "ward": "Clínica Médica",
            "bed": "05",
        },
    ]

    def test_returns_normalised_admission_list(self, tmp_path: Path):
        """Successful snapshot extraction returns normalised admission list."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            # Simulate path2 writing admission snapshot to --admissions-output path
            adm_idx = cmd.index("--admissions-output") + 1
            target_path = Path(cmd[adm_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(json.dumps(self.SAMPLE_ADMISSION_SNAPSHOT, ensure_ascii=False))
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            results = extractor.get_admission_snapshot(
                patient_record="1234567",
                start_date="2024-06-01",
                end_date="2024-07-31",
            )

        assert len(results) == 2
        assert results[0]["admission_key"] == "ADM001"
        assert results[0]["admission_start"] == "2024-06-01"
        assert results[0]["admission_end"] == "2024-06-15"
        assert results[0]["ward"] == "UTI Adulto"
        assert results[0]["bed"] == "12"
        assert results[1]["admission_end"] is None

    def test_missing_admissions_file_raises_error(self, tmp_path: Path):
        """Missing admission snapshot file should raise ExtractionError."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            # Do NOT write the --admissions-output file
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            with pytest.raises(ExtractionError, match="not found"):
                extractor.get_admission_snapshot(
                    patient_record="123",
                    start_date="2024-06-01",
                    end_date="2024-07-31",
                )

    def test_invalid_json_raises_invalid_json_error(self, tmp_path: Path):
        """Invalid JSON in admission snapshot should raise InvalidJsonError."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            adm_idx = cmd.index("--admissions-output") + 1
            target_path = Path(cmd[adm_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text("NOT JSON {{{")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            with pytest.raises(InvalidJsonError):
                extractor.get_admission_snapshot(
                    patient_record="123",
                    start_date="2024-06-01",
                    end_date="2024-07-31",
                )

    def test_nonzero_exit_raises_extraction_error(self, tmp_path: Path):
        """Non-zero exit code should raise ExtractionError."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run"
        ) as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "Playwright crash"
            mock_run.return_value = mock_result

            with pytest.raises(ExtractionError, match="code 1"):
                extractor.get_admission_snapshot(
                    patient_record="123",
                    start_date="2024-06-01",
                    end_date="2024-07-31",
                )

    def test_snapshot_nonzero_exit_includes_stdout_stderr_preview(self, tmp_path: Path):
        """Non-zero snapshot failure should include stdout/stderr context."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run"
        ) as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = "stdout parcial"
            mock_result.stderr = "stderr parcial"
            mock_run.return_value = mock_result

            with pytest.raises(ExtractionError) as exc_info:
                extractor.get_admission_snapshot(
                    patient_record="123",
                    start_date="2024-06-01",
                    end_date="2024-07-31",
                )

            message = str(exc_info.value)
            assert "code 1" in message
            assert "stdout" in message
            assert "stderr" in message
            assert "stdout parcial" in message
            assert "stderr parcial" in message

    def test_timeout_raises_extraction_timeout_error(self, tmp_path: Path):
        """Subprocess timeout should raise ExtractionTimeoutError."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run"
        ) as mock_run:
            import subprocess

            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["python"], timeout=120)

            with pytest.raises(ExtractionTimeoutError):
                extractor.get_admission_snapshot(
                    patient_record="123",
                    start_date="2024-06-01",
                    end_date="2024-07-31",
                )

    def test_snapshot_timeout_includes_stdout_stderr_preview(self, tmp_path: Path):
        """Admission timeout should include partial stdout/stderr for diagnosis."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run"
        ) as mock_run:
            import subprocess

            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["python"],
                timeout=120,
                output="stdout parcial",
                stderr="stderr parcial",
            )

            with pytest.raises(ExtractionTimeoutError) as exc_info:
                extractor.get_admission_snapshot(
                    patient_record="123",
                    start_date="2024-06-01",
                    end_date="2024-07-31",
                )

            message = str(exc_info.value)
            assert "stdout" in message
            assert "stderr" in message
            assert "stdout parcial" in message
            assert "stderr parcial" in message

    def test_date_conversion_in_snapshot_extraction(self, tmp_path: Path):
        """Dates should be converted to DD/MM/YYYY for path2."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        captured_cmd: list[str] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured_cmd.extend(cmd)
            adm_idx = cmd.index("--admissions-output") + 1
            target_path = Path(cmd[adm_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(json.dumps(self.SAMPLE_ADMISSION_SNAPSHOT))
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            extractor.get_admission_snapshot(
                patient_record="123",
                start_date="2024-06-01",
                end_date="2024-07-31",
            )

        start_idx = captured_cmd.index("--start-date") + 1
        end_idx = captured_cmd.index("--end-date") + 1
        assert captured_cmd[start_idx] == "01/06/2024"
        assert captured_cmd[end_idx] == "31/07/2024"

    def test_empty_snapshot_returns_empty_list(self, tmp_path: Path):
        """Empty admission snapshot should return empty list."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            adm_idx = cmd.index("--admissions-output") + 1
            target_path = Path(cmd[adm_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text("[]")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            results = extractor.get_admission_snapshot(
                patient_record="123",
                start_date="2024-06-01",
                end_date="2024-07-31",
            )

        assert results == []


# ---------------------------------------------------------------------------
# 9. Slice S1 Fix — admissions-only mode tests (TDD RED)
# ---------------------------------------------------------------------------


class TestAdmissionsOnlyMode:
    """Verify get_admission_snapshot() passes --admissions-only flag."""

    SAMPLE_ADMISSION_SNAPSHOT: list[dict[str, Any]] = [
        {
            "admissionKey": "ADM001",
            "admissionStart": "2024-06-01",
            "admissionEnd": "2024-06-15",
            "ward": "UTI Adulto",
            "bed": "12",
        },
    ]

    def test_passes_admissions_only_flag(self, tmp_path: Path):
        """Command must include --admissions-only flag."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        captured_cmd: list[str] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured_cmd.extend(cmd)
            # Simulate admissions-only mode writing file
            try:
                adm_idx = cmd.index("--admissions-output") + 1
                target_path = Path(cmd[adm_idx])
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(
                    json.dumps(self.SAMPLE_ADMISSION_SNAPSHOT, ensure_ascii=False)
                )
            except (ValueError, IndexError):
                pass
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            extractor.get_admission_snapshot(
                patient_record="123",
                start_date="2024-06-01",
                end_date="2024-06-15",
            )

        assert "--admissions-only" in captured_cmd, (
            f"Expected --admissions-only in command, got: {captured_cmd}"
        )

    def test_admissions_only_mode_works_without_evolutions(self, tmp_path: Path):
        """Snapshot extraction should succeed even if no evolutions exist.

        This test verifies that --admissions-only mode allows extraction to
        complete without requiring evolutions (i.e., no chunk/pdf/evolution flow).
        """
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            # Verify admissions-only is used (no --json-output expected)
            assert "--admissions-only" in cmd
            # Write the snapshot file as if path2 completed in admissions-only mode
            adm_idx = cmd.index("--admissions-output") + 1
            target_path = Path(cmd[adm_idx])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                json.dumps(self.SAMPLE_ADMISSION_SNAPSHOT, ensure_ascii=False)
            )
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            results = extractor.get_admission_snapshot(
                patient_record="123",
                start_date="2024-06-01",
                end_date="2024-06-15",
            )

        assert len(results) == 1
        assert results[0]["admission_key"] == "ADM001"

    def test_extract_evolutions_does_not_pass_admissions_only(self, tmp_path: Path):
        """extract_evolutions() should NOT include --admissions-only flag."""
        fake_script = tmp_path / "path2.py"
        fake_script.write_text("# fake")
        extractor = PlaywrightEvolutionExtractor(script_path=str(fake_script))

        captured_cmd: list[str] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured_cmd.extend(cmd)
            # Write empty evolutions file for extract_evolutions path
            try:
                json_idx = cmd.index("--json-output") + 1
                target_path = Path(cmd[json_idx])
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text("[]")
            except (ValueError, IndexError):
                pass
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.subprocess.run",
            side_effect=fake_run,
        ):
            extractor.extract_evolutions(
                patient_record="123",
                start_date="2024-06-01",
                end_date="2024-06-15",
            )

        assert "--admissions-only" not in captured_cmd, (
            f"extract_evolutions() should NOT pass --admissions-only: {captured_cmd}"
        )
