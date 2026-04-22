"""Playwright evolution extractor adapter.

Encapsulates subprocess execution of the integrated legacy ``path2.py``
connector and maps its JSON output to the canonical ingestion format.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from apps.ingestion.extractors.admission_snapshot_parser import (
    AdmissionSnapshotParser,
)
from apps.ingestion.extractors.errors import (
    ExtractionError,
    ExtractionTimeoutError,
    InvalidJsonError,
)
from apps.ingestion.extractors.ports import EvolutionExtractorPort

# ---------------------------------------------------------------------------
# Date conversion
# ---------------------------------------------------------------------------


def _convert_to_br_date(iso_date: str) -> str:
    """Convert YYYY-MM-DD to DD/MM/YYYY for path2.py.

    Args:
        iso_date: Date string in YYYY-MM-DD format.

    Returns:
        Date string in DD/MM/YYYY format.

    Raises:
        ExtractionError: If the date format is invalid.
    """
    from datetime import datetime

    try:
        dt = datetime.strptime(iso_date.strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise ExtractionError(
            f"Invalid date format: {iso_date!r}. Expected YYYY-MM-DD."
        ) from exc
    return dt.strftime("%d/%m/%Y")


# ---------------------------------------------------------------------------
# Profession type mapping (path2 -> canonical)
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, str] = {
    "medical": "medica",
    "nursing": "enfermagem",
    "phisiotherapy": "fisioterapia",
    "physiotherapy": "fisioterapia",
    "nutrition": "nutricao",
    "speech_therapy": "fonoaudiologia",
    "dentistry": "odontologia",
}


class PlaywrightEvolutionExtractor(EvolutionExtractorPort):
    """Transitional adapter that invokes path2.py via subprocess.

    Args:
        script_path: Absolute path to integrated path2.py script.
        headless: Whether to run Playwright in headless mode.
    """

    def __init__(
        self,
        *,
        script_path: str,
        headless: bool = True,
    ) -> None:
        self._script_path = script_path
        self._headless = headless

    def extract_evolutions(
        self,
        *,
        patient_record: str,
        start_date: str,
        end_date: str,
        timeout: int = 90,
    ) -> list[dict[str, Any]]:
        """Run path2.py subprocess and return normalised evolutions.

        Args:
            patient_record: Patient record ID (propagated as patient_source_key).
            start_date: Start date in YYYY-MM-DD format (converted to DD/MM/YYYY).
            end_date: End date in YYYY-MM-DD format (converted to DD/MM/YYYY).
            timeout: Maximum execution time in seconds.
        """
        br_start = _convert_to_br_date(start_date)
        br_end = _convert_to_br_date(end_date)

        script = Path(self._script_path)
        if not script.exists():
            raise ExtractionError(f"Extractor script not found: {script}")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            json_output_path = tmpdir_path / "evolutions.json"
            pdf_output_path = tmpdir_path / "evolutions.pdf"
            debug_output_path = tmpdir_path / "evolutions.debug.html"
            txt_output_path = tmpdir_path / "evolutions.txt"
            normalized_txt_output_path = tmpdir_path / "evolutions.normalized.txt"
            processed_output_path = tmpdir_path / "evolutions.processed.txt"
            sorted_output_path = tmpdir_path / "evolutions.sorted.txt"

            cmd = [
                sys.executable,
                str(script),
                "--patient-record",
                patient_record,
                "--start-date",
                br_start,
                "--end-date",
                br_end,
                "--output",
                str(pdf_output_path),
                "--debug-output",
                str(debug_output_path),
                "--txt-output",
                str(txt_output_path),
                "--normalized-txt-output",
                str(normalized_txt_output_path),
                "--processed-output",
                str(processed_output_path),
                "--sorted-output",
                str(sorted_output_path),
                "--json-output",
                str(json_output_path),
            ]
            if self._headless:
                cmd.append("--headless")

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise ExtractionTimeoutError(
                    f"Extraction timed out after {exc.timeout}s "
                    f"for patient_record={patient_record}"
                ) from exc
            except Exception as exc:
                raise ExtractionError(
                    f"Failed to execute extractor: {exc}"
                ) from exc

            if result.returncode != 0:
                stderr = result.stderr.strip()
                raise ExtractionError(
                    f"Extractor exited with code {result.returncode}: {stderr}"
                )

            raw_items = self._parse_json_output(json_output_path)
            return self._normalize_collection(raw_items, patient_source_key=patient_record)

    def get_admission_snapshot(
        self,
        *,
        patient_record: str,
        start_date: str,
        end_date: str,
        timeout: int = 120,
    ) -> list[dict[str, Any]]:
        """Extract patient admission snapshot from path2.py.

        Runs path2.py with additional flag to capture the full list of patient
        admissions (independent of the evolutions window) and returns normalised
        admission data.

        Args:
            patient_record: Patient record identifier (prontuário).
            start_date: Start date in YYYY-MM-DD format (converted to DD/MM/YYYY).
            end_date: End date in YYYY-MM-DD format (converted to DD/MM/YYYY).
            timeout: Maximum execution time in seconds.

        Returns:
            List of normalised admission dicts with canonical field names.

        Raises:
            ExtractionTimeoutError: When extraction exceeds timeout.
            ExtractionError: On any other extraction failure (incl. missing snapshot).
            InvalidJsonError: If JSON is invalid or not a list.
        """
        br_start = _convert_to_br_date(start_date)
        br_end = _convert_to_br_date(end_date)

        script = Path(self._script_path)
        if not script.exists():
            raise ExtractionError(f"Extractor script not found: {script}")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            admissions_output_path = tmpdir_path / "admissions.json"

            cmd = [
                sys.executable,
                str(script),
                "--patient-record",
                patient_record,
                "--start-date",
                br_start,
                "--end-date",
                br_end,
                "--admissions-output",
                str(admissions_output_path),
                "--admissions-only",
                "--headless",
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise ExtractionTimeoutError(
                    f"Admission snapshot extraction timed out after {exc.timeout}s "
                    f"for patient_record={patient_record}"
                ) from exc
            except Exception as exc:
                raise ExtractionError(
                    f"Failed to execute extractor for admission snapshot: {exc}"
                ) from exc

            if result.returncode != 0:
                stderr = result.stderr.strip()
                raise ExtractionError(
                    f"Extractor exited with code {result.returncode} during admission "
                    f"snapshot extraction: {stderr}"
                )

            parser = AdmissionSnapshotParser()
            return parser.parse_file(admissions_output_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_json_output(self, json_path: Path) -> list[dict[str, Any]]:
        """Read and validate the JSON output file from path2."""
        try:
            text = json_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except FileNotFoundError as exc:
            raise InvalidJsonError(
                f"Extractor output file not found: {json_path}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise InvalidJsonError(
                f"Invalid JSON from extractor: {exc}"
            ) from exc

        if not isinstance(data, list):
            raise InvalidJsonError(
                f"Expected JSON array, got {type(data).__name__}"
            )

        return data

    def _normalize_collection(
        self,
        items: list[dict[str, Any]],
        *,
        patient_source_key: str = "",
    ) -> list[dict[str, Any]]:
        """Normalise a list of path2 items to canonical format."""
        return [
            self._normalize_item(item, patient_source_key=patient_source_key)
            for item in items
        ]

    def _validate_item(self, item: dict[str, Any]) -> None:
        """Validate that an item has all required fields.

        Raises:
            InvalidJsonError: If a required field is missing or empty.
        """
        required_fields = {
            "createdAt": "happened_at",
            "content": "content_text",
            "createdBy": "author_name",
            "type": "profession_type",
            "signatureLine": "signature_line",
            "admissionKey": "admission_key",
        }
        missing: list[str] = []
        for source_field, canonical_name in required_fields.items():
            value = item.get(source_field)
            if value is None or (isinstance(value, str) and value.strip() == ""):
                missing.append(f"{source_field} (canonical: {canonical_name})")
        if missing:
            raise InvalidJsonError(
                f"Missing required fields in extracted item: {', '.join(missing)}"
            )

    def _normalize_item(
        self,
        item: dict[str, Any],
        *,
        patient_source_key: str = "",
    ) -> dict[str, Any]:
        """Map a single path2 JSON item to canonical ingestion format.

        Field mapping:
            createdAt   -> happened_at
            signedAt    -> signed_at (None if empty)
            content     -> content_text
            createdBy   -> author_name
            type        -> profession_type (via _TYPE_MAP)
            signatureLine -> signature_line
            admissionKey -> admission_key
            chunkStart  -> chunk_start
            chunkEnd    -> chunk_end
            (param)     -> patient_source_key
            (raw item)  -> raw_payload
            (constant)  -> source_system = "tasy"

        Raises:
            InvalidJsonError: If required fields are missing.
        """
        self._validate_item(item)

        raw_type = item.get("type", "other")
        profession_type = _TYPE_MAP.get(raw_type, "other")

        signed_at = item.get("signedAt")
        if signed_at == "":
            signed_at = None

        return {
            "happened_at": item["createdAt"],
            "signed_at": signed_at,
            "content_text": item["content"],
            "author_name": item.get("createdBy", ""),
            "profession_type": profession_type,
            "signature_line": item.get("signatureLine", ""),
            "admission_key": item["admissionKey"],
            "chunk_start": item.get("chunkStart", ""),
            "chunk_end": item.get("chunkEnd", ""),
            "patient_source_key": patient_source_key,
            "source_system": "tasy",
            "raw_payload": item,
        }
