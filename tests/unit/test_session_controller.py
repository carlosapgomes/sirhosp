"""Unit tests for persistent session controller (PSW-S2).

Tests cover session lifecycle management using fake Playwright-like
browser/session objects — no real browser required.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from apps.ingestion.extractors.session_controller import (
    PersistentSessionController,
    SessionControllerConfig,
)
from apps.ingestion.extractors.session_policy import (
    SEL_RENEWAL_BUTTON,
)

# ---------------------------------------------------------------------------
# Fake browser/session handle for unit tests
# ---------------------------------------------------------------------------


class FakeSessionHandle:
    """Fake Playwright-like session handle for unit testing.

    Simulates page HTML, tab state, connection status, and records
    all interactions for assertion.
    """

    def __init__(self) -> None:
        self._html: str = ""
        self._tab_classes: list[str] = []
        self._connected: bool = True
        self._clicked_selectors: list[str] = []
        self._opened_urls: list[str] = []
        self._closed_tab_calls: int = 0
        self._restart_calls: int = 0
        self._on_open_tab: Callable[[], None] | None = None
        self._open_tab_fail: bool = False

    # --- Fake state mutators (test helpers) ---

    def set_html(self, html: str) -> None:
        self._html = html

    def set_tab_classes(self, classes: list[str]) -> None:
        self._tab_classes = list(classes)

    def set_connected(self, connected: bool) -> None:
        self._connected = connected

    def set_on_open_tab(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked when ``open_tab`` is called.

        Useful for simulating page state changes (e.g. counter reset)
        after tab navigation.
        """
        self._on_open_tab = callback

    def fail_next_open_tab(self) -> None:
        """Make the next ``open_tab`` call return False."""
        self._open_tab_fail = True

    # --- Interface implementation ---

    def get_page_html(self) -> str:
        return self._html

    def is_connected(self) -> bool:
        return self._connected

    def click_selector(self, selector: str) -> None:
        self._clicked_selectors.append(selector)

    def open_tab(self, url: str) -> bool:
        self._opened_urls.append(url)
        if self._on_open_tab is not None:
            self._on_open_tab()
        return not self._open_tab_fail

    def get_tab_classes(self) -> list[str]:
        return list(self._tab_classes)

    def close_last_non_root_tab(self) -> None:
        self._closed_tab_calls += 1

    def restart_browser(self) -> None:
        self._restart_calls += 1
        self._connected = True

    # --- Test query helpers ---

    @property
    def clicked_selectors(self) -> list[str]:
        return list(self._clicked_selectors)

    @property
    def opened_urls(self) -> list[str]:
        return list(self._opened_urls)

    @property
    def closed_tab_calls(self) -> int:
        return self._closed_tab_calls

    @property
    def restart_calls(self) -> int:
        return self._restart_calls


# ---------------------------------------------------------------------------
# Synthetic HTML fixtures
# ---------------------------------------------------------------------------

VALID_COUNTER_HTML = r"""<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>"""

LOW_COUNTER_HTML = r"""<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>05</span>:<span>00</span>
</div>"""

VISIBLE_POPUP_HTML = r"""<div id="casca_renovasession" aria-hidden="false"
    style="display: block;">
  <button class="ui-confirmdialog-yes" type="submit">
    <span class="ui-button-text ui-c">Renovar</span>
  </button>
</div>"""

RESET_COUNTER_HTML = r"""<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>59</span>
</div>"""


# ===========================================================================
# ensure_ready
# ===========================================================================


class TestEnsureReady:
    """Tests for ``ensure_ready()`` — session health check."""

    def test_connected_with_valid_counter_returns_true(self) -> None:
        """Session connected and counter valid → True."""
        session = FakeSessionHandle()
        session.set_html(VALID_COUNTER_HTML)
        controller = PersistentSessionController(session)
        assert controller.ensure_ready() is True

    def test_disconnected_returns_false(self) -> None:
        """Browser disconnected → False."""
        session = FakeSessionHandle()
        session.set_connected(False)
        controller = PersistentSessionController(session)
        assert controller.ensure_ready() is False

    def test_visible_popup_clicks_renewal_button(self) -> None:
        """Popup visible → clicks renewal button (defensive)."""
        session = FakeSessionHandle()
        session.set_html(VISIBLE_POPUP_HTML)
        controller = PersistentSessionController(session)

        # Popup is visible, counter missing → should click and return False
        assert controller.ensure_ready() is False
        assert SEL_RENEWAL_BUTTON in session.clicked_selectors

    def test_popup_then_valid_counter_returns_true(self) -> None:
        """Popup visible → click → counter present → True."""
        session = FakeSessionHandle()

        # Simulate that clicking the renewal button clears the popup
        # and reveals a valid counter.
        def _on_click(selector: str) -> None:
            session.set_html(VALID_COUNTER_HTML)

        # Override click_selector
        original_click = session.click_selector

        def click_with_reveal(selector: str) -> None:
            original_click(selector)
            session.set_html(VALID_COUNTER_HTML)

        session.click_selector = click_with_reveal  # type: ignore[assignment]

        controller = PersistentSessionController(session)
        session.set_html(VISIBLE_POPUP_HTML)
        assert controller.ensure_ready() is True

    def test_missing_counter_without_popup_returns_false(self) -> None:
        """No counter and no popup → False."""
        session = FakeSessionHandle()
        session.set_html("<html><body><p>No session info</p></body></html>")
        controller = PersistentSessionController(session)
        assert controller.ensure_ready() is False


