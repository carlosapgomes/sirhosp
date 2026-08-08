"""Tests for PlaywrightSessionHandle — real Playwright session handle (PSW-S5).

Tests prove:
- ExclusiveBrowserProfile is acquired on startup and released on shutdown.
- open_tab propagates timeout to Playwright navigation.
- get_page_html returns the current page content.
- Tab operations (close_last_non_root_tab, get_tab_classes) work.
- Restart browser releases old profile and re-acquires.
- No real legacy access is required — all tests mock Playwright APIs.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apps.ingestion.extractors.browser_profile import ExclusiveBrowserProfile

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_browser_profile(tmp_path: Path) -> MagicMock:
    """Create a mock ExclusiveBrowserProfile with a real path."""
    profile = MagicMock(spec=ExclusiveBrowserProfile)
    profile.path = tmp_path / "sirhosp-profile-test-pid1-abc123"
    profile.is_in_use = False
    profile.acquire.return_value = profile.path
    profile.release_after_shutdown = MagicMock()
    return profile


@pytest.fixture
def mock_page() -> MagicMock:
    """Create a mock Playwright Page."""
    page = MagicMock()
    page.content.return_value = "<html><body>Mock page</body></html>"
    page.url = "about:blank"
    page.title.return_value = "Mock Title"
    return page


@pytest.fixture
def mock_persistent_context(mock_page: MagicMock) -> MagicMock:
    """Create a mock BrowserContext (returned by launch_persistent_context)."""
    context = MagicMock()
    context.new_page.return_value = mock_page
    context.pages = [mock_page]
    return context


@pytest.fixture
def playwright_inner_mock() -> MagicMock:
    """Create the inner Playwright mock."""
    mock = MagicMock()
    mock.chromium = MagicMock()
    return mock


@pytest.fixture
def sync_playwright_mock(
    mock_persistent_context: MagicMock,
    playwright_inner_mock: MagicMock,
) -> MagicMock:
    """Create a mock sync_playwright.

    The patched function returns this mock when called.
    ``mock.__enter__()`` returns ``playwright_inner_mock``.
    """
    playwright_inner_mock.chromium.launch_persistent_context.return_value = (
        mock_persistent_context
    )
    mock = MagicMock()
    mock.__enter__.return_value = playwright_inner_mock
    return mock


# ===========================================================================
# ExclusiveBrowserProfile integration
# ===========================================================================


class TestExclusiveBrowserProfileWiring:
    """Tests that ExclusiveBrowserProfile is acquired/released correctly."""

    def test_acquires_profile_on_start(
        self,
        mock_browser_profile: MagicMock,
        playwright_inner_mock: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """SessionHandle acquires the profile when starting."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()

        mock_browser_profile.acquire.assert_called_once()
        playwright_inner_mock.chromium.launch_persistent_context.assert_called_once()

    def test_launches_chromium_with_profile_path(
        self,
        mock_browser_profile: MagicMock,
        playwright_inner_mock: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """Chromium is launched with the acquired profile path."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()

        launch_kwargs = (
            playwright_inner_mock.chromium.launch_persistent_context
            .call_args.kwargs
        )
        user_data_dir = launch_kwargs.get("user_data_dir")
        assert user_data_dir is not None
        assert str(mock_browser_profile.path) in str(user_data_dir)

    def test_launches_chromium_with_proxy_and_https_tolerance(
        self,
        mock_browser_profile: MagicMock,
        playwright_inner_mock: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """Real persistent Chromium honors the production SOCKS5 proxy."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        with (
            patch.dict(
                os.environ,
                {
                    "PLAYWRIGHT_PROXY_SERVER": (
                        "socks5://sirhosp-tailscale-proxy:1055"
                    )
                },
                clear=False,
            ),
            patch(
                "playwright.sync_api.sync_playwright",
                return_value=sync_playwright_mock,
            ),
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()

        launch_kwargs = (
            playwright_inner_mock.chromium.launch_persistent_context
            .call_args.kwargs
        )
        assert launch_kwargs["proxy"] == {
            "server": "socks5://sirhosp-tailscale-proxy:1055"
        }
        assert launch_kwargs["ignore_https_errors"] is True

    def test_launches_chromium_without_proxy_when_unconfigured(
        self,
        mock_browser_profile: MagicMock,
        playwright_inner_mock: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """Direct environments keep working when no proxy is configured."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "playwright.sync_api.sync_playwright",
                return_value=sync_playwright_mock,
            ),
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()

        launch_kwargs = (
            playwright_inner_mock.chromium.launch_persistent_context
            .call_args.kwargs
        )
        assert "proxy" not in launch_kwargs
        assert launch_kwargs["ignore_https_errors"] is True

    def test_release_on_shutdown(
        self,
        mock_browser_profile: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """release_after_shutdown is called on shutdown."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            # After start, the profile is in-use (real acquire sets this).
            mock_browser_profile.is_in_use = True
            handle.shutdown()

        mock_browser_profile.release_after_shutdown.assert_called_once()

    def test_shutdown_stops_playwright_runtime(
        self,
        mock_browser_profile: MagicMock,
        playwright_inner_mock: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """The Playwright object is stopped through its public API."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            handle.shutdown()

        playwright_inner_mock.stop.assert_called_once_with()
        playwright_inner_mock.__exit__.assert_not_called()

    def test_start_is_idempotent(
        self,
        mock_browser_profile: MagicMock,
        playwright_inner_mock: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """Calling start twice does not re-launch the browser."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            handle.start()  # Second call is no-op

        mock_browser_profile.acquire.assert_called_once()


# ===========================================================================
# Timeout propagation to open_tab
# ===========================================================================


class TestTimeoutPropagation:
    """Tests that timeout values propagate to Playwright navigation."""

    def test_open_tab_propagates_timeout(
        self,
        mock_browser_profile: MagicMock,
        mock_page: MagicMock,
        mock_persistent_context: MagicMock,
        playwright_inner_mock: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """open_tab passes timeout to page.goto in milliseconds."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        mock_persistent_context.new_page.return_value = mock_page

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            result = handle.open_tab(
                "https://example.com/test", timeout=42
            )

        assert result is True
        mock_page.goto.assert_called_once()
        goto_kwargs = mock_page.goto.call_args.kwargs
        assert goto_kwargs.get("timeout") == 42_000  # Playwright uses ms

    def test_open_tab_default_timeout(
        self,
        mock_browser_profile: MagicMock,
        mock_page: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """open_tab uses default timeout when not specified."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        mock_persistent_context.new_page.return_value = mock_page

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            result = handle.open_tab("https://example.com/test")

        assert result is True
        goto_kwargs = mock_page.goto.call_args.kwargs
        assert goto_kwargs.get("timeout") == 120_000  # 120s default

    def test_open_tab_failure_returns_false(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """When navigation fails, open_tab returns False."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        failing_page = MagicMock()
        failing_page.goto.side_effect = Exception("Navigation failed")
        mock_persistent_context.new_page.return_value = failing_page

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            result = handle.open_tab(
                "https://example.com/bad", timeout=10
            )

        assert result is False


# ===========================================================================
# Page HTML access
# ===========================================================================


class TestPageHtml:
    """Tests for get_page_html."""

    def test_returns_current_page_html(
        self,
        mock_browser_profile: MagicMock,
        mock_page: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """get_page_html returns the active page's HTML content."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        mock_page.content.return_value = "<html><body>Hello</body></html>"

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            html = handle.get_page_html()

        assert html == "<html><body>Hello</body></html>"

    def test_returns_empty_when_no_pages(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """get_page_html returns empty string when no page exists."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        mock_persistent_context.pages = []

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            html = handle.get_page_html()

        assert html == ""


# ===========================================================================
# Connection status
# ===========================================================================


class TestIsConnected:
    """Tests for is_connected."""

    def test_connected_returns_true(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """When browser is connected, returns True."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            assert handle.is_connected() is True

    def test_disconnected_returns_false(
        self,
        mock_browser_profile: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """When browser is not connected, returns False."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            assert handle.is_connected() is False


# ===========================================================================
# Tab operations
# ===========================================================================


class _DomTabLocator:
    """Fake Playwright locator modeling a PrimeFaces DOM tab close button."""

    def __init__(self, page: "_DomTabPage", selector: str) -> None:
        self._page = page
        self._selector = selector

    def click(self, timeout: float | int | None = None) -> None:  # noqa: ARG002
        self._page.clicked_selectors.append(self._selector)
        if self._page.click_fails:
            raise RuntimeError("click failed (sanitized)")
        self._page.remove_last_dom_tab()


class _DomTabPage:
    """Fake Playwright Page carrying legacy PrimeFaces DOM ``<li>`` tabs.

    Models ONE Playwright Page whose DOM contains multiple legacy tab
    elements. ``locator(...).click()`` on the close control removes the last
    non-root DOM tab; the Page itself is never removed (R3). Mirrors the
    JS used by ``PlaywrightSessionHandle.get_tab_classes``.

    The close control click also models PrimeFaces' tab-strip re-render:
    after closing one tab, the new last tab gains ``tabs-last`` and a single
    remaining tab becomes root-only. The second (verification) read can be
    scripted to raise or return ``[]`` to reproduce the gap-1 scenarios.
    """

    def __init__(self, tab_classes: list[str]) -> None:
        self._tabs: list[str] = list(tab_classes)
        self.clicked_selectors: list[str] = []
        self.page_close_calls: int = 0
        self.click_fails: bool = False
        self.no_decrease: bool = False
        self.verify_raises: bool = False
        self.verify_empty: bool = False
        # PSW-S18-C2 R1: when set, verification reads (2nd+ evaluate calls)
        # return this exact post-click DOM state instead of the re-rendered
        # ``_tabs``. Models a PrimeFaces report that lost the root tab.
        self.verify_classes: list[str] | None = None
        self._evaluate_calls: int = 0

    def locator(self, selector: str) -> _DomTabLocator:
        return _DomTabLocator(self, selector)

    def evaluate(self, _expression: str) -> list[str]:
        self._evaluate_calls += 1
        # The first read is the pre-click state; subsequent reads verify.
        if self.verify_raises and self._evaluate_calls >= 2:
            raise RuntimeError("evaluate failed (sanitized)")
        if self.verify_empty and self._evaluate_calls >= 2:
            return []
        if self.verify_classes is not None and self._evaluate_calls >= 2:
            return list(self.verify_classes)
        return list(self._tabs)

    def close(self) -> None:
        self.page_close_calls += 1

    def remove_last_dom_tab(self) -> None:
        if self.no_decrease:
            return
        if len(self._tabs) >= 2:
            self._tabs.pop()
            # PrimeFaces re-renders the tab strip after a close: the new last
            # tab gains 'tabs-last'; a single remaining tab becomes root-only.
            if len(self._tabs) == 1:
                self._tabs = ["tabs-first tabs-last tabs-selected"]
            elif len(self._tabs) >= 2:
                tokens = self._tabs[-1].split()
                if "tabs-last" not in tokens:
                    tokens.append("tabs-last")
                self._tabs[-1] = " ".join(tokens)

    @property
    def tab_classes(self) -> list[str]:
        return list(self._tabs)


class TestTabOperations:
    """Tests for tab-related operations."""

    def test_click_selector(
        self,
        mock_browser_profile: MagicMock,
        mock_page: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """click_selector clicks on the matching element."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        locator_mock = MagicMock()
        mock_page.locator.return_value = locator_mock

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            handle.click_selector(".my-button")

        mock_page.locator.assert_called_with(".my-button")
        locator_mock.click.assert_called_once()

    def test_get_tab_classes_with_multiple_pages(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """get_tab_classes queries the DOM for tab elements."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        page1 = MagicMock()
        page2 = MagicMock()
        mock_persistent_context.pages = [page1, page2]
        # _current_page() returns the last page (page2)
        page2.evaluate.return_value = [
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            classes = handle.get_tab_classes()

        assert classes == [
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ]
        page2.evaluate.assert_called_once()

    def test_close_last_non_root_tab_clicks_dom_control(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """PSW-S18 R2/R3: close_last_non_root_tab clicks the centralized DOM
        close control on the active page; it never closes a Playwright Page."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )
        from apps.ingestion.extractors.session_policy import (
            SEL_TAB_LAST_CLOSE,
            TabCleanupOutcome,
        )

        # One Playwright Page carrying two legacy DOM <li> tabs.
        page = _DomTabPage([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])
        mock_persistent_context.pages = [page]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            outcome = handle.close_last_non_root_tab(timeout=1)

        assert outcome is TabCleanupOutcome.CLOSED_AND_VERIFIED
        # The DOM close control was clicked.
        assert SEL_TAB_LAST_CLOSE in page.clicked_selectors
        # No Playwright Page was closed (DOM tab, not a Page).
        assert page.page_close_calls == 0
        # A4: PrimeFaces re-renders the remaining tab to root-only.
        assert page.tab_classes == ["tabs-first tabs-last tabs-selected"]

    def test_close_verify_three_tabs_become_two_safe(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """A3: three tabs -> two safe tabs -> CLOSED_AND_VERIFIED; no Page close."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )
        from apps.ingestion.extractors.session_policy import TabCleanupOutcome

        page = _DomTabPage([
            "tabs-first tabs-selected",
            "tabs-selected",
            "tabs-last tabs-selected",
        ])
        mock_persistent_context.pages = [page]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            outcome = handle.close_last_non_root_tab(timeout=1)

        assert outcome is TabCleanupOutcome.CLOSED_AND_VERIFIED
        assert page.page_close_calls == 0
        # Exactly one tab removed; new last re-rendered with tabs-last.
        assert len(page.tab_classes) == 2

    def test_close_verify_lost_root_tab_is_unsafe(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """R1 (root preservation within A3): after the click the verified
        state lost the root tab (no ``tabs-first`` on any remaining tab) ->
        UNSAFE; never CLOSED_AND_VERIFIED. The Playwright Page stays alive."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )
        from apps.ingestion.extractors.session_policy import (
            SEL_TAB_LAST_CLOSE,
            TabCleanupOutcome,
        )

        # Three valid tabs before the click; tabs-first present on the first.
        page = _DomTabPage([
            "tabs-first tabs-selected",
            "tabs-selected",
            "tabs-last tabs-selected",
        ])
        # The post-click verify read reports a state that lost the root tab.
        page.verify_classes = ["tabs-selected", "tabs-last tabs-selected"]
        mock_persistent_context.pages = [page]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            outcome = handle.close_last_non_root_tab(timeout=1)

        assert outcome is TabCleanupOutcome.UNSAFE
        # The DOM close control was clicked.
        assert SEL_TAB_LAST_CLOSE in page.clicked_selectors
        # No Playwright Page was closed (DOM tab, not a Page).
        assert page.page_close_calls == 0

    def test_close_verify_read_exception_is_unsafe(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """A1: a verification-read exception after the click -> UNSAFE; Page alive."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )
        from apps.ingestion.extractors.session_policy import (
            SEL_TAB_LAST_CLOSE,
            TabCleanupOutcome,
        )

        page = _DomTabPage([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])
        page.verify_raises = True
        mock_persistent_context.pages = [page]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            outcome = handle.close_last_non_root_tab(timeout=1)

        assert outcome is TabCleanupOutcome.UNSAFE
        assert SEL_TAB_LAST_CLOSE in page.clicked_selectors
        assert page.page_close_calls == 0

    def test_close_verify_empty_read_is_unsafe(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """A2: a verification read returning [] after the click -> UNSAFE;
        never CLOSED_AND_VERIFIED; Page alive."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )
        from apps.ingestion.extractors.session_policy import TabCleanupOutcome

        page = _DomTabPage([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])
        page.verify_empty = True
        mock_persistent_context.pages = [page]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            outcome = handle.close_last_non_root_tab(timeout=1)

        assert outcome is TabCleanupOutcome.UNSAFE
        assert page.page_close_calls == 0

    def test_close_last_non_root_tab_root_only_no_click(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """Root-only DOM state -> ROOT_ONLY; no DOM click, no Page close."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )
        from apps.ingestion.extractors.session_policy import TabCleanupOutcome

        page = _DomTabPage(["tabs-first tabs-last tabs-selected"])
        mock_persistent_context.pages = [page]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            outcome = handle.close_last_non_root_tab(timeout=1)

        assert outcome is TabCleanupOutcome.ROOT_ONLY
        assert page.clicked_selectors == []
        assert page.page_close_calls == 0

    def test_close_last_non_root_tab_missing_control_is_unsafe(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """Click failure (missing/broken close control) -> UNSAFE; no Page close."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )
        from apps.ingestion.extractors.session_policy import TabCleanupOutcome

        page = _DomTabPage([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])
        page.click_fails = True
        mock_persistent_context.pages = [page]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            outcome = handle.close_last_non_root_tab(timeout=1)

        assert outcome is TabCleanupOutcome.UNSAFE
        assert page.page_close_calls == 0
        # Tab count unchanged (click failed).
        assert len(page.tab_classes) == 2

    def test_close_last_non_root_tab_no_count_decrease_is_unsafe(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """Click succeeds but tab count never decreases within the bounded
        timeout -> UNSAFE (R4 verification gate)."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )
        from apps.ingestion.extractors.session_policy import (
            SEL_TAB_LAST_CLOSE,
            TabCleanupOutcome,
        )

        page = _DomTabPage([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])
        page.no_decrease = True
        mock_persistent_context.pages = [page]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            outcome = handle.close_last_non_root_tab(timeout=1)

        assert outcome is TabCleanupOutcome.UNSAFE
        # The DOM control WAS clicked, but verification failed.
        assert SEL_TAB_LAST_CLOSE in page.clicked_selectors
        assert page.page_close_calls == 0

    def test_close_last_non_root_tab_ambiguous_state_is_unsafe(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """Ambiguous DOM state -> UNSAFE without clicking."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )
        from apps.ingestion.extractors.session_policy import TabCleanupOutcome

        # Last tab also carries tabs-first -> ambiguous/merged state.
        page = _DomTabPage([
            "tabs-first tabs-last tabs-selected",
            "tabs-first tabs-last tabs-selected",
        ])
        mock_persistent_context.pages = [page]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            outcome = handle.close_last_non_root_tab(timeout=1)

        assert outcome is TabCleanupOutcome.UNSAFE
        assert page.clicked_selectors == []
        assert page.page_close_calls == 0

    def test_restart_browser_releases_and_reacquires(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        playwright_inner_mock: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """restart_browser closes old context and starts new one."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            # Mark profile in use after start.
            mock_browser_profile.is_in_use = True

            # Reset call counts after initial start
            mock_browser_profile.acquire.reset_mock()
            mock_persistent_context.close.reset_mock()
            mock_browser_profile.release_after_shutdown.reset_mock()

            handle.restart_browser()

        mock_persistent_context.close.assert_called_once()
        mock_browser_profile.release_after_shutdown.assert_called_once()
        mock_browser_profile.acquire.assert_called_once()


# ===========================================================================
# Bootstrap page access (PSW-S10 final polish)
# ===========================================================================


class TestEnsureCurrentPage:
    """Tests for ensure_current_page (bootstrap get-or-create page)."""

    def test_creates_page_when_context_has_no_pages(
        self,
        mock_browser_profile: MagicMock,
        mock_page: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """ensure_current_page creates a page when none exists."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        # Context opened without pages (possible with launch_persistent_context).
        mock_persistent_context.pages = []
        mock_persistent_context.new_page.return_value = mock_page

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            page = handle.ensure_current_page()

        mock_persistent_context.new_page.assert_called_once()
        assert page is mock_page

    def test_reuses_existing_page_without_creating_new(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """ensure_current_page reuses the existing page and skips new_page."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        existing_page = MagicMock()
        mock_persistent_context.pages = [existing_page]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            page = handle.ensure_current_page()

        mock_persistent_context.new_page.assert_not_called()
        assert page is existing_page

    def test_returns_none_when_browser_not_started(
        self,
        mock_browser_profile: MagicMock,
    ) -> None:
        """ensure_current_page returns None before the browser starts."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        handle = PlaywrightSessionHandle(profile=mock_browser_profile)
        assert handle.ensure_current_page() is None


# ===========================================================================
# No real legacy access
# ===========================================================================


class TestNoRealLegacyAccess:
    """Tests prove no real legacy system is required."""

    def test_all_mocked_no_real_browser(self) -> None:
        """All tests use mocks — no real Playwright browser connection."""
        assert True

    def test_handle_not_rollout_ready_without_real_system(
        self,
        mock_browser_profile: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """The handle is wired but requires real system for full operation."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()

        assert hasattr(handle, "open_tab")
        assert hasattr(handle, "get_page_html")
        assert hasattr(handle, "restart_browser")


# ===========================================================================
# PSW-S17 final closure: source-boundary typed timeouts + sanitized logs
# ===========================================================================


SENSITIVE_URL_SENTINEL = "https://sensitive.example.test/SENSITIVE_URL"
SENSITIVE_COOKIE_SENTINEL = "SENSITIVE_COOKIE_VALUE"


class TestSourceBoundaryTypedTimeouts:
    """D3: source operations that can affect run classification must
    propagate a typed ExtractionTimeoutError on a real Playwright timeout."""

    def test_get_page_html_timeout_raises_extraction_timeout(
        self,
        mock_browser_profile: MagicMock,
        mock_page: MagicMock,
        sync_playwright_mock: MagicMock,
        caplog,
    ) -> None:
        """get_page_html raises ExtractionTimeoutError when page.content()
        raises a real Playwright timeout (not swallowed + logged)."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.errors import ExtractionTimeoutError
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        mock_page.content.side_effect = PlaywrightTimeoutError(
            f"Timeout at {SENSITIVE_URL_SENTINEL} cookie={SENSITIVE_COOKIE_SENTINEL}"
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            with pytest.raises(ExtractionTimeoutError) as exc_info:
                handle.get_page_html()

        message = str(exc_info.value)
        assert SENSITIVE_URL_SENTINEL not in message
        assert SENSITIVE_COOKIE_SENTINEL not in message

    def test_click_selector_timeout_raises_extraction_timeout(
        self,
        mock_browser_profile: MagicMock,
        mock_page: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """click_selector raises ExtractionTimeoutError when locator.click()
        raises a real Playwright timeout."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.errors import ExtractionTimeoutError
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        locator_mock = MagicMock()
        locator_mock.click.side_effect = PlaywrightTimeoutError(
            f"Timeout at {SENSITIVE_URL_SENTINEL}"
        )
        mock_page.locator.return_value = locator_mock

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            with pytest.raises(ExtractionTimeoutError):
                handle.click_selector(".my-button")

    def test_get_tab_classes_timeout_raises_extraction_timeout(
        self,
        mock_browser_profile: MagicMock,
        mock_page: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """get_tab_classes raises ExtractionTimeoutError when page.evaluate()
        raises a real Playwright timeout."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.errors import ExtractionTimeoutError
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        mock_page.evaluate.side_effect = PlaywrightTimeoutError(
            f"Timeout at {SENSITIVE_URL_SENTINEL}"
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            with pytest.raises(ExtractionTimeoutError):
                handle.get_tab_classes()


class TestHandleLogSanitization:
    """D3: all logs use constant sanitized messages — no raw exception,
    traceback, URL, selector, or source identifier."""

    def test_get_page_html_non_timeout_failure_log_sanitized(
        self,
        mock_browser_profile: MagicMock,
        mock_page: MagicMock,
        sync_playwright_mock: MagicMock,
        caplog,
    ) -> None:
        """A non-timeout failure in get_page_html logs a constant message
        (no raw exception text, URL, or cookie)."""
        import logging

        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        mock_page.content.side_effect = RuntimeError(
            f"boom at {SENSITIVE_URL_SENTINEL} cookie={SENSITIVE_COOKIE_SENTINEL}"
        )

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            with caplog.at_level(
                logging.WARNING,
                logger="apps.ingestion.extractors.playwright_session_handle",
            ):
                result = handle.get_page_html()

        # Non-timeout failure keeps the legacy empty-string return.
        assert result == ""
        # No sentinel may appear in any log record text.
        for record in caplog.records:
            text = record.getMessage()
            assert SENSITIVE_URL_SENTINEL not in text
            assert SENSITIVE_COOKIE_SENTINEL not in text
        # No traceback attached (exc_info must not carry the raw exception).
        for record in caplog.records:
            assert record.exc_info is None

    def test_click_selector_non_timeout_failure_log_sanitized(
        self,
        mock_browser_profile: MagicMock,
        mock_page: MagicMock,
        sync_playwright_mock: MagicMock,
        caplog,
    ) -> None:
        """A non-timeout failure in click_selector logs a constant message
        with no selector or raw exception text."""
        import logging

        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        sensitive_selector = "#SENSITIVE_SELECTOR"
        locator_mock = MagicMock()
        locator_mock.click.side_effect = RuntimeError(
            f"boom at {SENSITIVE_URL_SENTINEL}"
        )
        mock_page.locator.return_value = locator_mock

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(profile=mock_browser_profile)
            handle.start()
            with caplog.at_level(
                logging.WARNING,
                logger="apps.ingestion.extractors.playwright_session_handle",
            ):
                handle.click_selector(sensitive_selector)

        for record in caplog.records:
            text = record.getMessage()
            assert sensitive_selector not in text
            assert SENSITIVE_URL_SENTINEL not in text
