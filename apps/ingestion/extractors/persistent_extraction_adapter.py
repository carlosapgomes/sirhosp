"""Persistent session-based extraction adapter for admissions (PSW-S3).

Provides a :class:`PersistentExtractionAdapter` that exposes
``get_admission_snapshot(...)`` through a persistent browser session
abstraction. The adapter calls session readiness/renewal checkpoints
from :class:`~session_controller.PersistentSessionController` before
source-system actions, parses admission snapshot data from the page
HTML, and normalises it consistently with the existing
:class:`~admission_snapshot_parser.AdmissionSnapshotParser`.

No real Playwright calls exist in this module — all browser interaction
is delegated to a ``SessionHandle`` protocol implementation.
"""

from __future__ import annotations

import re
from typing import Any

from apps.ingestion.extractors.admission_snapshot_parser import (
    AdmissionSnapshotParser,
)
from apps.ingestion.extractors.errors import ExtractionError
from apps.ingestion.extractors.session_controller import (
    PersistentSessionController,
    SessionControllerConfig,
    SessionHandle,
)

# ---------------------------------------------------------------------------
# Default URL template for admissions page navigation
# ---------------------------------------------------------------------------

_DEFAULT_ADMISSIONS_URL_TEMPLATE = "/admissions/{patient_record}"

_ADMISSION_DATA_DIV_ID = "admission-snapshot-data"

# Regex to extract JSON array from a <div id="admission-snapshot-data"> container.
# Looks for an opening bracket [ ... ] inside the div.
_DATA_CONTAINER_RE = re.compile(
    r'<div[^>]*\bid\s*=\s*["\']'
    + re.escape(_ADMISSION_DATA_DIV_ID)
    + r'["\'][^>]*>\s*(.*?)\s*</div>',
    re.DOTALL | re.IGNORECASE,
)


def _build_admissions_url(
    template: str,
    *,
    patient_record: str,
    start_date: str = "",
    end_date: str = "",
) -> str:
    """Build the admissions page URL from the template and parameters.

    The template supports ``{patient_record}``, ``{start_date}``, and
    ``{end_date}`` placeholders.

    Args:
        template: URL template string.
        patient_record: Patient record identifier (prontuário).
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.

    Returns:
        Resolved URL string.
    """
    return template.format(
        patient_record=patient_record,
        start_date=start_date,
        end_date=end_date,
    )


def _extract_json_from_snapshot_container(html: str) -> str:
    """Extract the JSON string from the ``admission-snapshot-data`` div.

    Args:
        html: Full page HTML potentially containing the snapshot container.

    Returns:
        Raw JSON string extracted from the container.

    Raises:
        ExtractionError: If the snapshot data container is not found.
    """
    match = _DATA_CONTAINER_RE.search(html)
    if not match:
        raise ExtractionError(
            f"Page HTML contains no snapshot data container "
            f"(<div id=\"{_ADMISSION_DATA_DIV_ID}\">). "
            "Cannot extract admissions."
        )
    return match.group(1)


def _parse_admissions_json(json_text: str) -> list[dict[str, Any]]:
    """Parse and normalise a JSON admission snapshot string.

    Reuses the existing :class:`AdmissionSnapshotParser` for consistent
    field mapping and validation.

    Args:
        json_text: Raw JSON string with admission snapshot data.

    Returns:
        List of normalised admission dicts with canonical field names.

    Raises:
        InvalidJsonError: If JSON is invalid or not a list.
        ExtractionError: If required fields are missing.
    """
    parser = AdmissionSnapshotParser()
    return parser.parse_json_string(json_text)


# ---------------------------------------------------------------------------
# Persistent Extraction Adapter
# ---------------------------------------------------------------------------


class PersistentExtractionAdapter:
    """Persistent session-based extraction adapter for admissions.

    Wraps a ``PersistentSessionController`` and ``SessionHandle`` to
    provide the ``get_admission_snapshot()`` method for the ingestion
    lifecycle. Session checkpoints (ensure_ready, renew_if_needed) are
    called before source-system actions.

    Args:
        session: A ``SessionHandle`` implementation for browser interaction.
        config: Optional ``SessionControllerConfig`` with lifecycle thresholds.
    """

    def __init__(
        self,
        session: SessionHandle,
        config: SessionControllerConfig | None = None,
    ) -> None:
        self._session = session
        self._controller = PersistentSessionController(session, config)
        self._admissions_url_template: str = (
            config.base_admissions_url
            if config and config.base_admissions_url
            else _DEFAULT_ADMISSIONS_URL_TEMPLATE
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_admission_snapshot(
        self,
        *,
        patient_record: str,
        start_date: str,
        end_date: str,
        timeout: int = 120,
    ) -> list[dict[str, Any]]:
        """Extract admission snapshot through the persistent session.

        Lifecycle:
        1. Check session readiness (``ensure_ready``).
        2. Renew session if needed (``renew_if_needed``).
        3. Navigate to admissions page (open tab).
        4. Extract JSON data from page HTML.
        5. Parse and normalise via ``AdmissionSnapshotParser``.
        6. Cleanup job tab (``close_job_tab_if_present``).
        7. Mark job as processed (``mark_job_processed``).

        Args:
            patient_record: Patient record identifier (prontuário).
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
            timeout: Maximum execution time in seconds (reserved for
                future use with real Playwright handles).

        Returns:
            List of normalised admission dicts with canonical field names.

        Raises:
            ExtractionError: If session is not ready, renewal fails, or
                page navigation fails.
            InvalidJsonError: If the extracted data is invalid JSON or
                not a list.
        """
        # Step 1: Check session readiness
        if not self._controller.ensure_ready():
            raise ExtractionError("Session not ready for extraction")

        # Step 2: Renew session if needed
        if not self._controller.renew_if_needed():
            raise ExtractionError("Session renewal failed before extraction")

        # Step 3: Navigate to admissions page
        url = _build_admissions_url(
            self._admissions_url_template,
            patient_record=patient_record,
            start_date=start_date,
            end_date=end_date,
        )
        if not self._session.open_tab(url):
            raise ExtractionError(
                f"Failed to navigate to admissions page: {url}"
            )

        # Step 4: Extract JSON data from page HTML
        html = self._session.get_page_html()
        json_text = _extract_json_from_snapshot_container(html)

        # Step 5: Parse and normalise. AdmissionSnapshotParser maps invalid
        # JSON to InvalidJsonError and missing required fields to
        # ExtractionError, preserving the existing typed-exception taxonomy.
        result = _parse_admissions_json(json_text)

        # Step 6: Cleanup job tab
        self._controller.close_job_tab_if_present()

        # Step 7: Mark job as processed
        self._controller.mark_job_processed()

        return result
