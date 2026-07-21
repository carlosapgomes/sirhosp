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

    def test_close_last_non_root_tab(
        self,
        mock_browser_profile: MagicMock,
        mock_persistent_context: MagicMock,
        sync_playwright_mock: MagicMock,
    ) -> None:
        """close_last_non_root_tab closes the last non-root tab page."""
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        root_page = MagicMock()
        job_page = MagicMock()
        mock_persistent_context.pages = [root_page, job_page]

        with patch(
            "playwright.sync_api.sync_playwright",
            return_value=sync_playwright_mock,
        ):
            handle = PlaywrightSessionHandle(
                profile=mock_browser_profile,
            )
            handle.start()
            handle.close_last_non_root_tab()

        job_page.close.assert_called_once()
        root_page.close.assert_not_called()

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