# ===========================================================================
# renew_if_needed
# ===========================================================================


class TestRenewIfNeeded:
    """Tests for ``renew_if_needed()`` — proactive session renewal."""

    def test_counter_above_threshold_no_action(self) -> None:
        """Counter above threshold → no tabs opened, returns True."""
        session = FakeSessionHandle()
        session.set_html(VALID_COUNTER_HTML)  # 00:29:01 = 1741s
        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                renewal_threshold_seconds=600,  # 10 min
                safe_renewal_tab_url="https://example.com/safe",
            ),
        )
        assert controller.renew_if_needed() is True
        assert len(session.opened_urls) == 0

    def test_counter_below_threshold_opens_safe_tab(self) -> None:
        """Counter below threshold → opens safe tab → True."""
        session = FakeSessionHandle()
        session.set_html(LOW_COUNTER_HTML)  # 00:05:00 = 300s

        # Simulate counter reset after tab open.
        session.set_on_open_tab(lambda: session.set_html(RESET_COUNTER_HTML))

        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                renewal_threshold_seconds=600,
                safe_renewal_tab_url="https://example.com/safe",
            ),
        )
        assert controller.renew_if_needed() is True
        assert "https://example.com/safe" in session.opened_urls

    def test_safe_tab_open_fails_returns_false(self) -> None:
        """Safe tab open fails → returns False, increments failures."""
        session = FakeSessionHandle()
        session.set_html(LOW_COUNTER_HTML)
        session.fail_next_open_tab()

        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                renewal_threshold_seconds=600,
                safe_renewal_tab_url="https://example.com/safe",
                max_consecutive_failures=3,
            ),
        )
        assert controller.renew_if_needed() is False
        assert controller.consecutive_failures == 1

    def test_renewal_handles_popup_first_then_opens_tab(self) -> None:
        """Popup visible → clicks renewal → opens safe tab → True."""
        session = FakeSessionHandle()
        session.set_html(VISIBLE_POPUP_HTML)

        # After click and tab open, simulate counter reset.
        call_count = 0

        def _on_open_tab() -> None:
            nonlocal call_count
            call_count += 1
            session.set_html(RESET_COUNTER_HTML)

        session.set_on_open_tab(_on_open_tab)

        # Override click_selector to also clear popup
        original_click = session.click_selector

        def click_and_clear_popup(selector: str) -> None:
            original_click(selector)
            session.set_html(VISIBLE_POPUP_HTML)  # keep showing for now

        session.click_selector = click_and_clear_popup  # type: ignore[assignment]

        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                renewal_threshold_seconds=600,
                safe_renewal_tab_url="https://example.com/safe",
            ),
        )

        assert controller.renew_if_needed() is True
        assert SEL_RENEWAL_BUTTON in session.clicked_selectors
        assert "https://example.com/safe" in session.opened_urls

    def test_malformed_counter_opens_safe_tab_defensively(self) -> None:
        """Malformed counter → opens safe tab defensively → True."""
        session = FakeSessionHandle()
        session.set_html("<div id='tempoSessao'>Corrupted</div>")

        # Simulate that safe tab restores the counter.
        session.set_on_open_tab(lambda: session.set_html(RESET_COUNTER_HTML))

        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                renewal_threshold_seconds=600,
                safe_renewal_tab_url="https://example.com/safe",
            ),
        )
        assert controller.renew_if_needed() is True
        assert "https://example.com/safe" in session.opened_urls


# ===========================================================================
# open_safe_renewal_tab
# ===========================================================================


