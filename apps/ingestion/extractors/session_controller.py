"""Persistent Legacy Session Controller (PSW-S2).

Provides a controller that manages a persistent legacy browser session
across multiple ingestion jobs. Uses PSW-S1 policy primitives for DOM
parsing and decision-making, without direct Playwright dependency.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from apps.ingestion.extractors.session_policy import (
    SEL_RENEWAL_BUTTON,
    TabCleanupAction,
    TabCleanupOutcome,
    decide_tab_cleanup,
    is_renewal_popup_visible,
    parse_session_countdown,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class SessionControllerConfig:
    """Conservative configurable thresholds for session lifecycle.

    Attributes:
        max_jobs_per_session: Maximum jobs before triggering a browser restart.
        max_lifetime_seconds: Maximum browser lifetime in seconds before
            triggering a restart.
        max_consecutive_failures: Maximum consecutive renewal/login/tab-cleanup
            failures before triggering a restart.
        renewal_threshold_seconds: Renew proactively when remaining session
            time falls below this value.
        safe_renewal_tab_url: URL of a safe legacy tab to open for proactive
            session renewal.
        base_admissions_url: URL template for the admissions page.
            Supports ``{patient_record}``, ``{start_date}``, ``{end_date}``
            placeholders.
        base_evolutions_url: URL template for the evolutions page.
            Supports ``{patient_record}``, ``{start_date}``, ``{end_date}``
            placeholders. Defaults to
            ``/evolutions/{patient_record}?start={start_date}&end={end_date}``
            when empty.
    """

    max_jobs_per_session: int = 50
    max_lifetime_seconds: int = 3600
    max_consecutive_failures: int = 3
    renewal_threshold_seconds: int = 600
    safe_renewal_tab_url: str = ""
    base_admissions_url: str = "/admissions/{patient_record}"
    base_evolutions_url: str = ""


# ---------------------------------------------------------------------------
# Session handle protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SessionHandle(Protocol):
    """Abstract interface for a persistent legacy browser session.

    Implementations wrap Playwright page/browser objects or test fakes.
    """

    def get_page_html(self) -> str:
        """Return the current page HTML for policy inspection."""
        ...

    def is_connected(self) -> bool:
        """Return whether the browser is connected and responsive."""
        ...

    def click_selector(self, selector: str) -> None:
        """Click the element matching the given CSS selector."""
        ...

    def open_tab(self, url: str, *, timeout: int = 120) -> bool:
        """Open a new tab with the given URL and wait for render.

        Args:
            url: URL to navigate to.
            timeout: Maximum time in seconds to wait for the tab to open and
                render. Implementations backed by Playwright MUST honor this
                value in their navigation/wait calls.

        Returns:
            True if the tab opened and rendered successfully, False otherwise.
        """
        ...

    def get_tab_classes(self) -> list[str]:
        """Return class strings for each tab ``<li>`` in DOM order."""
        ...

    def close_last_non_root_tab(self) -> TabCleanupOutcome:
        """Close the last non-root legacy DOM tab and report the outcome.

        A PrimeFaces legacy tab is a DOM element inside ONE Playwright Page;
        implementations MUST click the centralized DOM close control on the
        active page (never close a Playwright Page) and verify the safe state
        within a bounded timeout (PSW-S18 R2/R3/R4).

        Returns:
            :attr:`~session_policy.TabCleanupOutcome.ROOT_ONLY` when only the
            root tab exists (no click);
            :attr:`~session_policy.TabCleanupOutcome.CLOSED_AND_VERIFIED` when
            a tab was closed and the safe state was observed;
            :attr:`~session_policy.TabCleanupOutcome.UNSAFE` when close/verify
            could not be completed.
        """
        ...

    def restart_browser(self) -> None:
        """Restart the browser/session completely."""
        ...


# ---------------------------------------------------------------------------
# Session Controller
# ---------------------------------------------------------------------------


class PersistentSessionController:
    """Manages a persistent legacy browser session across ingestion jobs.

    The controller encapsulates session health checks, proactive and
    defensive renewal, tab cleanup, job counting, failure tracking,
    and restart decisions. It delegates DOM parsing and policy decisions
    to ``session_policy`` primitives and interacts with the browser
    through a ``SessionHandle`` abstract interface.
    """

    def __init__(
        self,
        session: SessionHandle,
        config: SessionControllerConfig | None = None,
    ) -> None:
        self._session = session
        self.config = config or SessionControllerConfig()

        # --- Lifecycle counters ---
        self.jobs_processed: int = 0
        self.consecutive_failures: int = 0
        self._session_start_time: float = time.monotonic()
        # PSW-S18 R6: an unsafe cleanup forces recovery (restart) before the
        # next claim. This flag is set on UNSAFE, preserved by
        # ``mark_job_processed`` (R7), surfaced by ``restart_required``, and
        # cleared only by ``reset_after_restart`` (actual recovery).
        self._recovery_required: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_ready(self) -> bool:
        """Ensure the browser session is ready for work.

        Checks connection status, handles the renewal popup if visible,
        and verifies the session counter is present and valid.

        Returns:
            True if the session is ready, False if recovery is needed.
        """
        if not self._session.is_connected():
            self._increment_failure()
            return False

        # Defensive: handle visible popup before checking counter.
        html = self._session.get_page_html()
        if is_renewal_popup_visible(html):
            self._session.click_selector(SEL_RENEWAL_BUTTON)
            # After clicking, re-read the page HTML.
            html = self._session.get_page_html()

        # Verify session counter is present.
        remaining = parse_session_countdown(html)
        if remaining is None:
            self._increment_failure()
            return False

        return True

    def renew_if_needed(self) -> bool:
        """Proactively renew the session if remaining time is low.

        Opens the configured safe renewal tab when the session counter
        falls below the threshold. Handles the renewal popup defensively
        before opening the tab.

        Returns:
            True if renewal succeeded or was unnecessary, False on failure.
        """
        # Defensive: handle visible popup first.
        html = self._session.get_page_html()
        if is_renewal_popup_visible(html):
            self._session.click_selector(SEL_RENEWAL_BUTTON)
            html = self._session.get_page_html()

        remaining = parse_session_countdown(html)

        # If counter is missing/malformed, try renewal defensively.
        if remaining is None or remaining < self.config.renewal_threshold_seconds:
            return self.open_safe_renewal_tab()

        return True

    def open_safe_renewal_tab(self) -> bool:
        """Open the configured safe renewal tab and verify counter reset.

        Opens the safe URL in a new tab and checks that the session
        counter resets (or is present and above a minimal threshold)
        as evidence of successful renewal.

        Returns:
            True if the counter reset was verified, False otherwise.
        """
        if not self.config.safe_renewal_tab_url:
            self._increment_failure()
            return False

        # Parse counter before opening tab.
        html_before = self._session.get_page_html()
        before = parse_session_countdown(html_before)

        # Open the safe tab.
        tab_opened = self._session.open_tab(self.config.safe_renewal_tab_url)
        if not tab_opened:
            self._increment_failure()
            return False

        # Check counter after tab render.
        html_after = self._session.get_page_html()
        after = parse_session_countdown(html_after)

        # Verify counter reset: must be present and higher than before
        # (or at least higher than a minimal threshold indicating reset).
        if after is None:
            self._increment_failure()
            return False

        if before is not None and after <= before:
            self._increment_failure()
            return False

        # Successful renewal — reset failure counter.
        self.consecutive_failures = 0
        return True

    def close_job_tab_if_present(self) -> TabCleanupOutcome:
        """Close the last non-root legacy DOM tab after job completion.

        PSW-S18: reports exactly one of three cleanup outcomes and drives
        controller recovery state. Tab close is cleanup only — it never
        resets the failure counter or acts as renewal evidence (R5).

        Returns:
            :attr:`~session_policy.TabCleanupOutcome.ROOT_ONLY` when only the
            root tab exists (no close attempted);
            :attr:`~session_policy.TabCleanupOutcome.CLOSED_AND_VERIFIED` when
            a tab was closed and verified;
            :attr:`~session_policy.TabCleanupOutcome.UNSAFE` when the state is
            ambiguous or close/verify failed (recovery is forced before the
            next claim).
        """
        tab_classes = self._session.get_tab_classes()
        action = decide_tab_cleanup(tab_classes)

        if action == TabCleanupAction.PRESERVE_ROOT:
            return TabCleanupOutcome.ROOT_ONLY

        if action == TabCleanupAction.RECOVERY_REQUIRED:
            self._mark_unsafe_cleanup()
            return TabCleanupOutcome.UNSAFE

        # CLOSE_LAST_NON_ROOT: perform the concrete close + verify on the
        # active page and react to the reported outcome.
        outcome = self._session.close_last_non_root_tab()
        if outcome == TabCleanupOutcome.CLOSED_AND_VERIFIED:
            return TabCleanupOutcome.CLOSED_AND_VERIFIED
        if outcome == TabCleanupOutcome.ROOT_ONLY:
            # Race: the tab already disappeared and root-only was observed —
            # the safe state holds, no recovery needed.
            return TabCleanupOutcome.ROOT_ONLY
        # UNSAFE (or any unexpected value): force recovery before next claim.
        self._mark_unsafe_cleanup()
        return TabCleanupOutcome.UNSAFE

    def mark_job_processed(self) -> None:
        """Record a successfully processed job.

        Increments the job counter and resets the consecutive failure
        counter — EXCEPT when an unsafe cleanup forced recovery (PSW-S18 R7):
        in that case the cleanup failure must survive job accounting so the
        next claim stays blocked until an actual restart.
        """
        self.jobs_processed += 1
        if not self._recovery_required:
            self.consecutive_failures = 0

    def restart_required(self) -> bool:
        """Determine whether the browser session should be restarted.

        Checks all configured thresholds:
        - Browser disconnected.
        - Max jobs per session exceeded.
        - Max consecutive failures exceeded.
        - Max browser lifetime exceeded.

        Returns:
            True if a restart is needed at the next safe point.
        """
        # PSW-S18 R6: an unsafe cleanup forces recovery before the next claim.
        if self._recovery_required:
            return True

        if not self._session.is_connected():
            return True

        if self.jobs_processed >= self.config.max_jobs_per_session:
            return True

        if self.consecutive_failures >= self.config.max_consecutive_failures:
            return True

        elapsed = time.monotonic() - self._session_start_time
        if elapsed >= self.config.max_lifetime_seconds:
            return True

        return False

    def reset_after_restart(self) -> None:
        """Reset lifecycle counters after a browser restart.

        Call this after the caller has performed the actual browser
        restart (via ``SessionHandle.restart_browser()``).
        """
        self.jobs_processed = 0
        self.consecutive_failures = 0
        self._recovery_required = False
        self._session_start_time = time.monotonic()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _increment_failure(self) -> None:
        """Increment the consecutive failure counter."""
        self.consecutive_failures += 1

    def _mark_unsafe_cleanup(self) -> None:
        """Record an unsafe tab cleanup (PSW-S18 R6).

        Increments/preserves controller failure state and flags that
        recovery (restart) is required before the next claim.
        """
        self._increment_failure()
        self._recovery_required = True
