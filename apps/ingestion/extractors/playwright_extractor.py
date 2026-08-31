"""Playwright evolution extractor adapter.

Encapsulates subprocess execution of the integrated legacy ``path2.py``
connector and maps its JSON output to the canonical ingestion format.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
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
from apps.ingestion.extractors.patient_flow_snapshot import PatientFlowSnapshot
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

FLOW_SNAPSHOT_DEFAULT_START_DATE = "2000-01-01"
"""Wide default window start for self-contained flow snapshot captures
(PFIF-S2) — mirrors the classic worker's admissions-only default range."""


# PSW-S17 R5 (second corrective closure): the previous
# ``_build_timeout_context`` / ``_build_process_output_context`` helpers
# inlined subprocess stdout/stderr previews into persisted lifecycle error
# messages. They are removed because those previews can carry arbitrary
# source/system text. Operators needing subprocess diagnostics must use a
# separate explicitly redacted channel (out of scope for this slice).


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
        # PFIF-S2: job-scoped cache of the admissions subprocess artifacts
        # (admissions list + encounter dates) so the enriched flow snapshot
        # reuses the SAME subprocess — never a second browser/login/subprocess.
        self._flow_capture_cache: tuple[list[dict[str, Any]], list[date]] | None = (
            None
        )

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
                # PSW-S17 R5 (second corrective closure): constant sanitized
                # timeout message; no patient_record, no subprocess
                # stdout/stderr preview, raw chain suppressed.
                raise ExtractionTimeoutError(
                    f"Extraction timed out after {exc.timeout}s."
                ) from None
            except Exception:
                raise ExtractionError(
                    "Failed to execute the evolution extractor."
                ) from None

            if result.returncode != 0:
                # Best-effort: check if JSON output was produced despite
                # non-zero exit (e.g. path2.py exits 1 on empty results).
                # If valid JSON exists, use it instead of failing.
                rescued = self._try_rescue_json_output(json_output_path)
                if rescued is not None:
                    return self._normalize_collection(
                        rescued, patient_source_key=patient_record
                    )

                # PSW-S17 R5: keep only the non-sensitive return code; drop
                # subprocess stdout/stderr previews from persisted messages.
                raise ExtractionError(
                    f"Extractor exited with code {result.returncode}."
                )

            raw_items = self._parse_json_output(json_output_path)
            return self._normalize_collection(raw_items, patient_source_key=patient_record)

    def get_admission_snapshot(
        self,
        *,
        patient_record: str,
        start_date: str,
        end_date: str,
        timeout: int = DEFAULT_ADMISSION_TIMEOUT_SECONDS,
        include_encounter_sidecar: bool = False,
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
            include_encounter_sidecar: PFIF-S2 — also request the optional
                encounter-dates sidecar so a subsequent
                :meth:`get_patient_flow_snapshot` on this instance reuses the
                SAME subprocess artifacts (no second browser/login/subprocess).

        Returns:
            List of normalised admission dicts with canonical field names.

        Raises:
            ExtractionTimeoutError: When extraction exceeds timeout.
            ExtractionError: On any other extraction failure (incl. missing snapshot).
            InvalidJsonError: If JSON is invalid or not a list.
        """
        br_start = _convert_to_br_date(start_date)
        br_end = _convert_to_br_date(end_date)

        admissions, _encounter_dates = self._capture_admissions_artifacts(
            patient_record=patient_record,
            br_start=br_start,
            br_end=br_end,
            include_encounter_sidecar=include_encounter_sidecar,
            timeout=timeout,
        )
        return admissions

    def get_patient_flow_snapshot(
        self,
        *,
        patient_record: str,
        today: date,
        timeout: int = DEFAULT_ADMISSION_TIMEOUT_SECONDS,
    ) -> PatientFlowSnapshot:
        """Return the shared ``PatientFlowSnapshot`` contract (PFIF-S2 R2).

        Reuses the artifacts of the job's single admissions subprocess when
        available (cache filled by :meth:`get_admission_snapshot` with
        ``include_encounter_sidecar=True``); otherwise runs ONE self-contained
        subprocess. The encounter evidence was already collected by path2.py
        inside that same subprocess (only for empty admissions-only captures),
        so this method never opens a second browser/login/subprocess for the
        same job.

        Args:
            patient_record: Patient record identifier (prontuário).
            today: Local calendar date (``America/Bahia`` in production) used
                by the shared S1 recency classifier.
            timeout: Maximum subprocess execution time in seconds.

        Returns:
            The immutable shared snapshot with admissions, the latest valid
            encounter date and its closed recency bucket.

        Raises:
            ExtractionTimeoutError / ExtractionError: same sanitized taxonomy
                as :meth:`get_admission_snapshot` (incl. missing/malformed
                sidecar when the admissions capture was empty).
        """
        if self._flow_capture_cache is None:
            self._flow_capture_cache = self._capture_admissions_artifacts(
                patient_record=patient_record,
                br_start=_convert_to_br_date(FLOW_SNAPSHOT_DEFAULT_START_DATE),
                br_end=_convert_to_br_date(today.isoformat()),
                include_encounter_sidecar=True,
                timeout=timeout,
            )
        admissions, encounter_dates = self._flow_capture_cache
        return PatientFlowSnapshot.build(
            admissions=admissions,
            encounter_dates=encounter_dates,
            today=today,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _capture_admissions_artifacts(
        self,
        *,
        patient_record: str,
        br_start: str,
        br_end: str,
        include_encounter_sidecar: bool,
        timeout: int,
    ) -> tuple[list[dict[str, Any]], list[date]]:
        """Run ONE admissions-only path2.py subprocess and read its artifacts.

        Returns ``(admissions, encounter_dates)``. ``encounter_dates`` is
        non-empty only when the sidecar was requested AND the admissions list
        was empty — the only condition under which path2.py consults the
        legacy Atendimentos table (PFIF-S2 R1).
        """
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
            ]
            encounters_output_path: Path | None = None
            if include_encounter_sidecar:
                encounters_output_path = tmpdir_path / "encounters.json"
                cmd += ["--encounters-output", str(encounters_output_path)]
            cmd += ["--admissions-only", "--headless"]

            try:
                result = run_subprocess(
                    cmd,
                    timeout=timeout,
                )
            except SubprocessTimeoutError as exc:
                # PSW-S17 R5: constant sanitized timeout message; raw chain
                # suppressed.
                raise ExtractionTimeoutError(
                    f"Admission snapshot extraction timed out "
                    f"after {exc.timeout}s."
                ) from None
            except Exception:
                raise ExtractionError(
                    "Failed to execute the admission snapshot extractor."
                ) from None

            if result.returncode != 0:
                # PSW-S17 R5: keep only the non-sensitive return code.
                raise ExtractionError(
                    "Admission snapshot extractor exited with code "
                    f"{result.returncode}."
                )

            parser = AdmissionSnapshotParser()
            admissions = parser.parse_file(admissions_output_path)
            if encounters_output_path is None or admissions:
                # Without the sidecar request, or with a non-empty capture,
                # path2.py never consulted Atendimentos (no sidecar exists).
                encounter_dates: list[date] = []
            else:
                encounter_dates = self._read_encounter_sidecar(
                    encounters_output_path
                )
            if include_encounter_sidecar:
                # PFIF-S2: job-scoped cache so a follow-up
                # get_patient_flow_snapshot() call reuses the SAME
                # subprocess artifacts — never a second subprocess.
                self._flow_capture_cache = (admissions, encounter_dates)
            return admissions, encounter_dates

    def _read_encounter_sidecar(self, sidecar_path: Path) -> list[date]:
        """Read the optional encounter-dates sidecar written by path2.py.

        When the admissions list is empty the sidecar is REQUIRED: a missing
        or malformed artifact is a sanitized failure — no raw content, path
        or record token enters the message (PFIF-S2 R2/R5).
        """
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ExtractionError(
                "Encounter sidecar artifact is missing for an empty "
                "admissions capture."
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise ExtractionError(
                "Encounter sidecar artifact is malformed for an empty "
                "admissions capture."
            ) from exc

        if not isinstance(data, dict) or set(data.keys()) != {
            "encounter_dates"
        }:
            raise ExtractionError(
                "Encounter sidecar artifact has an unexpected shape."
            )
        raw_dates = data["encounter_dates"]
        if not isinstance(raw_dates, list) or any(
            not isinstance(value, str) for value in raw_dates
        ):
            raise ExtractionError(
                "Encounter sidecar artifact has an unexpected shape."
            )

        parsed: list[date] = []
        for value in raw_dates:
            try:
                parsed.append(date.fromisoformat(value))
            except ValueError as exc:
                raise ExtractionError(
                    "Encounter sidecar artifact has an invalid date entry."
                ) from exc
        return parsed

    def _try_rescue_json_output(self, json_path: Path) -> list[dict[str, Any]] | None:
        """Attempt to read the JSON output file even after non-zero exit.

        path2.py may exit with code 1 when there are zero evolutions in the
        period (e.g. deceased patient with no clinical records). This method
        tries to salvage a valid JSON array from the output file rather than
        treating the run as a hard failure.

        Returns:
            Parsed list of items, or None if the file is missing/invalid.
        """
        try:
            return self._parse_json_output(json_path)
        except InvalidJsonError:
            return None

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
