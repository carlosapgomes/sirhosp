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

import json
import logging
import re
from typing import Any
from urllib.parse import quote

from apps.ingestion.extractors.admission_snapshot_parser import (
    AdmissionSnapshotParser,
)
from apps.ingestion.extractors.errors import (
    ExtractionError,
    ExtractionTimeoutError,
    InvalidJsonError,
    SnapshotContainerMissingError,
)
from apps.ingestion.extractors.legacy_navigation import (
    DEMOGRAPHICS_IDENTITY_MESSAGE,
    demographics_identity_matches,
)
from apps.ingestion.extractors.playwright_extractor import _TYPE_MAP
from apps.ingestion.extractors.session_controller import (
    PersistentSessionController,
    SessionControllerConfig,
    SessionHandle,
)

logger = logging.getLogger(__name__)

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

# ---------------------------------------------------------------------------
# Evolution data extraction constants and patterns (PSW-S5)
# ---------------------------------------------------------------------------

_DEFAULT_EVOLUTIONS_URL_TEMPLATE = (
    "/evolutions/{patient_record}?start={start_date}&end={end_date}"
)
"""Default URL template for evolution page navigation.

Supports ``{patient_record}``, ``{start_date}``, ``{end_date}`` placeholders.
"""

_EVOLUTION_DATA_DIV_ID = "evolution-data"
"""HTML id of the evolution data container div."""

_EVOLUTION_DATA_CONTAINER_RE = re.compile(
    r'<div[^>]*\bid\s*=\s*["\']'
    + re.escape(_EVOLUTION_DATA_DIV_ID)
    + r'["\'][^>]*>\s*(.*?)\s*</div>',
    re.DOTALL | re.IGNORECASE,
)
"""Regex to extract JSON array from a ``<div id="evolution-data">`` container."""

# ---------------------------------------------------------------------------
# Demographics data extraction constants (PSW-S16)
# ---------------------------------------------------------------------------

_DEFAULT_DEMOGRAPHICS_URL_TEMPLATE = "/demographics/{patient_record}"
"""Default URL template for the demographics page (stub/test compatibility).

The real legacy path uses action navigation
(``extract_demographics_via_legacy_actions``); this template only exists so
the stub path and unit tests can inject a synthetic ``demographics-data``
container.
"""

_DEMOGRAPHICS_DATA_DIV_ID = "demographics-data"
"""HTML id of the synthetic demographics data container div."""

_DEMOGRAPHICS_DATA_CONTAINER_RE = re.compile(
    r'<div[^>]*\bid\s*=\s*["\']'
    + re.escape(_DEMOGRAPHICS_DATA_DIV_ID)
    + r'["\'][^>]*>\s*(.*?)\s*</div>',
    re.DOTALL | re.IGNORECASE,
)
"""Regex to extract a JSON object from ``<div id="demographics-data">``."""


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
        Resolved URL string with all path parameters URL-encoded.
    """
    return template.format(
        patient_record=quote(patient_record, safe=""),
        start_date=quote(start_date, safe=""),
        end_date=quote(end_date, safe=""),
    )


# ---------------------------------------------------------------------------
# Generic container extraction
# ---------------------------------------------------------------------------


def _extract_json_from_container(
    html: str,
    div_id: str,
    pattern: re.Pattern,
) -> str:
    """Extract the JSON string from a named ``<div>`` container.

    Args:
        html: Full page HTML potentially containing the container.
        div_id: The ``id`` attribute value of the target div.
        pattern: Compiled regex to match the div and extract content.

    Returns:
        Raw JSON string extracted from the container.

    Raises:
        SnapshotContainerMissingError: If the container is not found.
    """
    match = pattern.search(html)
    if not match:
        raise SnapshotContainerMissingError(
            f"Page HTML contains no data container "
            f"(<div id=\"{div_id}\">). "
            "Cannot extract data."
        )
    return match.group(1)


def _extract_json_from_snapshot_container(html: str) -> str:
    """Extract the JSON string from the ``admission-snapshot-data`` div.

    Args:
        html: Full page HTML potentially containing the snapshot container.

    Returns:
        Raw JSON string extracted from the container.

    Raises:
        SnapshotContainerMissingError: If the snapshot data container is not
            found in the page HTML.
    """
    return _extract_json_from_container(
        html, _ADMISSION_DATA_DIV_ID, _DATA_CONTAINER_RE
    )


# ---------------------------------------------------------------------------
# Evolution JSON parsing (PSW-S5)
# ---------------------------------------------------------------------------


def _parse_evolutions_json(json_text: str) -> list[dict[str, Any]]:
    """Parse and normalise a JSON evolution data string.

    Args:
        json_text: Raw JSON string with evolution data.

    Returns:
        List of normalised evolution dicts with canonical field names.

    Raises:
        InvalidJsonError: If JSON is invalid or not a list.
    """
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise InvalidJsonError(
            f"Invalid JSON in evolution data: {exc}"
        ) from exc

    if not isinstance(data, list):
        raise InvalidJsonError(
            f"Evolution data JSON root must be a list, "
            f"got {type(data).__name__}"
        )

    result: list[dict[str, Any]] = []
    for item in data:
        normalised = _normalise_evolution_item(item)
        result.append(normalised)

    return result


def _normalise_evolution_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalise a single evolution item to canonical field names.

    Maps raw field names (e.g. ``admissionKey``) to canonical names
    (e.g. ``admission_key``). Accepts both snake_case and camelCase
    input field names for flexibility.

    Args:
        item: Raw evolution dict.

    Returns:
        Normalised dict with canonical field names.
    """
    return {
        "admission_key": (
            item.get("admission_key")
            or item.get("admissionKey")
            or ""
        ),
        "happened_at": (
            item.get("happened_at")
            or item.get("createdAt")
            or ""
        ),
        "event_type": (
            item.get("event_type")
            or item.get("type")
            or ""
        ),
        "content": (
            item.get("content")
            or item.get("content_text")
            or ""
        ),
        "profession": (
            item.get("profession")
            or item.get("profession_type")
            or ""
        ),
    }


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
# Evolution -> persistence schema enrichment (PSW-S11 fix)
# ---------------------------------------------------------------------------


