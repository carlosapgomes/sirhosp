"""Unit tests for session DOM policy primitives (PSW-S1).

Tests cover countdown parsing, popup detection, and tab cleanup
decisions using synthetic HTML only — no Playwright dependency.
"""

from __future__ import annotations

from apps.ingestion.extractors.session_policy import (
    TabCleanupAction,
    decide_tab_cleanup,
    get_renewal_button_selector,
    is_renewal_popup_visible,
    parse_session_countdown,
)

# ---------------------------------------------------------------------------
# Session countdown parsing
# ---------------------------------------------------------------------------

VALID_COUNTER_HTML = r"""<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>"""


class TestParseSessionCountdown:
    def test_valid_counter_returns_seconds(self) -> None:
        """Standard 00:29:01 → 1741 seconds."""
        result = parse_session_countdown(VALID_COUNTER_HTML)
        assert result == 1741

    def test_hours_nonzero(self) -> None:
        """01:15:30 → 4530 seconds."""
        html = r"""<div id="tempoSessao" class="tempo-sessao">
          <span>01</span>:<span>15</span>:<span>30</span>
        </div>"""
        assert parse_session_countdown(html) == 4530

    def test_near_expiry(self) -> None:
        """00:00:05 → 5 seconds."""
        html = r"""<div id="tempoSessao">
          <span>00</span>:<span>00</span>:<span>05</span>
        </div>"""
        assert parse_session_countdown(html) == 5

    def test_missing_counter_returns_none(self) -> None:
        """No #tempoSessao element → None."""
        html = "<html><body><p>No counter here</p></body></html>"
        assert parse_session_countdown(html) is None

    def test_malformed_missing_spans_returns_none(self) -> None:
        """#tempoSessao exists but spans are missing → None."""
        html = r"""<div id="tempoSessao">Tempo de Sessão: 00:29:01</div>"""
        assert parse_session_countdown(html) is None

    def test_malformed_non_numeric_returns_none(self) -> None:
        """Spans contain non-numeric values → None."""
        html = r"""<div id="tempoSessao">
          <span>ab</span>:<span>cd</span>:<span>ef</span>
        </div>"""
        assert parse_session_countdown(html) is None

    def test_empty_html_returns_none(self) -> None:
        """Completely empty string → None."""
        assert parse_session_countdown("") is None

    def test_partial_spans_returns_none(self) -> None:
        """Only two spans instead of three → None."""
        html = r"""<div id="tempoSessao">
          <span>00</span>:<span>29</span>
        </div>"""
        assert parse_session_countdown(html) is None


# ---------------------------------------------------------------------------
# Renewal popup detection
# ---------------------------------------------------------------------------


class TestIsRenewalPopupVisible:
    def test_visible_popup_returns_true(self) -> None:
        """Popup with aria-hidden=false and display:block → True."""
        html = r"""<div id="casca_renovasession" aria-hidden="false"
                    style="display: block;">
          <button class="ui-confirmdialog-yes" type="submit">
            <span class="ui-button-text ui-c">Renovar</span>
          </button>
        </div>"""
        assert is_renewal_popup_visible(html) is True

    def test_hidden_popup_returns_false(self) -> None:
        """Popup with aria-hidden=true → False."""
        html = r"""<div id="casca_renovasession" aria-hidden="true"
                    style="display: none;">
          <button class="ui-confirmdialog-yes" type="submit">Renovar</button>
        </div>"""
        assert is_renewal_popup_visible(html) is False

    def test_no_popup_returns_false(self) -> None:
        """No casca_renovasession element at all → False."""
        html = "<html><body><p>No popup here</p></body></html>"
        assert is_renewal_popup_visible(html) is False

    def test_popup_display_none_aria_false_returns_false(self) -> None:
        """Popup with aria-hidden=false but display:none → False."""
        html = r"""<div id="casca_renovasession" aria-hidden="false"
                    style="display: none;">
          <button class="ui-confirmdialog-yes">Renovar</button>
        </div>"""
        assert is_renewal_popup_visible(html) is False

    def test_popup_visible_no_aria_attribute_returns_false(self) -> None:
        """Popup with display:block but no aria-hidden → False."""
        html = r"""<div id="casca_renovasession" style="display: block;">
          <button class="ui-confirmdialog-yes">Renovar</button>
        </div>"""
        assert is_renewal_popup_visible(html) is False

    def test_empty_html_returns_false(self) -> None:
        """Completely empty string → False."""
        assert is_renewal_popup_visible("") is False


