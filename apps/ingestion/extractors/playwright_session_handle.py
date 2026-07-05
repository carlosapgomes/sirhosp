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
from typing import Any

from apps.ingestion.extractors.browser_profile import ExclusiveBrowserProfile

logger = logging.getLogger(__name__)

# Default timeout in seconds for navigation if none is provided
_DEFAULT_NAVIGATION_TIMEOUT_SECONDS = 120


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
            "user_data_dir": str(profile_path),
        }
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
            except Exception as exc:
                logger.warning("Error closing browser: %s", exc)
            self._browser = None
            self._context = None

        if self._playwright is not None:
            try:
                self._playwright.__exit__(None, None, None)
            except Exception as exc:
                logger.warning("Error stopping Playwright: %s", exc)
            self._playwright = None

        if self._profile.is_in_use:
            self._profile.release_after_shutdown(remove=False)

        self._started = False

    # ------------------------------------------------------------------
    # SessionHandle protocol
    # ------------------------------------------------------------------

    def get_page_html(self) -> str:
        """Return the current page HTML."""
        page = self._current_page()
        if page is None:
            return ""
        try:
            return page.content()
        except Exception:
            logger.warning("Failed to get page HTML", exc_info=True)
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
        """Click the element matching the given CSS selector."""
        page = self._current_page()
        if page is None:
            logger.warning("Cannot click selector %r — no page available", selector)
            return
        try:
            page.locator(selector).click()
        except Exception as exc:
            logger.warning("Failed to click selector %r: %s", selector, exc)

    def open_tab(self, url: str, *, timeout: int = _DEFAULT_NAVIGATION_TIMEOUT_SECONDS) -> bool:
        """Open a new tab with the given URL and wait for render.

        Args:
            url: URL to navigate to.
            timeout: Maximum time in seconds to wait for the tab to load.
                Converted to milliseconds for Playwright's ``goto``.

        Returns:
            ``True`` if the tab opened and rendered successfully,
            ``False`` otherwise.
        """
        if self._context is None:
            return False

        try:
            page = self._context.new_page()
            timeout_ms = timeout * 1000
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            return True
        except Exception as exc:
            logger.warning("Failed to open tab %r: %s", url, exc)
            return False

    def get_tab_classes(self) -> list[str]:
        """Query the DOM for tab ``<li>`` class strings.

        Evaluates JavaScript on the current page to extract class
        attributes from each tab ``<li>`` element in DOM order.
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
            logger.warning("Failed to get tab classes: %s", exc)
            return []

    def close_last_non_root_tab(self) -> None:
        """Close the last non-root operational tab.

        Closes the last page in the context if there are at least 2 pages,
        preserving the root tab (the first page opened).
        """
        if self._context is None:
            return
        pages = self._context.pages
        if len(pages) >= 2:
            last_page = pages[-1]
            try:
                last_page.close()
            except Exception as exc:
                logger.warning("Failed to close last non-root tab: %s", exc)

    def restart_browser(self) -> None:
        """Restart the browser and session completely.

        Closes the current browser, releases the old profile, acquires a
        fresh profile, and launches a new browser.
        """
        # Close the current browser.
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception as exc:
                logger.warning("Error closing browser during restart: %s", exc)
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
                self._playwright.__exit__(None, None, None)
            except Exception as exc:
                logger.warning("Error stopping Playwright during restart: %s", exc)

        # Launch a fresh Playwright + browser.
        self._playwright = sync_playwright().__enter__()
        launch_kwargs: dict[str, Any] = {
            "headless": self._headless,
            "user_data_dir": str(profile_path),
        }
        self._browser = self._playwright.chromium.launch_persistent_context(
            **launch_kwargs,
        )
        self._context = self._browser

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