class TestOpenSafeRenewalTab:
    """Tests for ``open_safe_renewal_tab()`` — renewal tab action."""

    def test_opens_configured_url(self) -> None:
        """Opens the configured safe URL."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                safe_renewal_tab_url="https://example.com/safe-renewal",
            ),
        )
        controller.open_safe_renewal_tab()
        assert "https://example.com/safe-renewal" in session.opened_urls

    def test_counter_resets_after_tab_open_returns_true(self) -> None:
        """Tab opens and counter resets (higher value) → returns True."""
        session = FakeSessionHandle()
        session.set_html(LOW_COUNTER_HTML)  # 300s

        # Simulate counter reset after tab navigation.
        session.set_on_open_tab(lambda: session.set_html(RESET_COUNTER_HTML))

        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                safe_renewal_tab_url="https://example.com/safe",
            ),
        )
        result = controller.open_safe_renewal_tab()
        assert result is True

    def test_counter_not_reset_returns_false(self) -> None:
        """Tab opens but counter does not increase → False."""
        session = FakeSessionHandle()
        session.set_html(LOW_COUNTER_HTML)  # 300s

        # Counter stays at 300s after tab open.
        session.set_on_open_tab(lambda: None)

        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                safe_renewal_tab_url="https://example.com/safe",
            ),
        )
        result = controller.open_safe_renewal_tab()
        assert result is False

    def test_missing_counter_after_tab_returns_false(self) -> None:
        """Tab opens but counter disappears → False."""
        session = FakeSessionHandle()
        session.set_html(VALID_COUNTER_HTML)

        # Counter disappears after tab open.
        session.set_on_open_tab(
            lambda: session.set_html("<html><body>No counter</body></html>")
        )

        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                safe_renewal_tab_url="https://example.com/safe",
            ),
        )
        result = controller.open_safe_renewal_tab()
        assert result is False

    def test_no_safe_url_returns_false(self) -> None:
        """No safe URL configured → returns False."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(safe_renewal_tab_url=""),
        )
        result = controller.open_safe_renewal_tab()
        assert result is False
        assert controller.consecutive_failures == 1

    def test_tab_open_failure_returns_false(self) -> None:
        """Tab open fails → returns False."""
        session = FakeSessionHandle()
        session.fail_next_open_tab()
        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                safe_renewal_tab_url="https://example.com/safe",
            ),
        )
        result = controller.open_safe_renewal_tab()
        assert result is False
        assert controller.consecutive_failures == 1


# ===========================================================================
# close_job_tab_if_present
# ===========================================================================


class TestCloseJobTabIfPresent:
    """Tests for ``close_job_tab_if_present()`` — tab cleanup."""

    def test_single_root_tab_does_nothing(self) -> None:
        """Only root tab → no tab close."""
        session = FakeSessionHandle()
        session.set_tab_classes(["tabs-first tabs-last tabs-selected"])
        controller = PersistentSessionController(session)
        controller.close_job_tab_if_present()
        assert session.closed_tab_calls == 0

    def test_two_tabs_closes_last_non_root(self) -> None:
        """Two tabs → closes last non-root tab."""
        session = FakeSessionHandle()
        session.set_tab_classes([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])
        controller = PersistentSessionController(session)
        controller.close_job_tab_if_present()
        assert session.closed_tab_calls == 1

    def test_three_tabs_closes_last_non_root(self) -> None:
        """Three tabs → closes last non-root tab."""
        session = FakeSessionHandle()
        session.set_tab_classes([
            "tabs-first tabs-selected",
            "tabs-selected",
            "tabs-last tabs-selected",
        ])
        controller = PersistentSessionController(session)
        controller.close_job_tab_if_present()
        assert session.closed_tab_calls == 1

    def test_ambiguous_state_increments_failures(self) -> None:
        """Ambiguous tab state → no close, increments failures."""
        session = FakeSessionHandle()
        session.set_tab_classes([])
        controller = PersistentSessionController(session)
        controller.close_job_tab_if_present()
        assert session.closed_tab_calls == 0
        assert controller.consecutive_failures == 1

    def test_close_is_not_renewal_evidence(self) -> None:
        """Tab close does not reset failure counter or session tracking."""
        session = FakeSessionHandle()
        session.set_tab_classes([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])
        controller = PersistentSessionController(session)
        controller.consecutive_failures = 2
        controller.close_job_tab_if_present()
        # Close is cleanup — does not reset failures or session expiry
        assert controller.consecutive_failures == 2


# ===========================================================================
# mark_job_processed
# ===========================================================================


class TestMarkJobProcessed:
    """Tests for ``mark_job_processed()`` — job counter."""

    def test_increments_job_count(self) -> None:
        """Calling mark_job_processed increments jobs_processed."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(session)
        assert controller.jobs_processed == 0
        controller.mark_job_processed()
        assert controller.jobs_processed == 1
        controller.mark_job_processed()
        assert controller.jobs_processed == 2

    def test_job_processed_resets_failure_counter(self) -> None:
        """Successful job resets consecutive_failures."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(session)
        controller.consecutive_failures = 2
        controller.mark_job_processed()
        assert controller.consecutive_failures == 0


# ===========================================================================
# restart_required
# ===========================================================================