class TestGetRenewalButtonSelector:
    def test_returns_expected_selector(self) -> None:
        """The selector targets the semantic renewal button."""
        selector = get_renewal_button_selector()
        assert selector == ".ui-confirmdialog-yes"


# ---------------------------------------------------------------------------
# Tab cleanup decisions
# ---------------------------------------------------------------------------


class TestDecideTabCleanup:
    def test_root_only_tab_preserves_root(self) -> None:
        """Single root tab → PRESERVE_ROOT."""
        tab_classes = ["tabs-first tabs-last tabs-selected"]
        assert decide_tab_cleanup(tab_classes) == TabCleanupAction.PRESERVE_ROOT

    def test_root_only_accepts_reordered_tokens(self) -> None:
        """B2: same mandatory tokens in a different order → PRESERVE_ROOT."""
        tab_classes = ["tabs-last tabs-first tabs-selected"]
        assert decide_tab_cleanup(tab_classes) == TabCleanupAction.PRESERVE_ROOT

    def test_root_only_accepts_extra_primefaces_classes(self) -> None:
        """B3: mandatory tokens plus extra PrimeFaces classes → PRESERVE_ROOT."""
        tab_classes = [
            "ui-tab ui-state-active tabs-first tabs-last tabs-selected"
        ]
        assert decide_tab_cleanup(tab_classes) == TabCleanupAction.PRESERVE_ROOT

    def test_root_only_missing_a_token_requires_recovery(self) -> None:
        """B4: missing one mandatory token → RECOVERY_REQUIRED."""
        tab_classes = ["tabs-first tabs-last"]
        assert (
            decide_tab_cleanup(tab_classes)
            == TabCleanupAction.RECOVERY_REQUIRED
        )

    def test_two_tabs_closes_last_non_root(self) -> None:
        """Two tabs, last is not root → CLOSE_LAST_NON_ROOT."""
        tab_classes = [
            "tabs-first tabs-selected",
            "tabs-last tabs-selected",
        ]
        assert (
            decide_tab_cleanup(tab_classes)
            == TabCleanupAction.CLOSE_LAST_NON_ROOT
        )

    def test_three_tabs_closes_last_non_root(self) -> None:
        """Three tabs, last is not first → CLOSE_LAST_NON_ROOT."""
        tab_classes = [
            "tabs-first tabs-selected",
            "tabs-selected",
            "tabs-last tabs-selected",
        ]
        assert (
            decide_tab_cleanup(tab_classes)
            == TabCleanupAction.CLOSE_LAST_NON_ROOT
        )

    def test_multiple_tabs_last_is_also_first_requires_recovery(self) -> None:
        """Two or more tabs where the last also carries 'tabs-first'
        (ambiguous/merged state) → RECOVERY_REQUIRED, never close."""
        tab_classes = [
            "tabs-first tabs-last tabs-selected",
            "tabs-first tabs-last tabs-selected",
        ]
        assert (
            decide_tab_cleanup(tab_classes)
            == TabCleanupAction.RECOVERY_REQUIRED
        )

    def test_empty_tab_list_requires_recovery(self) -> None:
        """No tabs at all → RECOVERY_REQUIRED."""
        assert (
            decide_tab_cleanup([])
            == TabCleanupAction.RECOVERY_REQUIRED
        )

    def test_single_tab_without_root_classes_requires_recovery(
        self,
    ) -> None:
        """One tab but missing root classes → RECOVERY_REQUIRED."""
        tab_classes = ["tabs-selected"]
        assert (
            decide_tab_cleanup(tab_classes)
            == TabCleanupAction.RECOVERY_REQUIRED
        )

    def test_last_tab_missing_tabs_last_requires_recovery(self) -> None:
        """Last tab does not have 'tabs-last' → RECOVERY_REQUIRED."""
        tab_classes = [
            "tabs-first tabs-selected",
            "tabs-selected",
        ]
        assert (
            decide_tab_cleanup(tab_classes)
            == TabCleanupAction.RECOVERY_REQUIRED
        )

    def test_tab_close_is_not_renewal_evidence(self) -> None:
        """Semantic test: closing a tab must never be classified
        as a renewal action. No TabCleanupAction value implies renewal."""
        all_actions = set(TabCleanupAction)
        renewal_implying = {a for a in all_actions if "renew" in a.name.lower()}
        assert len(renewal_implying) == 0, (
            f"No action should imply renewal, got: {renewal_implying}"
        )
