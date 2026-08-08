"""Real Playwright-based SessionHandle (PSW-S5).

Provides a concrete implementation of the ``SessionHandle`` protocol
that owns a Playwright Chromium browser, manages exclusive per-process
browser profiles, and exposes the operations required by the
``PersistentSessionController`` and ``PersistentExtractionAdapter``.

Design (per ``design.md`` Decision 6):
- Each ``PlaywrightSessionHandle`` uses an ``ExclusiveBrowserProfile``
  for its Chromium user data directory, guaranteeing path exclusivity.
- ``acquire()`` is called on ``start()``, ``release_after_shutdown()``
  is called on ``shutdown()`` and ``restart_browser()``.
- Timeout values (seconds) are converted to milliseconds for Playwright
  API calls (``page.goto``, page wait actions).
- Tab cleanup uses the session policy primitives for deciding which
  tab to close.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from apps.ingestion.extractors.browser_profile import ExclusiveBrowserProfile
from apps.ingestion.extractors.errors import (
    ExtractionTimeoutError,
    is_playwright_timeout_error,
)
from apps.ingestion.extractors.session_policy import (
    SEL_TAB_LAST_CLOSE,
    TabCleanupAction,
    TabCleanupOutcome,
    decide_tab_cleanup,
)
from automation.source_system.proxy_config import get_playwright_proxy

logger = logging.getLogger(__name__)

# Default timeout in seconds for navigation if none is provided
_DEFAULT_NAVIGATION_TIMEOUT_SECONDS = 120

# PSW-S18 R4: bounded budget (seconds) to click the DOM close control and
# verify the tab count decreased / root-only state was restored. Cleanup is
# post-run housekeeping, so this stays short and bounded.
_DEFAULT_TAB_CLOSE_VERIFY_TIMEOUT_SECONDS = 5


class PlaywrightSessionHandle:
    """Real Playwright-backed implementation of the SessionHandle protocol.

    Wraps a Playwright ``Browser``, ``BrowserContext``, and ``Page`` to
    provide the session lifecycle operations consumed by the persistent
    ingestion controller and adapter.

    Args:
        profile: An ``ExclusiveBrowserProfile`` for the Chromium user data
            directory. If ``None``, a default ephemeral profile is created.
        headless: Whether to launch Chromium in headless mode.
    """

    def __init__(
        self,
        profile: ExclusiveBrowserProfile | None = None,
        headless: bool = True,
    ) -> None:
        self._profile = profile or ExclusiveBrowserProfile()
        self._headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._started: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Acquire the exclusive profile and launch the browser.

        Idempotent: calling ``start()`` twice does not re-launch.
        """
        if self._started:
            return
        self._started = True

        # Acquire exclusive profile path.
        profile_path = self._profile.acquire()

        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().__enter__()

        launch_kwargs: dict[str, Any] = {
            "headless": self._headless,
            "ignore_https_errors": True,
            "user_data_dir": str(profile_path),
        }
        proxy = get_playwright_proxy()
        if proxy is not None:
            launch_kwargs["proxy"] = proxy
        self._browser = self._playwright.chromium.launch_persistent_context(
            **launch_kwargs,
        )
        self._context = self._browser

    def shutdown(self) -> None:
        """Close the browser and release the exclusive profile.

        Safe to call even if ``start()`` was never called.
        """
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                logger.warning("Error closing browser (sanitized)")
            self._browser = None
            self._context = None

        if self._playwright is not None:
            try:
                # ``sync_playwright().__enter__()`` returns the public
                # Playwright object. Its matching public teardown API is
                # ``stop()``; the returned object is not the context manager.
                self._playwright.stop()
            except Exception:
                logger.warning("Error stopping Playwright (sanitized)")
            self._playwright = None

        if self._profile.is_in_use:
            self._profile.release_after_shutdown(remove=False)

        self._started = False

    # ------------------------------------------------------------------
    # SessionHandle protocol
    # ------------------------------------------------------------------

    def get_page_html(self) -> str:
        """Return the current page HTML.

        PSW-S17 final closure (D3): a real Playwright timeout from
        ``page.content()`` propagates as a typed
        :class:`ExtractionTimeoutError` so the run records
        ``failure_reason=timeout``. Non-timeout failures keep the legacy
        empty-string return with a constant sanitized log (no raw
        exception, URL, cookie, or traceback).
        """
        page = self._current_page()
        if page is None:
            return ""
        try:
            return page.content()
        except Exception as exc:
            if is_playwright_timeout_error(exc):
                raise ExtractionTimeoutError(
                    "Persistent session page content read timed out."
                ) from None
            logger.warning(
                "Persistent session get_page_html failed (sanitized)"
            )
            return ""

    def is_connected(self) -> bool:
        """Return whether the browser is connected and responsive."""
        if self._browser is None:
            return False
        try:
            # Check if the context has any pages (a minimal connectivity check).
            if self._context is not None:
                return True
            return False
        except Exception:
            return False

    def click_selector(self, selector: str) -> None:
        """Click the element matching the given CSS selector.

        PSW-S17 final closure (D3): a real Playwright timeout propagates
        as a typed :class:`ExtractionTimeoutError`. Non-timeout failures
        log a constant sanitized message (no selector or raw exception).
        """
        page = self._current_page()
        if page is None:
            logger.warning(
                "Persistent session click_selector failed (sanitized)"
            )
            return
        try:
            page.locator(selector).click()
        except Exception as exc:
            if is_playwright_timeout_error(exc):
                raise ExtractionTimeoutError(
                    "Persistent session selector click timed out."
                ) from None
            logger.warning(
                "Persistent session click_selector failed (sanitized)"
            )

    def open_tab(self, url: str, *, timeout: int = _DEFAULT_NAVIGATION_TIMEOUT_SECONDS) -> bool:
        """Open a new tab with the given URL and wait for render.

        Args:
            url: URL to navigate to.
            timeout: Maximum time in seconds to wait for the tab to load.
                Converted to milliseconds for Playwright's ``goto``.

        Returns:
            ``True`` if the tab opened and rendered successfully,
            ``False`` for non-timeout navigation failures.

        Raises:
            ExtractionTimeoutError: when Playwright signals a navigation
                timeout. PSW-S17 R2/R3: the typed timeout must cross the
                adapter/command boundary so the run records
                ``failure_reason=timeout``. Non-timeout failures keep the
                ``False`` return for compatibility with existing callers.
        """
        if self._context is None:
            return False

        try:
            page = self._context.new_page()
            timeout_ms = timeout * 1000
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            return True
        except Exception as exc:
            # PSW-S17 R2/R3: a Playwright navigation timeout must surface as
            # a typed ExtractionTimeoutError so the shared classifier maps
            # the run/attempt to ("timeout", True). The constant message
            # contains no URL, cookie, credential, or raw payload.
            if is_playwright_timeout_error(exc):
                raise ExtractionTimeoutError(
                    "Persistent session navigation timed out."
                ) from None
            # Non-timeout failures keep the legacy False return; the log
            # message is constant and sanitized (no URL, no raw exception).
            logger.warning("Persistent session open_tab failed (sanitized)")
            return False

    def get_tab_classes(self) -> list[str]:
        """Query the DOM for tab ``<li>`` class strings.

        Evaluates JavaScript on the current page to extract class
        attributes from each tab ``<li>`` element in DOM order.

        PSW-S17 final closure (D3): a real Playwright timeout propagates
        as a typed :class:`ExtractionTimeoutError`. Non-timeout failures
        return ``[]`` with a constant sanitized log.
        """
        page = self._current_page()
        if page is None:
            return []
        try:
            result = page.evaluate(
                """() => {
                    const tabs = document.querySelectorAll('li[id$=":tab"]');
                    return Array.from(tabs).map(t => t.className);
                }"""
            )
            if isinstance(result, list):
                return [str(cls) for cls in result]
            return []
        except Exception as exc:
            if is_playwright_timeout_error(exc):
                raise ExtractionTimeoutError(
                    "Persistent session tab-class read timed out."
                ) from None
            logger.warning(
                "Persistent session get_tab_classes failed (sanitized)"
            )
            return []

    def close_last_non_root_tab(
        self, *, timeout: int = _DEFAULT_TAB_CLOSE_VERIFY_TIMEOUT_SECONDS
    ) -> TabCleanupOutcome:
        """Close the last non-root legacy DOM tab and verify the safe state.

        PSW-S18 R2/R3/R4: a PrimeFaces legacy tab is a DOM ``<li>`` element
        inside ONE Playwright Page — it is NOT a ``BrowserContext.pages``
        entry. This clicks the centralized DOM close control
        (``SEL_TAB_LAST_CLOSE``) on the active page and verifies the DOM tab
        count decreased or the root-only state was restored within a bounded
        timeout. It NEVER closes a Playwright Page.

        PSW-S18 R9: cleanup failures are sanitized (constant log messages)
        and mapped to :attr:`~session_policy.TabCleanupOutcome.UNSAFE`; they
        are never re-raised and never classify the run as a source timeout
        (cleanup is post-run housekeeping, not extraction).

        Args:
            timeout: Bounded budget (seconds) shared by the click and the
                verification poll.

        Returns:
            :attr:`~session_policy.TabCleanupOutcome.ROOT_ONLY` when only the
            root tab exists (no click);
            :attr:`~session_policy.TabCleanupOutcome.CLOSED_AND_VERIFIED`
            when a tab was closed and the safe state was observed;
            :attr:`~session_policy.TabCleanupOutcome.UNSAFE` when close/verify
            could not be completed.
        """
        page = self._current_page()
        if page is None:
            logger.warning(
                "Persistent session tab cleanup: no active page (sanitized)"
            )
            return TabCleanupOutcome.UNSAFE

        try:
            classes_before = self.get_tab_classes()
        except Exception:  # noqa: BLE001 - sanitized cleanup failure
            logger.warning(
                "Persistent session tab cleanup: tab read failed (sanitized)"
            )
            return TabCleanupOutcome.UNSAFE

        action = decide_tab_cleanup(classes_before)
        if action == TabCleanupAction.PRESERVE_ROOT:
            return TabCleanupOutcome.ROOT_ONLY
        if action == TabCleanupAction.RECOVERY_REQUIRED:
            return TabCleanupOutcome.UNSAFE

        # CLOSE_LAST_NON_ROOT: click the centralized DOM close control.
        try:
            page.locator(SEL_TAB_LAST_CLOSE).click(timeout=timeout * 1000)
        except Exception:  # noqa: BLE001 - sanitized cleanup failure
            logger.warning(
                "Persistent session tab cleanup: close click failed (sanitized)"
            )
            return TabCleanupOutcome.UNSAFE

        # Verify the tab count decreased or root-only state was restored
        # within the bounded timeout. PSW-S18-C1 (gap 1): a failed/empty read,
        # a reduction to zero, a removal of more than one tab, or an ambiguous
        # resulting state must never produce CLOSED_AND_VERIFIED.
        deadline = time.monotonic() + timeout
        while True:
            try:
                classes_after = self.get_tab_classes()
            except Exception:  # noqa: BLE001 - sanitized cleanup failure
                logger.warning(
                    "Persistent session tab cleanup: verify read failed (sanitized)"
                )
                return TabCleanupOutcome.UNSAFE
            if (
                classes_after
                and len(classes_after) == len(classes_before) - 1
                and decide_tab_cleanup(classes_after) != TabCleanupAction.RECOVERY_REQUIRED
                # PSW-S18-C2 R1: the root tab must survive in first position.
                and "tabs-first" in classes_after[0].split()
            ):
                return TabCleanupOutcome.CLOSED_AND_VERIFIED
            if time.monotonic() >= deadline:
                return TabCleanupOutcome.UNSAFE
            time.sleep(0.05)

    def restart_browser(self) -> None:
        """Restart the browser and session completely.

        Closes the current browser, releases the old profile, acquires a
        fresh profile, and launches a new browser.
        """
        # Close the current browser.
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                logger.warning(
                    "Error closing browser during restart (sanitized)"
                )
            self._browser = None
            self._context = None

        # Release the old profile (no destructive cleanup).
        if self._profile.is_in_use:
            self._profile.release_after_shutdown(remove=False)

        # Acquire a new profile (reuses the same ``ExclusiveBrowserProfile``
        # instance; ``acquire()`` is idempotent — it creates the directory if
        # missing and writes the ownership marker).
        profile_path = self._profile.acquire()

        from playwright.sync_api import sync_playwright

        # Close old Playwright instance.
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                logger.warning(
                    "Error stopping Playwright during restart (sanitized)"
                )

        # Launch a fresh Playwright + browser.
        self._playwright = sync_playwright().__enter__()
        launch_kwargs: dict[str, Any] = {
            "headless": self._headless,
            "ignore_https_errors": True,
            "user_data_dir": str(profile_path),
        }
        proxy = get_playwright_proxy()
        if proxy is not None:
            launch_kwargs["proxy"] = proxy
        self._browser = self._playwright.chromium.launch_persistent_context(
            **launch_kwargs,
        )
        self._context = self._browser

    # ------------------------------------------------------------------
    # Bootstrap-level access (PSW-S10)
    # ------------------------------------------------------------------

    def ensure_current_page(self):
        """Return an active page, creating one if none exists.

        Guarantees the bootstrap path has a page to operate on even when the
        persistent browser context (``launch_persistent_context``) opened
        without pages. When a page already exists, it is reused and
        ``new_page()`` is not called.

        Used by the persistent worker's ``--real-handle`` path to obtain the
        root page for the legacy login bootstrap
        (:func:`bootstrap_legacy_session`) before the handle is wrapped in
        ``RealHandleBridge``. This is the only sanctioned escape hatch for
        Playwright-specific operations not covered by the ``SessionHandle``
        protocol.

        Returns:
            The currently active (last used) Playwright ``Page``, or a freshly
            created page if none exists. Returns ``None`` when the browser
            context has not been started or a new page cannot be created.
        """
        page = self._current_page()
        if page is not None:
            return page
        if self._context is None:
            return None
        try:
            return self._context.new_page()
        except Exception:
            logger.warning(
                "Failed to create initial page for bootstrap (sanitized)"
            )
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_page(self):
        """Return the currently active (last used) page, or None."""
        if self._context is None:
            return None
        pages = self._context.pages
        if not pages:
            return None
        return pages[-1]