class TestRestartRequired:
    """Tests for ``restart_required()`` — health threshold checks."""

    def test_under_thresholds_returns_false(self) -> None:
        """All counters under thresholds → False."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                max_jobs_per_session=50,
                max_lifetime_seconds=3600,
                max_consecutive_failures=3,
            ),
        )
        assert controller.restart_required() is False

    def test_max_jobs_reached_returns_true(self) -> None:
        """jobs_processed >= max_jobs_per_session → True."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(max_jobs_per_session=5),
        )
        controller.jobs_processed = 5
        assert controller.restart_required() is True

    def test_max_failures_reached_returns_true(self) -> None:
        """consecutive_failures >= max_consecutive_failures → True."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(max_consecutive_failures=3),
        )
        controller.consecutive_failures = 3
        assert controller.restart_required() is True

    def test_max_lifetime_exceeded_returns_true(self) -> None:
        """Session lifetime exceeds max_lifetime_seconds → True."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(max_lifetime_seconds=10),
        )
        # Simulate session created long ago.
        controller._session_start_time = time.monotonic() - 20
        assert controller.restart_required() is True

    def test_disconnected_returns_true(self) -> None:
        """Browser disconnected → True."""
        session = FakeSessionHandle()
        session.set_connected(False)
        controller = PersistentSessionController(session)
        assert controller.restart_required() is True

    def test_reset_after_restart(self) -> None:
        """After restart, counters reset → False."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                max_jobs_per_session=5,
                max_consecutive_failures=3,
            ),
        )
        controller.jobs_processed = 5
        controller.consecutive_failures = 3
        assert controller.restart_required() is True
        controller.reset_after_restart()
        assert controller.jobs_processed == 0
        assert controller.consecutive_failures == 0
        assert controller.restart_required() is False


# ===========================================================================
# Integration-style: full lifecycle with fakes
# ===========================================================================


class TestSessionLifecycleWithFakes:
    """End-to-end lifecycle with fakes — multiple methods in sequence."""

    def test_basic_job_cycle(self) -> None:
        """Full lifecycle: ensure_ready → process → cleanup → check restart."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                max_jobs_per_session=50,
                max_lifetime_seconds=3600,
                max_consecutive_failures=3,
            ),
        )

        # Ensure ready
        session.set_html(VALID_COUNTER_HTML)
        assert controller.ensure_ready() is True

        # Process a job
        controller.mark_job_processed()
        assert controller.jobs_processed == 1

        # Cleanup tab
        session.set_tab_classes([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])
        controller.close_job_tab_if_present()
        assert session.closed_tab_calls == 1

        # After one job, should not need restart
        assert controller.restart_required() is False

    def test_renewal_then_job_cycle(self) -> None:
        """Renewal needed → renew → process → cleanup."""
        session = FakeSessionHandle()
        session.set_html(LOW_COUNTER_HTML)

        # Simulate counter reset on safe tab open.
        session.set_on_open_tab(lambda: session.set_html(RESET_COUNTER_HTML))

        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(
                renewal_threshold_seconds=600,
                safe_renewal_tab_url="https://example.com/safe",
                max_jobs_per_session=50,
            ),
        )

        # Low counter triggers proactive renewal
        assert controller.renew_if_needed() is True
        assert "https://example.com/safe" in session.opened_urls

        # After renewal, mark job
        controller.mark_job_processed()
        assert controller.jobs_processed == 1

    def test_failures_accumulate_across_operations(self) -> None:
        """Multiple failure conditions accumulate and trigger restart."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(
            session,
            config=SessionControllerConfig(max_consecutive_failures=2),
        )

        # Tab cleanup failures
        session.set_tab_classes([])
        controller.close_job_tab_if_present()
        assert controller.consecutive_failures == 1

        # Another failure (missing counter)
        session.set_html("<html><body>No session info</body></html>")
        controller.ensure_ready()
        assert controller.consecutive_failures == 2

        # Restart required
        assert controller.restart_required() is True

    def test_renewal_popup_tab_close_does_not_reset_failures(self) -> None:
        """Tab close is cleanup only — does not reset failure counters."""
        session = FakeSessionHandle()
        controller = PersistentSessionController(session)
        controller.consecutive_failures = 2

        session.set_tab_classes([
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ])
        controller.close_job_tab_if_present()

        # Tab close is NOT renewal — failures remain
        assert controller.consecutive_failures == 2


# ===========================================================================
# Default config tests
# ===========================================================================


class TestDefaultConfig:
    """Tests for default configuration values."""

    def test_default_values_are_conservative(self) -> None:
        """Default config provides conservative thresholds."""
        config = SessionControllerConfig()
        assert config.max_jobs_per_session == 50
        assert config.max_lifetime_seconds == 3600
        assert config.max_consecutive_failures == 3
        assert config.renewal_threshold_seconds == 600
        assert config.safe_renewal_tab_url == ""
