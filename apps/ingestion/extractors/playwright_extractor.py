"""Playwright evolution extractor adapter.

Encapsulates subprocess execution of the integrated legacy ``path2.py``
connector and maps its JSON output to the canonical ingestion format.
"""

from __future__ import annotations

import json
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
from apps.ingestion.extractors.subprocess_utils import (
    SubprocessTimeoutError,
    run_subprocess,
)

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

DEFAULT_EVOLUTION_TIMEOUT_SECONDS = 900
DEFAULT_ADMISSION_TIMEOUT_SECONDS = 120
_TIMEOUT_PREVIEW_MAX_CHARS = 1200


def _format_timeout_stream(value: str | bytes | None) -> str:
    """Normalize and truncate subprocess stream output for error messages."""
    if value is None:
        return ""

    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value

    text = text.strip()
    if not text:
        return ""

    if len(text) <= _TIMEOUT_PREVIEW_MAX_CHARS:
        return text

    remaining = len(text) - _TIMEOUT_PREVIEW_MAX_CHARS
    return f"{text[:_TIMEOUT_PREVIEW_MAX_CHARS]}... [truncated {remaining} chars]"


def _build_process_output_context(
    stdout_value: str | bytes | None,
    stderr_value: str | bytes | None,
) -> str:
    """Build diagnostic context from subprocess stdout/stderr."""
    stdout_preview = _format_timeout_stream(stdout_value)
    stderr_preview = _format_timeout_stream(stderr_value)

    parts: list[str] = []
    if stdout_preview:
        parts.append(f"stdout preview: {stdout_preview}")
    if stderr_preview:
        parts.append(f"stderr preview: {stderr_preview}")

    return " | ".join(parts)


def _build_timeout_context(exc: SubprocessTimeoutError) -> str:
    """Build diagnostic context from SubprocessTimeoutError output/stderr."""
    stdout_value = exc.output
    return _build_process_output_context(stdout_value, exc.stderr)


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
        timeout: int = DEFAULT_EVOLUTION_TIMEOUT_SECONDS,
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
                result = run_subprocess(
                    cmd,
                    timeout=timeout,
                )
            except SubprocessTimeoutError as exc:
                timeout_context = _build_timeout_context(exc)
                message = (
                    f"Extraction timed out after {exc.timeout}s "
                    f"for patient_record={patient_record}"
                )
                if timeout_context:
                    message = f"{message}. {timeout_context}"
                raise ExtractionTimeoutError(message) from exc
            except Exception as exc:
                raise ExtractionError(
                    f"Failed to execute extractor: {exc}"
                ) from exc

            if result.returncode != 0:
                output_context = _build_process_output_context(
                    getattr(result, "stdout", None),
                    getattr(result, "stderr", None),
                )
                message = f"Extractor exited with code {result.returncode}"
                if output_context:
                    message = f"{message}. {output_context}"
                raise ExtractionError(message)

            raw_items = self._parse_json_output(json_output_path)
            return self._normalize_collection(raw_items, patient_source_key=patient_record)

    def get_admission_snapshot(
        self,
        *,
        patient_record: str,
        start_date: str,
        end_date: str,
        timeout: int = DEFAULT_ADMISSION_TIMEOUT_SECONDS,
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
                result = run_subprocess(
                    cmd,
                    timeout=timeout,
                )
            except SubprocessTimeoutError as exc:
                timeout_context = _build_timeout_context(exc)
                message = (
                    f"Admission snapshot extraction timed out after {exc.timeout}s "
                    f"for patient_record={patient_record}"
                )
                if timeout_context:
                    message = f"{message}. {timeout_context}"
                raise ExtractionTimeoutError(message) from exc
            except Exception as exc:
                raise ExtractionError(
                    f"Failed to execute extractor for admission snapshot: {exc}"
                ) from exc

            if result.returncode != 0:
                output_context = _build_process_output_context(
                    getattr(result, "stdout", None),
                    getattr(result, "stderr", None),
                )
                message = (
                    "Extractor exited with code "
                    f"{result.returncode} during admission snapshot extraction"
                )
                if output_context:
                    message = f"{message}. {output_context}"
                raise ExtractionError(message)

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