def _enrich_evolutions_for_persistence(
    events: list[dict[str, Any]],
    *,
    patient_record: str,
    source_system: str = "tasy",
) -> list[dict[str, Any]]:
    """Add the persistible schema fields the shared ingestion service reads.

    Both the lightweight fast paths and the PDF fallback produce the adapter's
    5-key evolution contract (``admission_key``, ``happened_at``,
    ``event_type``, ``content``, ``profession``). The shared
    :func:`~apps.ingestion.evolution_ingestion.ingest_evolutions` service and
    :func:`~apps.ingestion.services._persist_event` instead read
    ``content_text``, ``profession_type``, ``author_name``, ``signature_line``,
    ``patient_source_key``, and ``source_system``.

    This enriches each event in place with those fields (derived from the
    5-key contract) while keeping the original keys for compatibility.
    ``patient_source_key`` comes from the run's ``patient_record`` so the
    correct patient is associated.

    Args:
        events: Evolution dicts in the 5-key contract (possibly enriched).
        patient_record: Patient record (prontuário) of the current run.
        source_system: Canonical source system (default ``"tasy"``).

    Returns:
        The same list, enriched in place with persistible fields.
    """
    for event in events:
        content = event.get("content", "")
        event_type = event.get("event_type", "")
        profession = event.get("profession", "")
        event.setdefault("patient_source_key", patient_record)
        event.setdefault("source_system", source_system)
        event.setdefault("content_text", content)
        # Map the PDF classifier token to the same canonical profession_type
        # the subprocess extractor stores for an identical evolution (reuses
        # ``_TYPE_MAP`` from ``playwright_extractor`` to avoid divergence).
        event.setdefault(
            "profession_type", _TYPE_MAP.get(event_type, event_type)
        )
        event.setdefault("author_name", profession)
        event.setdefault("signature_line", event.get("signature_line", ""))
    return events


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
        self._evolutions_url_template: str = (
            getattr(config, "base_evolutions_url", "")
            or _DEFAULT_EVOLUTIONS_URL_TEMPLATE
        )
        self._demographics_url_template: str = (
            getattr(config, "base_demographics_url", "")
            or _DEFAULT_DEMOGRAPHICS_URL_TEMPLATE
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
            timeout: Maximum execution time in seconds, propagated to the
                session handle's navigation/wait path.

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

        # Step 3: Navigate to admissions page.
        # Priority: UI action navigation (``navigate_to_admissions``) when
        # the session supports it — this is the path for real legacy
        # Java/JSP/PrimeFaces systems that don't expose reloadable deep
        # links. Fallback: URL template (``open_tab``) for stub/test compat.
        # PSW-S17 R2/R3: typed timeouts (NavigationTimeoutError from the
        # action path, ExtractionTimeoutError from open_tab) propagate as
        # typed ExtractionTimeoutError subclasses. Non-timeout failures use
        # a constant sanitized message (no URL, patient record, or token).
        _navigate_to_admissions = getattr(
            self._session, "navigate_to_admissions", None
        )
        if callable(_navigate_to_admissions):
            # Action-based UI navigation (PSW-S12).
            if not _navigate_to_admissions(patient_record=patient_record):
                raise ExtractionError(
                    "Failed to navigate to the admissions page "
                    "via legacy UI actions."
                )
        else:
            # URL template fallback (legacy/test path).
            url = _build_admissions_url(
                self._admissions_url_template,
                patient_record=patient_record,
                start_date=start_date,
                end_date=end_date,
            )
            if not self._session.open_tab(url, timeout=timeout):
                raise ExtractionError(
                    "Failed to navigate to the admissions page."
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

    # ------------------------------------------------------------------
    # Evolution extraction (PSW-S5)
    # ------------------------------------------------------------------

    def extract_evolutions(
        self,
        *,
        patient_record: str,
        start_date: str,
        end_date: str,
        timeout: int = 120,
    ) -> list[dict[str, Any]]:
        """Extract clinical evolutions through the persistent session.

        Lifecycle:
        1. Check session readiness (``ensure_ready``).
        2. Renew session if needed (``renew_if_needed``).
        3. Navigate to evolution page (open tab with timeout).
        4. Extract JSON data from evolution container in page HTML.
        5. Parse and normalise evolution data.
        6. Cleanup job tab (``close_job_tab_if_present``).
        7. Mark job as processed (``mark_job_processed``).

        Args:
            patient_record: Patient record identifier (prontuário).
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
            timeout: Maximum execution time in seconds, propagated to the
                session handle's navigation/wait path.

        Returns:
            List of normalised evolution dicts with canonical field names.

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

        # Step 3: Navigate to evolution page.
        # First priority: URL template (``open_tab``) + container parsing
        # for stub/test compatibility and JSON/pre fast paths. The bridge
        # returns evolution data from lightweight fast paths
        # (``evolution-data-json`` script, ``pre.report-text``) when
        # available.
        url = _build_admissions_url(
            self._evolutions_url_template,
            patient_record=patient_record,
            start_date=start_date,
            end_date=end_date,
        )
        # PSW-S17 R2/R3: a Playwright navigation timeout surfaces as a
        # typed ExtractionTimeoutError from ``open_tab`` and propagates.
        # Non-timeout failures produce a constant sanitized message (no URL).
        if not self._session.open_tab(url, timeout=timeout):
            raise ExtractionError(
                "Failed to navigate to the evolution page."
            )

        # Step 4: Extract JSON data from evolution container
        html = self._session.get_page_html()
        json_text = _extract_json_from_container(
            html, _EVOLUTION_DATA_DIV_ID, _EVOLUTION_DATA_CONTAINER_RE
        )

        # Step 5: Parse and normalise evolution data
        result = _parse_evolutions_json(json_text)

        # Step 5b (PSW-S11): PDF report fallback. The lightweight fast paths
        # (``evolution-data-json`` script, ``pre.report-text``) are tried first
        # by the bridge. When they yield no events, delegate to the real
        # legacy PDF flow on sessions that expose it (``RealHandleBridge``),
        # reusing the already-open persistent page/context — never a new
        # browser or subprocess. A genuine empty window stays an empty list.
        if not result and hasattr(self._session, "extract_evolutions_pdf"):
            result = self._session.extract_evolutions_pdf(
                start_date=start_date,
                end_date=end_date,
                timeout=timeout,
            )

        # Step 5c (PSW-S13): Real legacy action navigation fallback.
        # When fast paths (JSON script + pre.report-text + PDF fallback)
        # yield no events AND the session exposes the legacy action flow,
        # navigate the real JSP/PrimeFaces UI to extract evolutions.
        # The action method handles admissions selection, detail
        # navigation, date filling, report generation, PDF download,
        # text extraction, and normalisation internally, returning the
        # 5-key evolution contract. A genuine empty window stays [].
        if not result and hasattr(
            self._session, "extract_evolutions_via_legacy_actions"
        ):
            result = self._session.extract_evolutions_via_legacy_actions(
                patient_record=patient_record,
                start_date=start_date,
                end_date=end_date,
                timeout=timeout,
            )

        # Step 6 (PSW-S11 fix): map the adapter's 5-key evolution contract
        # (admission_key/happened_at/event_type/content/profession) onto the
        # schema the shared ingestion service persists
        # (content_text/profession_type/author_name/signature_line/
        # patient_source_key/source_system). The adapter knows the
        # patient_record, so it is the single place to enrich both the
        # fast-path and the PDF-fallback events for persistence.
        result = _enrich_evolutions_for_persistence(
            result, patient_record=patient_record
        )

        # Step 7: Cleanup job tab
        self._controller.close_job_tab_if_present()

        # Step 8: Mark job as processed
        self._controller.mark_job_processed()

        return result

    # ------------------------------------------------------------------
    # Demographics extraction (PSW-S16)
    # ------------------------------------------------------------------

    def get_demographics(
        self,
        *,
        patient_record: str,
        timeout: int = 120,
    ) -> dict[str, str]:
        """Extract patient demographics through the persistent session.

        Lifecycle:
        1. Check session readiness (``ensure_ready``).
        2. Renew session if needed (``renew_if_needed``).
        3. Navigate + extract demographics:
           - Real handle: delegate to
             ``extract_demographics_via_legacy_actions`` (action navigation
             reusing the already-open page/context).
           - Stub/test fallback: URL template (``open_tab``) + parse the
             synthetic ``<div id="demographics-data">`` JSON container.
        4. Cleanup job tab (``close_job_tab_if_present``).
        5. Mark job as processed (``mark_job_processed``).

        The returned dict uses the external keys
        :func:`~apps.ingestion.services.upsert_patient_demographics` reads.
        Dates stay in source ``DD/MM/YYYY`` format; the persistence service
        parses them.

        Args:
            patient_record: Patient record identifier (prontuário).
            timeout: Maximum execution time in seconds, propagated to the
                session handle's navigation path.

        Returns:
            Normalized in-memory demographics dict.

        Raises:
            ExtractionError: If session is not ready, renewal fails, or the
                real-handle action navigation fails.
            InvalidJsonError: If the stub-path synthetic container holds
                invalid JSON or a non-object payload.
            SnapshotContainerMissingError: If the stub-path page renders but
                the synthetic demographics container is absent.
        """
        # Step 1: Check session readiness
        if not self._controller.ensure_ready():
            raise ExtractionError("Session not ready for extraction")

        # Step 2: Renew session if needed
        if not self._controller.renew_if_needed():
            raise ExtractionError("Session renewal failed before extraction")

        # Step 3: Navigate + extract demographics.
        _extract_via_actions = getattr(
            self._session, "extract_demographics_via_legacy_actions", None
        )
        if callable(_extract_via_actions):
            # Real legacy action navigation (PSW-S16). Reuses the
            # already-open persistent page/context.
            # PSW-S17 R2/R3: a typed NavigationTimeoutError MUST propagate
            # unchanged; only non-timeout failures are wrapped.
            try:
                demographics = _extract_via_actions(
                    patient_record=patient_record, timeout=timeout
                )
            except ExtractionTimeoutError:
                raise
            except Exception as exc:  # noqa: BLE001 - sanitized taxonomy
                raise ExtractionError(
                    "Failed to extract demographics via legacy UI actions"
                ) from exc
            if not isinstance(demographics, dict):
                raise ExtractionError(
                    "Demographics extraction returned a non-object payload"
                )
        else:
            # URL template fallback (stub/test compatibility).
            url = _build_admissions_url(
                self._demographics_url_template,
                patient_record=patient_record,
            )
            if not self._session.open_tab(url, timeout=timeout):
                raise ExtractionError(
                    "Failed to navigate to the demographics page."
                )
            html = self._session.get_page_html()
            json_text = _extract_json_from_container(
                html,
                _DEMOGRAPHICS_DATA_DIV_ID,
                _DEMOGRAPHICS_DATA_CONTAINER_RE,
            )
            try:
                demographics = json.loads(json_text)
            except json.JSONDecodeError as exc:
                raise InvalidJsonError(
                    f"Invalid JSON in demographics data: {exc}"
                ) from exc
            if not isinstance(demographics, dict):
                raise InvalidJsonError(
                    "Demographics data JSON root must be an object"
                )

        # Identity invariant (PSW-S16 R3): a persistent demographics run can
        # reach persistence only after the requested patient was positively
        # identified in the extracted payload. This boundary is crossed by
        # every real/stub extraction path. Fail-closed BEFORE cleanup so a
        # mismatched/empty identity never counts the job as processed.
        if not demographics_identity_matches(
            requested_patient_record=patient_record,
            demographics=demographics,
        ):
            raise ExtractionError(DEMOGRAPHICS_IDENTITY_MESSAGE)

        # Step 4: Cleanup job tab (safe no-op when only root tab remains).
        self._controller.close_job_tab_if_present()

        # Step 5: Mark job as processed.
        self._controller.mark_job_processed()

        return demographics

    def cleanup_after_failure(self) -> None:
        """Clean up the job tab and mark the job as processed after a recoverable failure.

        Data-level failures (missing snapshot container, invalid JSON) occur after
        the job tab was successfully opened. The command loop must call this method
        before claiming another run, ensuring:
        1. The non-root job tab is closed (safe no-op if only root tab remains).
        2. The job is counted as processed (resets consecutive_failure counter).

        Session-level failures (not ready, renewal failure, tab open failure)
        happen before a job tab is opened. This method is safe to call in those
        cases too -- tab cleanup will be a no-op when only the root tab exists.
        """
        self._controller.close_job_tab_if_present()
        self._controller.mark_job_processed()

    def ensure_session_ready(self) -> bool:
        """Ensure the underlying persistent session is ready for work.

        PSW-S19-C1: a pending restart is authoritative even when the old page
        still looks ready, so ``restart_required()`` is resolved BEFORE
        ordinary readiness may be accepted. When a restart is required, the
        closed restart/rebootstrap boundary runs; it returns ``True`` only
        after the authenticated ``#tempoSessao`` marker is observed. There is
        no background login thread.

        Returns:
            True if the session is ready, False if recovery failed or
            rebootstrap is incomplete.
        """
        if self._controller.restart_required():
            return self._restart_and_rebootstrap()
        return self._controller.ensure_ready()

    def restart_and_rebootstrap(self) -> bool:
        """Restart the browser and re-bootstrap auth at a safe point between jobs.

        PSW-S19 R2/R3: the single lifecycle boundary for a controlled restart.
        Called by the worker between jobs (a safe point) once the controller
        reports ``restart_required()``. Returns True only when the browser was
        restarted, the authenticated session re-bootstrapped through the
        handle/bridge ``bootstrap()`` boundary, the ``#tempoSessao`` marker was
        observed, and the controller counters reset. On any failure (R5)
        recovery state is retained and no reset occurs.
        """
        return self._restart_and_rebootstrap()

    def _restart_and_rebootstrap(self) -> bool:
        """Run the closed restart/rebootstrap boundary.

        Success order (PSW-S19-C1 closed matrix):

            bootstrap capability is callable
            -> restart browser/context
            -> run bootstrap/login
            -> controller ensure_ready observes valid #tempoSessao
            -> reset_after_restart exactly once
            -> return True

        Every other condition returns ``False`` without resetting recovery:
        bootstrap absent/non-callable (no restart), ``restart_browser()``
        raising, ``bootstrap()`` raising, or the readiness marker being
        invalid after bootstrap. Failures emit at most a constant sanitized
        warning; no exception text, URL, profile path, credential, cookie,
        selector, or raw HTML is observable, and no queued run is mutated.
        """
        bootstrap = getattr(self._session, "bootstrap", None)
        if not callable(bootstrap):
            # bootstrap capability absent: no restart, no reset, recovery pending.
            return False
        try:
            self._session.restart_browser()
        except Exception:  # noqa: BLE001 - sanitized lifecycle boundary
            logger.warning("Persistent session restart failed (sanitized)")
            return False
        try:
            bootstrap()
        except Exception:  # noqa: BLE001 - sanitized lifecycle boundary
            logger.warning("Persistent session rebootstrap failed (sanitized)")
            return False
        if not self._controller.ensure_ready():
            logger.warning(
                "Persistent session readiness marker missing after "
                "rebootstrap (sanitized)"
            )
            return False
        self._controller.reset_after_restart()
        return True

    @property
    def controller(self):
        """Return the underlying session controller (for tests and command orchestration)."""
        return self._controller

    @property
    def session(self):
        """Return the underlying SessionHandle (for command-level lifecycle control).

        Used by the worker command to restart the browser between jobs or on
        teardown. Returns the same object passed at construction.
        """
        return self._session
