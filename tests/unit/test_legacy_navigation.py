"""Tests for legacy UI navigation helper (PSW-S12).

Prove that the persistent worker's ``--real-handle`` path can navigate the
real legacy UI using action-based Playwright calls modeled after ``path2.py``,
without requiring admissions or evolutions URL templates.

All tests use mocked/fake Playwright page objects — no real legacy access.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from apps.ingestion.extractors.persistent_extraction_adapter import (
    _ADMISSION_DATA_DIV_ID,
)

# ===========================================================================
# Representative synthetic legacy DOM for the internações page
# ===========================================================================

ADMISSIONS_TABLE_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="mainContent">
  <iframe name="frame_pol" id="frame_pol" src="/internacoes/consulta.xhtml">
    <html><body>
    <table id="tabelaInternacoes:resultList">
      <tbody id="tabelaInternacoes:resultList_data">
        <tr data-ri="0" data-rk="ADM-RK-001">
          <td>15/01/2024</td>
          <td>20/01/2024</td>
          <td>Enfermaria A</td>
          <td>Leito 101</td>
          <td><a title="Detalhes da Internação">Detalhes</a></td>
        </tr>
        <tr data-ri="1" data-rk="ADM-RK-002">
          <td>01/03/2024</td>
          <td></td>
          <td>UTI</td>
          <td>Leito 005</td>
          <td><a title="Detalhes da Internação">Detalhes</a></td>
        </tr>
      </tbody>
    </table>
    </body></html>
  </iframe>
</div>
</body>
</html>"""

EMPTY_ADMISSIONS_TABLE_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="mainContent">
  <iframe name="frame_pol" id="frame_pol" src="/internacoes/consulta.xhtml">
    <html><body>
    <table id="tabelaInternacoes:resultList">
      <tbody id="tabelaInternacoes:resultList_data">
      </tbody>
    </table>
    </body></html>
  </iframe>
</div>
</body>
</html>"""

NO_TABLE_HTML = """<html>
<body>
<div id="tempoSessao" class="tempo-sessao">
  Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
</div>
<div id="mainContent">
  <p>Nenhuma internação encontrada para este prontuário.</p>
</div>
</body>
</html>"""


# ===========================================================================
# Fake Playwright Page for navigation tests
# ===========================================================================


class FakeNavigationPage:
    """Minimal fake Playwright Page that tracks action calls.

    Models the interactions that ``legacy_navigation`` helpers perform:
    - ``locator()`` -> returns a fake locator
    - ``get_by_role()`` -> returns a fake locator
    - ``get_by_text()`` -> returns a fake locator
    - ``frame()`` -> returns a fake frame
    - ``content()`` -> returns HTML
    """

    def __init__(self, html: str = "") -> None:
        self._html = html
        self._locator_calls: list[str] = []
        self._role_calls: list[tuple[str, str | None]] = []
        self._text_calls: list[str] = []
        self._frame_name_calls: list[str] = []
        self._frame: FakeNavigationFrame | None = None
        self._visible_selectors: set[str] = set()
        self._click_callbacks: dict[str, list[str]] = {}
        self._filled_values: dict[str, str] = {}
        self._wait_timeouts: list[int] = []
        self._click_timeouts: list[int] = []
        self._fill_timeouts: list[int] = []
        self._action_timeouts: list[int] = []
        self._wait_for_timeout_calls: list[int] = []
        self._action_hook = None

    def set_html(self, html: str) -> None:
        self._html = html

    def set_frame(self, frame: FakeNavigationFrame) -> None:
        self._frame = frame

    def set_action_hook(self, hook) -> None:
        """Install ``hook(action, selector, timeout)`` for fake actions.

        Shared with this page's locators and ``wait_for_timeout``. Tests use
        it to advance a controlled clock by a chosen amount on a chosen
        action, modeling operation duration. ``None`` (default) keeps
        immediate/no-op behavior so unrelated tests are undisturbed.
        """
        self._action_hook = hook

    def _fire_action(self, action: str, selector: str, timeout: int | None) -> None:
        if self._action_hook is not None:
            self._action_hook(action, selector, timeout)

    def make_selector_visible(self, selector: str) -> None:
        """Mark a CSS selector as visible (locator wait succeeds)."""
        self._visible_selectors.add(selector)

    def on_click_make_visible(self, clicked_selector: str, make_visible: str) -> None:
        """Register that when clicked_selector is clicked, make_visible becomes visible."""
        self._click_callbacks.setdefault(clicked_selector, []).append(make_visible)

    def content(self) -> str:
        return self._html

    def locator(self, selector: str, has_text: Any = None) -> FakeNavigationLocator:  # noqa: ARG002
        self._locator_calls.append(selector)
        return FakeNavigationLocator(
            selector=selector,
            visible_getter=lambda: selector in self._visible_selectors,
            on_click_callback=lambda: self._on_click_hook(selector),
            fill_callback=lambda value: self._filled_values.__setitem__(
                selector, value
            ),
            wait_callback=self._record_wait,
            click_callback=self._record_click,
            fill_timeout_callback=self._record_fill,
            action_hook=self._fire_action,
        )

    def get_by_role(self, role: str, *, name: str | None = None) -> FakeNavigationLocator:
        self._role_calls.append((role, name))
        key = f"role:{role}:{name}" if name else f"role:{role}"
        return FakeNavigationLocator(
            selector=key,
            visible_getter=lambda: key in self._visible_selectors,
            on_click_callback=lambda: self._on_click_hook(key),
            wait_callback=self._record_wait,
            click_callback=self._record_click,
            fill_timeout_callback=self._record_fill,
            action_hook=self._fire_action,
        )

    def get_by_text(self, text: str, *, exact: bool = False) -> FakeNavigationLocator:  # noqa: ARG002
        self._text_calls.append(text)
        key = f"text:{text}"
        return FakeNavigationLocator(
            selector=key,
            visible_getter=lambda: key in self._visible_selectors,
            on_click_callback=lambda: self._on_click_hook(key),
            wait_callback=self._record_wait,
            click_callback=self._record_click,
            fill_timeout_callback=self._record_fill,
            action_hook=self._fire_action,
        )

    def wait_for_timeout(self, timeout_ms: int) -> None:  # noqa: ARG002
        """Simulate Playwright's page.wait_for_timeout().

        Recorded (not a silent no-op) and fires the optional action hook so
        tests can model that a polling pause consumes controlled time.
        """
        self._wait_for_timeout_calls.append(timeout_ms)
        self._fire_action("wait_for_timeout", "page", timeout_ms)

    def _on_click_hook(self, clicked_selector: str) -> None:
        """Internal callback when a locator is clicked."""
        for make_visible in self._click_callbacks.get(clicked_selector, []):
            self._visible_selectors.add(make_visible)

    def _record_wait(self, state: str, timeout: int) -> None:  # noqa: ARG002
        self._wait_timeouts.append(timeout)
        self._action_timeouts.append(timeout)

    def _record_click(self, timeout: int) -> None:
        self._click_timeouts.append(timeout)
        self._action_timeouts.append(timeout)

    def _record_fill(self, timeout: int) -> None:
        self._fill_timeouts.append(timeout)
        self._action_timeouts.append(timeout)

    def frame(self, name: str) -> FakeNavigationFrame | None:
        self._frame_name_calls.append(name)
        return self._frame

    # --- Test query helpers ---

    @property
    def locator_calls(self) -> list[str]:
        return list(self._locator_calls)

    @property
    def role_calls(self) -> list[tuple[str, str | None]]:
        return list(self._role_calls)

    @property
    def text_calls(self) -> list[str]:
        return list(self._text_calls)

    @property
    def frame_name_calls(self) -> list[str]:
        return list(self._frame_name_calls)

    @property
    def filled_values(self) -> dict[str, str]:
        """Map of CSS selector -> last fill() value applied to any locator."""
        return dict(self._filled_values)

    @property
    def wait_timeouts(self) -> list[int]:
        """Timeout values passed to ``wait_for`` on locators from this page."""
        return list(self._wait_timeouts)

    @property
    def click_timeouts(self) -> list[int]:
        """Timeout values passed to ``click`` on locators from this page."""
        return list(self._click_timeouts)

    @property
    def fill_timeouts(self) -> list[int]:
        """Timeout values passed to ``fill`` on locators from this page."""
        return list(self._fill_timeouts)

    @property
    def action_timeouts(self) -> list[int]:
        """Every wait/click/fill timeout in call order (time-ordered)."""
        return list(self._action_timeouts)

    @property
    def wait_for_timeout_calls(self) -> list[int]:
        """Timeout values passed to ``page.wait_for_timeout()`` in order."""
        return list(self._wait_for_timeout_calls)


class FakeNavigationLocator:
    """Fake Playwright locator with lazy visibility check."""

    def __init__(
        self,
        selector: str,
        visible_getter,
        on_click_callback=None,
        fill_callback=None,
        wait_callback=None,
        click_callback=None,
        fill_timeout_callback=None,
        action_hook=None,
    ) -> None:
        self._selector = selector
        self._visible_getter = visible_getter
        self._on_click_callback = on_click_callback
        self._fill_callback = fill_callback
        self._wait_callback = wait_callback
        self._click_callback = click_callback
        self._fill_timeout_callback = fill_timeout_callback
        self._action_hook = action_hook
        self._clicked = False
        self._filled_value: str | None = None

    @property
    def first(self):
        """Simulate Playwright's ``locator.first``."""
        return self

    def wait_for(self, *, state: str = "visible", timeout: int | None = None) -> None:  # noqa: ARG002
        if self._wait_callback is not None:
            self._wait_callback(state, timeout)
        if self._action_hook is not None:
            self._action_hook("wait", self._selector, timeout)
        if state == "visible" and not self._visible_getter():
            raise Exception(f"Locator {self._selector} not visible")  # noqa: TRY002

    def click(self, *, timeout: int | None = None) -> None:
        if self._click_callback is not None:
            self._click_callback(timeout)
        if self._action_hook is not None:
            self._action_hook("click", self._selector, timeout)
        self._clicked = True
        if self._on_click_callback:
            self._on_click_callback()

    def fill(self, value: str, *, timeout: int | None = None) -> None:
        if self._fill_timeout_callback is not None:
            self._fill_timeout_callback(timeout)
        if self._action_hook is not None:
            self._action_hook("fill", self._selector, timeout)
        self._filled_value = value
        if self._fill_callback:
            self._fill_callback(value)

    def count(self) -> int:
        """Return 1 if this locator is visible, 0 otherwise."""
        try:
            return 1 if self._visible_getter() else 0
        except Exception:
            return 0

    def is_visible(self) -> bool:
        """Simulate Playwright's ``locator.is_visible()``."""
        try:
            return bool(self._visible_getter())
        except Exception:
            return False

    def locator(self, selector: str) -> "FakeNavigationLocator":
        """Return a sub-locator (delegates visibility to parent)."""
        return FakeNavigationLocator(
            selector=f"{self._selector} >> {selector}",
            visible_getter=self._visible_getter,
            on_click_callback=self._on_click_callback,
            action_hook=self._action_hook,
        )

    @property
    def was_clicked(self) -> bool:
        return self._clicked

    @property
    def filled_value(self) -> str | None:
        return self._filled_value


class FakeNavigationFrame:
    """Fake Playwright frame that supports locator queries on HTML."""

    def __init__(self, html: str = "") -> None:
        self._html = html
        self.name = "frame_pol"
        self._url = "/internacoes/consulta.xhtml"
        self._locator_calls: list[str] = []
        self._role_calls: list[tuple[str, str | None]] = []
        self._eval_calls: list[str] = []
        self._eval_results: dict[str, list[dict]] = {}
        self._visible_selectors: set[str] = set()
        self._evaluate_result: dict[str, str] = {}
        self._evaluate_calls: list[str] = []
        self._wait_timeouts: list[int] = []
        self._click_timeouts: list[int] = []
        self._fill_timeouts: list[int] = []
        self._action_timeouts: list[int] = []
        self._action_hook = None

    def set_html(self, html: str) -> None:
        self._html = html

    def set_url(self, url: str) -> None:
        self._url = url

    def set_action_hook(self, hook) -> None:
        """Install ``hook(action, selector, timeout)`` for frame actions.

        Shared with this frame's locators so readiness waits (Cadastro and
        identity) can model operation duration against one clock. ``None``
        (default) keeps immediate/no-op behavior.
        """
        self._action_hook = hook

    def _fire_action(self, action: str, selector: str, timeout: int | None) -> None:
        if self._action_hook is not None:
            self._action_hook(action, selector, timeout)

    def make_selector_visible(self, selector: str) -> None:
        self._visible_selectors.add(selector)

    def content(self) -> str:
        return self._html

    @property
    def url(self) -> str:
        return self._url

    def locator(self, selector: str) -> FakeNavigationLocator:
        self._locator_calls.append(selector)
        return FakeNavigationLocator(
            selector=selector,
            visible_getter=lambda: selector in self._visible_selectors,
            wait_callback=self._record_wait,
            click_callback=self._record_click,
            fill_timeout_callback=self._record_fill,
            action_hook=self._fire_action,
        )

    def get_by_role(self, role: str, *, name: str | None = None) -> FakeNavigationLocator:
        self._role_calls.append((role, name))
        key = f"role:{role}:{name}" if name else f"role:{role}"
        return FakeNavigationLocator(
            selector=key,
            visible_getter=lambda: key in self._visible_selectors,
            wait_callback=self._record_wait,
            click_callback=self._record_click,
            fill_timeout_callback=self._record_fill,
            action_hook=self._fire_action,
        )

    def eval_on_selector_all(self, selector: str, expression: str) -> list[dict]:  # noqa: ARG002
        """Simulate extracting admission rows via eval."""
        self._eval_calls.append(f"{expression} on {selector}")
        result = self._eval_results.get(selector, [])
        return list(result)  # type: ignore[return-value]

    def set_eval_result(self, selector: str, result: list[dict]) -> None:
        self._eval_results[selector] = result

    def set_evaluate_result(self, result: dict[str, str]) -> None:
        """Register the dict returned by frame.evaluate() (demographics read)."""
        self._evaluate_result = dict(result)

    def _record_wait(self, state: str, timeout: int) -> None:  # noqa: ARG002
        self._wait_timeouts.append(timeout)
        self._action_timeouts.append(timeout)

    def _record_click(self, timeout: int) -> None:
        self._click_timeouts.append(timeout)
        self._action_timeouts.append(timeout)

    def _record_fill(self, timeout: int) -> None:
        self._fill_timeouts.append(timeout)
        self._action_timeouts.append(timeout)

    def evaluate(self, expression: str, arg: Any = None) -> Any:  # noqa: ARG002
        """Simulate Playwright's frame.evaluate(expression, arg)."""
        self._evaluate_calls.append(expression)
        return dict(self._evaluate_result)

    @property
    def evaluate_calls(self) -> list[str]:
        return list(self._evaluate_calls)

    @property
    def wait_timeouts(self) -> list[int]:
        """Timeout values passed to ``wait_for`` on locators from this frame."""
        return list(self._wait_timeouts)

    @property
    def click_timeouts(self) -> list[int]:
        """Timeout values passed to ``click`` on locators from this frame."""
        return list(self._click_timeouts)

    @property
    def fill_timeouts(self) -> list[int]:
        """Timeout values passed to ``fill`` on locators from this frame."""
        return list(self._fill_timeouts)

    @property
    def action_timeouts(self) -> list[int]:
        """Every wait/click/fill timeout in call order (time-ordered)."""
        return list(self._action_timeouts)


class FakeClock:
    """Deterministic monotonic clock for deadline tests.

    Each call to ``monotonic()`` returns the next value, advancing by
    ``step`` seconds. Tests pass ``step > 0`` to model elapsed time without
    wall-clock sleeps. Patch it onto ``time.monotonic`` for the duration of
    one test.

    ``advance(seconds)`` jumps the clock forward by an explicit amount (used
    by fake action hooks to model that an operation consumed time).
    """

    def __init__(self, *, start: float = 1000.0, step: float = 0.0) -> None:
        self._next = start
        self._step = step
        self.calls = 0

    def monotonic(self) -> float:
        value = self._next
        self._next += self._step
        self.calls += 1
        return value

    def advance(self, seconds: float) -> None:
        """Jump the clock forward by ``seconds`` (model consumed time)."""
        self._next += seconds


# ===========================================================================
# Build representative eval results for admissions table
# ===========================================================================

_ADMISSIONS_EVAL_ROWS = [
    {
        "dataRi": "0",
        "dataRk": "ADM-RK-001",
        "cells": [
            "15/01/2024",
            "20/01/2024",
            "Enfermaria A",
            "Leito 101",
            "Detalhes",
        ],
        "hasDetailsLink": True,
    },
    {
        "dataRi": "1",
        "dataRk": "ADM-RK-002",
        "cells": [
            "01/03/2024",
            "",
            "UTI",
            "Leito 005",
            "Detalhes",
        ],
        "hasDetailsLink": True,
    },
]


# ===========================================================================
# Tests: legacy_navigation module
# ===========================================================================


class TestEnsureSearchScreen:
    """Tests for ensure_search_screen()."""

    def test_search_screen_already_visible_does_nothing(self) -> None:
        """When #prontuarioInput is already visible, no fallback is needed."""
        from apps.ingestion.extractors.legacy_navigation import (
            ensure_search_screen,
        )

        page = FakeNavigationPage()
        page.make_selector_visible("#prontuarioInput")

        ensure_search_screen(page)

        # Should have checked the prontuarioInput locator
        assert "#prontuarioInput" in page.locator_calls

    def test_search_screen_retries_when_not_visible(self) -> None:
        """When #prontuarioInput is not initially visible, fallback is tried."""
        from apps.ingestion.extractors.legacy_navigation import (
            ensure_search_screen,
        )

        page = FakeNavigationPage()
        # #prontuarioInput NOT visible initially
        # Make polMenu visible for the fallback
        page.make_selector_visible("#polMenu")
        # When polMenu is clicked, prontuarioInput becomes visible
        page.on_click_make_visible("#polMenu", "#prontuarioInput")

        ensure_search_screen(page)

        # Should have tried #polMenu as fallback
        assert "#polMenu" in page.locator_calls

    def test_pol_menu_present_click_timeout_raises_typed(self) -> None:
        """D11: POL menu present but click raises Playwright timeout → typed."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
            ensure_search_screen,
        )

        page = FakeNavigationPage()
        page.make_selector_visible("#polMenu")

        original_click = FakeNavigationLocator.click

        def _raise_timeout(self, *, timeout=None):
            raise PlaywrightTimeoutError("Timeout 30000ms")

        FakeNavigationLocator.click = _raise_timeout  # type: ignore[method-assign]
        try:
            with pytest.raises(NavigationTimeoutError):
                ensure_search_screen(page)
        finally:
            FakeNavigationLocator.click = original_click  # type: ignore[method-assign]

    def test_pol_menu_present_readiness_wait_timeout_raises_typed(self) -> None:
        """D11: POL menu present, click ok, but prontuario readiness wait
        raises Playwright timeout → typed."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
            ensure_search_screen,
        )

        page = FakeNavigationPage()
        page.make_selector_visible("#polMenu")
        page.on_click_make_visible("#polMenu", "#prontuarioInput")

        call_count = {"n": 0}
        original_wait_for = FakeNavigationLocator.wait_for

        def _conditional_timeout(self, *, state="visible", timeout=None):
            call_count["n"] += 1
            # Call 1: Strategy 1 prontuario (not visible → generic Exception).
            # Call 2: Strategy 2 readiness prontuario (after POL click) →
            # Playwright timeout (must not be swallowed).
            if call_count["n"] >= 2:
                raise PlaywrightTimeoutError("Timeout 6000ms")
            if state == "visible" and not self._visible_getter():
                raise Exception(f"not visible: {self._selector}")

        FakeNavigationLocator.wait_for = _conditional_timeout  # type: ignore[method-assign]
        try:
            with pytest.raises(NavigationTimeoutError):
                ensure_search_screen(page)
        finally:
            FakeNavigationLocator.wait_for = original_wait_for  # type: ignore[method-assign]

    def test_dashboard_present_click_timeout_raises_typed(self) -> None:
        """D11: dashboard present but click raises Playwright timeout → typed."""
        import re

        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
            ensure_search_screen,
        )

        page = FakeNavigationPage()
        # Compute the exact key produced by get_by_role with a regex name.
        name_re = re.compile(r"Clique aqui para acessar o", re.IGNORECASE)
        page.make_selector_visible(f"role:button:{name_re}")

        original_click = FakeNavigationLocator.click

        def _raise_timeout(self, *, timeout=None):
            raise PlaywrightTimeoutError("Timeout 30000ms")

        FakeNavigationLocator.click = _raise_timeout  # type: ignore[method-assign]
        try:
            with pytest.raises(NavigationTimeoutError):
                ensure_search_screen(page)
        finally:
            FakeNavigationLocator.click = original_click  # type: ignore[method-assign]

    def test_dashboard_present_readiness_wait_timeout_raises_typed(self) -> None:
        """D19/R3: dashboard present, click ok, but the post-click prontuario
        readiness wait raises a Playwright timeout → typed
        NavigationTimeoutError (direct regression coverage for the dashboard
        post-click readiness path)."""
        import re

        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
            ensure_search_screen,
        )

        page = FakeNavigationPage()
        name_re = re.compile(r"Clique aqui para acessar o", re.IGNORECASE)
        page.make_selector_visible(f"role:button:{name_re}")
        page.on_click_make_visible(f"role:button:{name_re}", "#prontuarioInput")

        call_count = {"n": 0}
        original_wait_for = FakeNavigationLocator.wait_for

        def _conditional_timeout(self, *, state="visible", timeout=None):
            call_count["n"] += 1
            # Call 1: Strategy 1 prontuario (not visible → generic Exception).
            # Call 2: Strategy 3 dashboard post-click readiness prontuario →
            # Playwright timeout (must not be swallowed).
            if call_count["n"] >= 2:
                raise PlaywrightTimeoutError("Timeout 6000ms")
            if state == "visible" and not self._visible_getter():
                raise Exception(f"not visible: {self._selector}")

        FakeNavigationLocator.wait_for = _conditional_timeout  # type: ignore[method-assign]
        try:
            with pytest.raises(NavigationTimeoutError):
                ensure_search_screen(page)
        finally:
            FakeNavigationLocator.wait_for = original_wait_for  # type: ignore[method-assign]

    def test_both_fallbacks_absent_raises_navigation_error(self) -> None:
        """D11: both POL menu and dashboard absent → ordinary NavigationError."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
            ensure_search_screen,
        )

        page = FakeNavigationPage()
        # Nothing visible at all.
        with pytest.raises(NavigationError):
            ensure_search_screen(page)


class TestSearchPatient:
    """Tests for search_patient()."""

    def test_fills_prontuario_and_clicks_pesquisa_avancada(self) -> None:
        """search_patient fills #prontuarioInput and clicks Pesquisa Avançada."""
        from apps.ingestion.extractors.legacy_navigation import (
            search_patient,
        )

        page = FakeNavigationPage()
        page.make_selector_visible("#prontuarioInput")
        page.make_selector_visible("role:link:Pesquisa Avançada")

        search_patient(page, patient_record="1234567")

        # Prontuario input should have been filled
        assert "#prontuarioInput" in page.locator_calls
        # Pesquisa Avançada link should have been clicked
        assert ("link", "Pesquisa Avançada") in page.role_calls

    def test_normalizes_patient_record(self) -> None:
        """Patient record with non-digit chars is normalized to digits only."""
        from apps.ingestion.extractors.legacy_navigation import (
            normalize_patient_record,
        )

        assert normalize_patient_record("123/45 A") == "12345"
        assert normalize_patient_record("abc") == "abc"
        assert normalize_patient_record("") == ""
        assert normalize_patient_record("  007  ") == "007"


class TestClickInternacoes:
    """Tests for click_internacoes()."""

    def test_clicks_internacoes_text(self) -> None:
        """click_internacoes clicks the Internações text element."""
        from apps.ingestion.extractors.legacy_navigation import (
            click_internacoes,
        )

        page = FakeNavigationPage()
        page.make_selector_visible("text:Internações")

        click_internacoes(page)

        assert "Internações" in page.text_calls

    def test_playwright_timeout_becomes_navigation_timeout(self) -> None:
        """PSW-S17 R2 (second closure): a real Playwright TimeoutError from
        the required wait/click becomes NavigationTimeoutError, not a
        generic NavigationError."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
            click_internacoes,
        )

        page = FakeNavigationPage()

        # Force the FakeNavigationLocator.wait_for to raise a real
        # Playwright TimeoutError so the source boundary can map it.
        original_wait_for = FakeNavigationLocator.wait_for

        def _raise_playwright_timeout(self, *, state="visible", timeout=None):
            raise PlaywrightTimeoutError("Timeout 15000ms")

        FakeNavigationLocator.wait_for = _raise_playwright_timeout  # type: ignore[method-assign]
        try:
            with pytest.raises(NavigationTimeoutError):
                click_internacoes(page)
        finally:
            FakeNavigationLocator.wait_for = original_wait_for  # type: ignore[method-assign]


class TestWaitForAdmissionsTable:
    """Tests for wait_for_admissions_table()."""

    def test_waits_for_frame_pol_and_table_rows(self) -> None:
        """wait_for_admissions_table polls for frame_pol and table rows."""
        from apps.ingestion.extractors.legacy_navigation import (
            SEL_INTERNACOES_TABLE_ROWS,
            wait_for_admissions_table,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html=ADMISSIONS_TABLE_HTML)
        # Frame has the table rows selector visible
        frame.make_selector_visible(SEL_INTERNACOES_TABLE_ROWS)
        page.set_frame(frame)

        result = wait_for_admissions_table(page, timeout_ms=5000)

        assert result is frame
        assert "frame_pol" in page.frame_name_calls

    def test_raises_when_frame_not_found(self) -> None:
        """Raises NavigationTimeoutError when frame_pol is never found within
        the whole-operation budget (PSW-S17 R2 second closure)."""
        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
            wait_for_admissions_table,
        )

        page = FakeNavigationPage()
        # No frame set — whole-operation budget expires.

        with pytest.raises(NavigationTimeoutError):
            wait_for_admissions_table(page, timeout_ms=500)


class TestReadAdmissionsRows:
    """Tests for read_admissions_rows()."""

    def test_returns_valid_admission_rows(self) -> None:
        """Reads and parses admission rows from the frame."""
        from apps.ingestion.extractors.legacy_navigation import (
            read_admissions_rows,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html=ADMISSIONS_TABLE_HTML)
        frame.set_eval_result(
            "#tabelaInternacoes\\:resultList_data > tr",
            list(_ADMISSIONS_EVAL_ROWS),
        )
        page.set_frame(frame)

        rows = read_admissions_rows(page)

        assert len(rows) == 2
        assert rows[0]["admissionKey"] == "ADM-RK-001"
        assert rows[0]["admissionStart"] is not None
        assert rows[0]["admissionEnd"] is not None
        assert rows[0]["ward"] == "Enfermaria A"
        assert rows[0]["bed"] == "Leito 101"

        # Second admission is open-ended
        assert rows[1]["admissionKey"] == "ADM-RK-002"
        assert rows[1]["admissionEnd"] is None

    def test_returns_empty_list_when_no_rows(self) -> None:
        """Returns empty list when table has no rows."""
        from apps.ingestion.extractors.legacy_navigation import (
            read_admissions_rows,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html=EMPTY_ADMISSIONS_TABLE_HTML)
        frame.set_eval_result(
            "#tabelaInternacoes\\:resultList_data > tr",
            [],
        )
        page.set_frame(frame)

        rows = read_admissions_rows(page)
        assert rows == []

    def test_skips_rows_without_details_link(self) -> None:
        """Skips rows that don't have a details link."""
        from apps.ingestion.extractors.legacy_navigation import (
            read_admissions_rows,
        )

        rows_with_missing = [
            {
                "dataRi": "0",
                "dataRk": "ADM-RK-001",
                "cells": ["15/01/2024", "20/01/2024", "A", "B", "nope"],
                "hasDetailsLink": False,
            },
            {
                "dataRi": "1",
                "dataRk": "ADM-RK-002",
                "cells": ["01/03/2024", "", "UTI", "Leito 005", "Detalhes"],
                "hasDetailsLink": True,
            },
        ]

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html=ADMISSIONS_TABLE_HTML)
        frame.set_eval_result(
            "#tabelaInternacoes\\:resultList_data > tr",
            rows_with_missing,
        )
        page.set_frame(frame)

        rows = read_admissions_rows(page)
        assert len(rows) == 1
        assert rows[0]["admissionKey"] == "ADM-RK-002"


class TestBuildAdmissionSnapshot:
    """Tests for build_admission_snapshot()."""

    def test_converts_to_canonical_snapshot(self) -> None:
        """Converts admission rows to canonical snapshot format."""
        from datetime import date

        from apps.ingestion.extractors.legacy_navigation import (
            _build_admission_snapshot,
        )

        admissions = [
            {
                "admissionKey": "ADM-RK-001",
                "admissionStart": date(2024, 1, 15),
                "admissionEnd": date(2024, 1, 20),
                "ward": "Enfermaria A",
                "bed": "Leito 101",
            },
            {
                "admissionKey": "ADM-RK-002",
                "admissionStart": date(2024, 3, 1),
                "admissionEnd": None,
                "ward": "UTI",
                "bed": "Leito 005",
            },
        ]

        snapshot = _build_admission_snapshot(admissions)

        assert len(snapshot) == 2
        assert snapshot[0]["admissionKey"] == "ADM-RK-001"
        assert snapshot[0]["admissionStart"] == "2024-01-15"
        assert snapshot[0]["admissionEnd"] == "2024-01-20"
        assert snapshot[1]["admissionEnd"] is None

    def test_empty_input_returns_empty_snapshot(self) -> None:
        """Empty admission list returns empty snapshot."""
        from apps.ingestion.extractors.legacy_navigation import (
            _build_admission_snapshot,
        )

        assert _build_admission_snapshot([]) == []


# ===========================================================================
# Tests: RealHandleBridge navigation (integration)
# ===========================================================================


class FakePageWithHtml:
    """Minimal page mock for bridge navigation tests.

    Exposes ``locator``, ``get_by_role``, ``get_by_text``, ``frame``,
    and ``content``, all returning sensible defaults.
    """

    def __init__(self) -> None:
        self._html: str = ""
        self._frame: object = None
        self._locators: dict[str, object] = {}
        self._visible_selectors: set[str] = set()

    def set_html(self, html: str) -> None:
        self._html = html

    def set_frame(self, frame: object) -> None:
        self._frame = frame

    def make_visible(self, selector: str) -> None:
        self._visible_selectors.add(selector)

    def wait_for_timeout(self, timeout_ms: int) -> None:  # noqa: ARG002
        pass

    def content(self) -> str:
        return self._html

    def locator(self, selector: str) -> MagicMock:
        mock = MagicMock()
        # If the selector is visible, wait_for succeeds; otherwise fails
        if selector in self._visible_selectors:
            mock.wait_for = MagicMock()
        else:
            mock.wait_for.side_effect = Exception(f"locator {selector} not visible")
        mock.click = MagicMock()
        mock.fill = MagicMock()
        return mock

    def get_by_role(self, role: str, *, name: str | None = None) -> MagicMock:  # noqa: ARG002
        key = f"role:{role}:{name}" if name else f"role:{role}"
        mock = MagicMock()
        if key in self._visible_selectors:
            mock.wait_for = MagicMock()
        else:
            mock.wait_for.side_effect = Exception(f"locator {key} not visible")
        mock.click = MagicMock()
        return mock

    def get_by_text(self, text: str, *, exact: bool = False) -> MagicMock:  # noqa: ARG002
        key = f"text:{text}"
        mock = MagicMock()
        if key in self._visible_selectors:
            mock.wait_for = MagicMock()
        else:
            mock.wait_for.side_effect = Exception(f"locator {key} not visible")
        mock.click = MagicMock()
        return mock

    def frame(self, name: str) -> object | None:  # noqa: ARG002
        return self._frame


class TestBridgeAdmissionsNavigation:
    """Tests that the bridge can navigate via UI actions for admissions."""

    def test_navigate_to_admissions_calls_expected_actions(self) -> None:
        """Bridge navigation calls the expected UI action sequence."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        # Create a real PlaywrightSessionHandle-like mock that has
        # ensure_current_page() to provide the page for navigation.
        handle = MagicMock()
        handle.is_connected.return_value = True
        handle.get_page_html.return_value = ADMISSIONS_TABLE_HTML
        handle.get_tab_classes.return_value = [
            "tabs-first tabs-last tabs-selected",
        ]
        handle.open_tab.return_value = True

        frame = MagicMock()
        frame.name = "frame_pol"
        frame.eval_on_selector_all.return_value = list(_ADMISSIONS_EVAL_ROWS)

        frame = MagicMock()
        frame.name = "frame_pol"
        frame.eval_on_selector_all.return_value = list(_ADMISSIONS_EVAL_ROWS)

        page = FakePageWithHtml()
        page.set_html(ADMISSIONS_TABLE_HTML)
        page.set_frame(frame)
        page.make_visible("#prontuarioInput")
        page.make_visible("role:link:Pesquisa Avançada")
        page.make_visible("text:Internações")
        handle.ensure_current_page.return_value = page

        handle.set_html = lambda html: handle.get_page_html.__setattr__(
            "return_value", html
        ) or None

        bridge = RealHandleBridge(handle)

        # Navigate via UI actions
        result = bridge.navigate_to_admissions(patient_record="1234567")

        # Must return True when successful
        assert result is True

        # The bridge should have interacted with the page via the
        # navigation helpers — the ensure_current_page was called.
        handle.ensure_current_page.assert_called()

    def test_navigate_to_admissions_builds_synthetic_container(self) -> None:
        """After navigation, get_page_html returns the synthetic container."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        frame = MagicMock()
        frame.name = "frame_pol"
        frame.url = "/internacoes/consulta.xhtml"
        frame.eval_on_selector_all.return_value = list(_ADMISSIONS_EVAL_ROWS)

        page = FakePageWithHtml()
        page.set_html(ADMISSIONS_TABLE_HTML)
        page.set_frame(frame)
        page.make_visible("#prontuarioInput")
        page.make_visible("role:link:Pesquisa Avançada")
        page.make_visible("text:Internações")

        handle = MagicMock()
        handle.is_connected.return_value = True
        handle.get_page_html.return_value = ADMISSIONS_TABLE_HTML
        handle.ensure_current_page.return_value = page
        handle.get_tab_classes.return_value = [
            "tabs-first tabs-last tabs-selected",
        ]
        # Make set_html actually update what get_page_html returns.
        handle.set_html = lambda html: handle.get_page_html.__setattr__(
            "return_value", html
        ) or None

        bridge = RealHandleBridge(handle)

        # Navigate first
        result = bridge.navigate_to_admissions(patient_record="1234567")
        assert result is True

        # Then get the HTML — should contain synthetic container
        result_html = bridge.get_page_html()

        assert _ADMISSION_DATA_DIV_ID in result_html

        # Parse JSON from the container
        import re  # noqa: PLC0415 - used only in test
        match = re.search(
            r'<div\s+id="admission-snapshot-data">(.*?)</div>',
            result_html,
            re.DOTALL,
        )
        assert match is not None
        data = json.loads(match.group(1))
        assert len(data) == 2
        assert data[0]["admissionKey"] == "ADM-RK-001"
        assert data[0]["admissionStart"] == "2024-01-15"

    def test_navigate_to_admissions_fails_with_none_page(self) -> None:
        """Navigation returns False when ensure_current_page returns None."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        handle = MagicMock(spec=["ensure_current_page"])
        handle.ensure_current_page.return_value = None

        bridge = RealHandleBridge(handle)

        result = bridge.navigate_to_admissions(patient_record="1234567")

        assert result is False

    def test_navigate_to_admissions_without_set_html_uses_regex_container(
        self,
    ) -> None:
        """Real ``PlaywrightSessionHandle`` has no ``set_html``.

        When the wrapped handle exposes only ``get_page_html`` and
        ``ensure_current_page`` (the real persistent handle contract),
        ``navigate_to_admissions`` cannot inject the JS-eval snapshot via
        ``set_html``. It instead marks the page context as admissions, and
        the next ``get_page_html()`` re-parses the raw legacy table HTML into
        the canonical synthetic container via the PSW-S9 regex parser.

        This characterizes the real-handle path so it is not silently
        broken: navigation still reuses the already-open page (no new
        browser/subprocess) and the adapter still receives valid admission
        data, just sourced from the regex parser instead of the JS-eval
        snapshot.
        """
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        frame = MagicMock()
        frame.name = "frame_pol"
        frame.url = "/internacoes/consulta.xhtml"
        frame.eval_on_selector_all.return_value = list(_ADMISSIONS_EVAL_ROWS)

        page = FakePageWithHtml()
        page.set_html(ADMISSIONS_TABLE_HTML)
        page.set_frame(frame)
        page.make_visible("#prontuarioInput")
        page.make_visible("role:link:Pesquisa Avançada")
        page.make_visible("text:Internações")

        class _HandleWithoutSetHtml:
            """Mirrors PlaywrightSessionHandle: no ``set_html`` method."""

            def __init__(self, current_page, html):
                self._page = current_page
                self._html = html

            def get_page_html(self):
                return self._html

            def ensure_current_page(self):
                return self._page

        handle = _HandleWithoutSetHtml(page, ADMISSIONS_TABLE_HTML)

        bridge = RealHandleBridge(handle)  # type: ignore[arg-type]

        result = bridge.navigate_to_admissions(patient_record="1234567")
        assert result is True

        html = bridge.get_page_html()
        assert _ADMISSION_DATA_DIV_ID in html

        import re  # noqa: PLC0415 - test-only local import

        match = re.search(
            r'<div\s+id="admission-snapshot-data">(.*?)</div>',
            html,
            re.DOTALL,
        )
        assert match is not None
        data = json.loads(match.group(1))
        assert len(data) == 2
        assert data[0]["admissionKey"] == "ADM-RK-001"
        assert data[0]["admissionStart"] == "2024-01-15"
        assert data[0]["admissionEnd"] == "2024-01-20"
        assert data[1]["admissionKey"] == "ADM-RK-002"
        assert data[1]["admissionEnd"] is None


class TestChooseOverlappingAdmissions:
    """Tests for choose_overlapping_admissions()."""

    def test_selects_admissions_overlapping_window(self) -> None:
        """Returns admissions that overlap the requested window."""
        from apps.ingestion.extractors.legacy_navigation import (
            choose_overlapping_admissions,
        )

        admissions: list[dict[str, Any]] = [
            {"admissionKey": "ADM-001", "admissionStart": "2024-01-15",
             "admissionEnd": "2024-01-20", "ward": "A", "bed": "1"},
            {"admissionKey": "ADM-002", "admissionStart": "2024-03-01",
             "admissionEnd": None, "ward": "B", "bed": "2"},
            {"admissionKey": "ADM-003", "admissionStart": "2024-06-01",
             "admissionEnd": "2024-06-10", "ward": "C", "bed": "3"},
        ]

        # Window overlapping first and second admissions
        result = choose_overlapping_admissions(
            admissions,
            start_date="2024-01-01",
            end_date="2024-03-15",
        )

        assert len(result) == 2
        assert result[0]["admissionKey"] == "ADM-001"
        assert result[1]["admissionKey"] == "ADM-002"

    def test_no_overlap_raises_navigation_error(self) -> None:
        """No overlapping admission raises NavigationError."""
        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
            choose_overlapping_admissions,
        )

        admissions = [
            {"admissionKey": "ADM-001", "admissionStart": "2024-01-15",
             "admissionEnd": "2024-01-20", "ward": "A", "bed": "1"},
        ]

        with pytest.raises(
            NavigationError,
            match="Nenhuma internação com interseção",
        ):
            choose_overlapping_admissions(
                admissions,
                start_date="2024-06-01",
                end_date="2024-06-30",
            )

    def test_open_ended_admission_overlaps_any_future_window(self) -> None:
        """Admission without end date overlaps any future window."""
        from apps.ingestion.extractors.legacy_navigation import (
            choose_overlapping_admissions,
        )

        admissions = [
            {"admissionKey": "ADM-001", "admissionStart": "2024-01-15",
             "admissionEnd": None, "ward": "A", "bed": "1"},
        ]

        result = choose_overlapping_admissions(
            admissions,
            start_date="2024-06-01",
            end_date="2024-06-30",
        )

        assert len(result) == 1
        assert result[0]["admissionKey"] == "ADM-001"

    def test_empty_admissions_list_raises_error(self) -> None:
        """Empty admissions list raises NavigationError."""
        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
            choose_overlapping_admissions,
        )

        with pytest.raises(NavigationError, match="Nenhuma internação"):
            choose_overlapping_admissions(
                [],
                start_date="2024-01-01",
                end_date="2024-01-31",
            )


class TestEvolutionNavigationHelpers:
    """Tests for evolution-level navigation helpers."""

    def test_open_internacao_detail_clicks_details_link(self) -> None:
        """open_internacao_detail clicks the details link for the given key."""
        from apps.ingestion.extractors.legacy_navigation import (
            SEL_DETAILS_LINK,
            SEL_INTERNACOES_TABLE_BODY,
            open_internacao_detail,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        # Make the row and the compound details link selector visible
        row_selector = (
            f'{SEL_INTERNACOES_TABLE_BODY} > '
            f'tr[data-rk="ADM-RK-001"]'
        )
        details_row_selector = (
            f'{row_selector} {SEL_DETAILS_LINK}'
        )
        frame.make_selector_visible(row_selector)
        frame.make_selector_visible(details_row_selector)
        page.set_frame(frame)

        open_internacao_detail(page, admission_key="ADM-RK-001")

        # The frame's locator was called for the right row selector
        assert row_selector in frame._locator_calls

    def test_open_internacao_detail_nonexistent_key_raises(self) -> None:
        """Opening detail for non-existent key raises a sanitized
        NavigationError that does NOT include the admission key
        (PSW-S17 R6 second closure)."""
        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
            open_internacao_detail,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        page.set_frame(frame)

        sentinel_key = "SENSITIVE-ADMISSION-KEY"
        with pytest.raises(NavigationError) as exc_info:
            open_internacao_detail(
                page, admission_key=sentinel_key
            )
        message = str(exc_info.value)
        # PSW-S17 R6: admission key must NOT leak into the error message.
        assert sentinel_key not in message

    def test_click_evolucao_button(self) -> None:
        """click_evolucao clicks the Evolução button in frame_pol."""
        from apps.ingestion.extractors.legacy_navigation import (
            click_evolucao,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        frame.make_selector_visible("role:button:Evolução")
        page.set_frame(frame)

        click_evolucao(page)

        # The frame's get_by_role was called for button + Evolução
        assert ("button", "Evolução") in frame._role_calls

    def test_fill_evolution_dates_fills_br_format(self) -> None:
        """fill_evolution_dates fills DD/MM/YYYY dates."""
        from apps.ingestion.extractors.legacy_navigation import (
            fill_evolution_dates,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        frame.make_selector_visible(
            '[id$="dataInicio:dataInicio:inputId_input"]'
        )
        frame.make_selector_visible(
            '[id$="dataFim:dataFim:inputId_input"]'
        )
        page.set_frame(frame)

        # Should not raise
        fill_evolution_dates(
            page,
            start_date_br="01/06/2024",
            end_date_br="30/06/2024",
        )

        # Locator calls should include the date inputs
        assert any(
            "dataInicio:dataInicio:inputId_input" in c
            for c in frame._locator_calls
        )
        assert any(
            "dataFim:dataFim:inputId_input" in c
            for c in frame._locator_calls
        )

    def test_select_ascending_order_when_present(self) -> None:
        """select_ascending_order selects Crescente when the selector is present."""
        from apps.ingestion.extractors.legacy_navigation import (
            select_ascending_order,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        # Make the order select visible
        frame.make_selector_visible(
            '#ordenacaoCrescente\\:ordenacaoCrescente\\:inputId_input'
        )
        page.set_frame(frame)

        # Should not raise
        select_ascending_order(page)

    def test_select_ascending_order_absent_remains_noop(self) -> None:
        """D2: when the order select is absent (count() == 0), the function
        is a non-blocking no-op (no timeout raised)."""
        from apps.ingestion.extractors.legacy_navigation import (
            select_ascending_order,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        # Do NOT make the selector visible — count() returns 0.
        page.set_frame(frame)

        # Should not raise (absence is a no-op).
        select_ascending_order(page)

    def test_select_ascending_order_present_timeout_raises_typed(self) -> None:
        """D2: when the order select IS present but a Playwright timeout
        occurs during interaction, a typed NavigationTimeoutError is raised
        (NOT swallowed as optional absence)."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
            select_ascending_order,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        # Selector IS present (visible → count() returns 1).
        frame.make_selector_visible(
            '#ordenacaoCrescente\\:ordenacaoCrescente\\:inputId_input'
        )
        page.set_frame(frame)

        original_wait_for = FakeNavigationLocator.wait_for

        def _raise_timeout(self, *, state="visible", timeout=None):
            raise PlaywrightTimeoutError("Timeout 5000ms")

        FakeNavigationLocator.wait_for = _raise_timeout  # type: ignore[method-assign]
        try:
            with pytest.raises(NavigationTimeoutError):
                select_ascending_order(page)
        finally:
            FakeNavigationLocator.wait_for = original_wait_for  # type: ignore[method-assign]

    def test_click_visualizar_report(self) -> None:
        """click_visualizar_report clicks the visualize button."""
        from apps.ingestion.extractors.legacy_navigation import (
            click_visualizar_report,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        frame.make_selector_visible(
            '#bt_UltimosQuinzedias\\:button'
        )
        page.set_frame(frame)

        click_visualizar_report(page)

        assert any(
            "bt_UltimosQuinzedias" in c
            for c in frame._locator_calls
        )

    def test_click_evolucao_wait_timeout_becomes_navigation_timeout(self) -> None:
        """D1: a real Playwright TimeoutError from the Evolução button
        wait_for becomes NavigationTimeoutError (typed), not a generic
        NavigationError."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
            click_evolucao,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        frame.make_selector_visible("role:button:Evolução")
        page.set_frame(frame)

        original_wait_for = FakeNavigationLocator.wait_for

        def _raise_timeout(self, *, state="visible", timeout=None):
            raise PlaywrightTimeoutError("Timeout 15000ms")

        FakeNavigationLocator.wait_for = _raise_timeout  # type: ignore[method-assign]
        try:
            with pytest.raises(NavigationTimeoutError):
                click_evolucao(page)
        finally:
            FakeNavigationLocator.wait_for = original_wait_for  # type: ignore[method-assign]

    def test_click_evolucao_click_timeout_becomes_navigation_timeout(self) -> None:
        """D1: a real Playwright TimeoutError from the Evolução button click
        becomes NavigationTimeoutError (typed), not a generic NavigationError."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
            click_evolucao,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        frame.make_selector_visible("role:button:Evolução")
        page.set_frame(frame)

        original_click = FakeNavigationLocator.click

        def _raise_timeout(self, *, timeout=None):
            raise PlaywrightTimeoutError("Timeout 30000ms")

        FakeNavigationLocator.click = _raise_timeout  # type: ignore[method-assign]
        try:
            with pytest.raises(NavigationTimeoutError):
                click_evolucao(page)
        finally:
            FakeNavigationLocator.click = original_click  # type: ignore[method-assign]

    def test_evolucao_button_disabled_raises(self) -> None:
        """Disabled Evolução button raises NavigationError."""
        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
            click_evolucao,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        page.set_frame(frame)
        # Do NOT make the button visible — simulate disabled/absent

        with pytest.raises(
            NavigationError,
            match="Botão Evolução não encontrado",
        ):
            click_evolucao(page)


class TestWaitForReportOrNoEvolutions:
    """Tests for wait_for_report_or_no_evolutions()."""

    def test_reports_true_when_report_page_available(self) -> None:
        """Returns True when the report page is detected."""
        from apps.ingestion.extractors.legacy_navigation import (
            wait_for_report_or_no_evolutions,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        frame.set_url(
            "https://legacy/relatorioAnaEvoInternacaoPdf.xhtml"
        )
        frame.make_selector_visible("#printLinks")
        page.set_frame(frame)

        # Simulate: has printLinks -> report available
        result = wait_for_report_or_no_evolutions(
            page, timeout_ms=5000
        )

        assert result is True

    def test_reports_false_when_no_evolutions_detected(self) -> None:
        """Returns False ONLY when an explicit no-evolutions dialog appears.

        PSW-S17 R2/R3 correction: a polling-budget expiry is a TIMEOUT
        and raises ``NavigationTimeoutError``; it must NOT be conflated
        with the genuine no-evolutions result.
        """
        from apps.ingestion.extractors.legacy_navigation import (
            SEL_NO_EVOLUTIONS_DIALOG,
            wait_for_report_or_no_evolutions,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        frame.set_url(
            "https://legacy/consultaDetalheInternacao.xhtml"
        )
        # Explicit no-evolutions dialog visible -> False (not a timeout).
        frame.make_selector_visible(SEL_NO_EVOLUTIONS_DIALOG)
        page.set_frame(frame)

        result = wait_for_report_or_no_evolutions(
            page, timeout_ms=5000
        )

        assert result is False

    def test_polling_budget_expiry_raises_typed_timeout(self) -> None:
        """Polling timeout raises NavigationTimeoutError (not False).

        PSW-S17 R2/R3: a wait timeout MUST surface as a typed timeout so
        the run records ``failure_reason=timeout``.
        """
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
            wait_for_report_or_no_evolutions,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame(html="")
        frame.set_url(
            "https://legacy/consultaDetalheInternacao.xhtml"
        )
        page.set_frame(frame)

        with pytest.raises(NavigationTimeoutError):
            wait_for_report_or_no_evolutions(
                page, timeout_ms=200
            )


class TestFullEvolutionFlowThroughBridge:
    """Tests that the bridge's extract_evolutions_via_legacy_actions works end-to-end."""

    def test_full_flow_with_handle_that_supports_evolution_actions(self) -> None:
        """Bridge extracts evolutions via legacy actions when handle supports it."""
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )

        # Build a FakePlaywrightHandle with ensure_current_page
        from tests.unit.test_real_handle_bridge import (
            FakePlaywrightHandle,
        )

        handle = FakePlaywrightHandle()

        # Create a fake page that can support the evolution navigation
        frame = FakeNavigationFrame(html="")
        # Set up eval results so the admissions table returns real rows
        frame.set_eval_result(
            "#tabelaInternacoes\\:resultList_data > tr",
            list(_ADMISSIONS_EVAL_ROWS),
        )
        # Make all required selectors visible for the evolution flow
        from apps.ingestion.extractors.legacy_navigation import (
            SEL_INTERNACOES_TABLE_ROWS,
        )
        frame.make_selector_visible(SEL_INTERNACOES_TABLE_ROWS)
        page = FakeNavigationPage()
        page.set_html(ADMISSIONS_TABLE_HTML)
        page.set_frame(frame)
        page.make_selector_visible("#prontuarioInput")
        page.make_selector_visible("role:link:Pesquisa Avançada")
        page.make_selector_visible("text:Internações")

        handle.set_html(ADMISSIONS_TABLE_HTML)
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        bridge = RealHandleBridge(handle)

        # This is the key test: the bridge does NOT crash when
        # extract_evolutions_via_legacy_actions is called.
        # With fakes, it will return [] because no real PDF is available
        # (the report download will fail). The acceptance is that the
        # method exists, accepts params, and returns a list without crashing.
        result = bridge.extract_evolutions_via_legacy_actions(
            patient_record="1234567",
            start_date="2024-01-01",
            end_date="2024-01-31",
            timeout=30,
        )

        assert isinstance(result, list)

    def test_no_overlapping_admission_raises_extraction_error(self) -> None:
        """No overlapping admission raises sanitized extraction error."""
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfError,
        )
        from apps.ingestion.extractors.real_handle_bridge import (
            RealHandleBridge,
        )
        from tests.unit.test_real_handle_bridge import (
            FakePlaywrightHandle,
        )

        handle = FakePlaywrightHandle()

        page = MagicMock()
        page.frame = MagicMock(return_value=MagicMock())
        handle.ensure_current_page = lambda: page  # type: ignore[method-assign]

        bridge = RealHandleBridge(handle)

        with pytest.raises(
            EvolutionPdfError,
            match="Nenhuma internação com interseção",
        ):
            bridge.extract_evolutions_via_legacy_actions(
                patient_record="9999999",
                start_date="2024-06-01",
                end_date="2024-06-30",
            )


class TestBridgeNavigationIntegration:
    """Tests that the adapter uses bridge navigation when available."""

    def test_adapter_uses_navigation_when_session_has_it(self) -> None:
        """Adapter detects navigate_to_admissions on session and uses it."""
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.extractors.session_controller import (
            SessionControllerConfig,
        )

        # Session that has both get_page_html and navigate_to_admissions
        session = MagicMock()
        session.is_connected.return_value = True
        session.get_tab_classes.return_value = [
            "tabs-first tabs-last tabs-selected",
        ]
        session.navigate_to_admissions = MagicMock(return_value=True)
        session.open_tab = MagicMock(return_value=False)

        # The session's get_page_html returns HTML with a valid container
        # AFTER navigate_to_admissions has been called.
        session.get_page_html.return_value = (
            '<html><body>'
            '<div id="tempoSessao"><span>00</span>:<span>29</span>:<span>01</span></div>'
            '<div id="admission-snapshot-data">'
            '[{"admissionKey":"ADM-RK-001","admissionStart":"2024-01-15",'
            '"admissionEnd":"2024-01-20","ward":"Enfermaria A","bed":"Leito 101"}'
            ']'
            '</div>'
            '</body></html>'
        )

        adapter = PersistentExtractionAdapter(
            session,
            config=SessionControllerConfig(
                base_admissions_url="/admissions/{patient_record}",
            ),
        )

        result = adapter.get_admission_snapshot(
            patient_record="1234567",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        # Open_tab should NOT have been called — navigation was used instead
        session.open_tab.assert_not_called()
        session.navigate_to_admissions.assert_called_once_with(
            patient_record="1234567"
        )

        assert isinstance(result, list)
        assert len(result) == 1

    def test_adapter_falls_back_to_url_template_without_navigation(self) -> None:
        """Without navigate_to_admissions, adapter uses URL template."""
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.extractors.session_controller import (
            SessionControllerConfig,
        )

        # Session WITHOUT navigate_to_admissions
        session = MagicMock()
        session.is_connected.return_value = True
        session.get_tab_classes.return_value = [
            "tabs-first tabs-last tabs-selected",
        ]
        # Return valid HTML with container for URL template path
        session.get_page_html.return_value = (
            '<html><body><div id="tempoSessao">'
            '<span>00</span>:<span>29</span>:<span>01</span>'
            "</div>"
            '<div id="admission-snapshot-data">'
            '[{"admissionKey":"ADM-001","admissionStart":"2024-01-15",'
            '"admissionEnd":"2024-01-20","ward":"W","bed":"B"}]'
            "</div>"
            "</body></html>"
        )
        session.open_tab.return_value = True
        # MagicMock auto-creates attributes. Use a fixed-spec session
        # so the adapter falls back to open_tab.
        class _FixedSession:
            """Session-like object that does NOT auto-create attributes."""
            is_connected = session.is_connected
            get_page_html = session.get_page_html
            get_tab_classes = session.get_tab_classes
            open_tab = session.open_tab

        session = _FixedSession()  # type: ignore[assignment]

        adapter = PersistentExtractionAdapter(
            session,
            config=SessionControllerConfig(
                base_admissions_url="/admissions/{patient_record}",
            ),
        )

        result = adapter.get_admission_snapshot(
            patient_record="1234567",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        # Open_tab should have been called (fallback path)
        session.open_tab.assert_called_once()
        assert isinstance(result, list)
        assert len(result) == 1


# ===========================================================================
# PSW-S16: Demographics navigation helpers
# ===========================================================================


class TestClickDadosDoPaciente:
    """Tests for click_dados_do_paciente()."""

    def test_clicks_dados_do_paciente_tree_label(self) -> None:
        """click_dados_do_paciente clicks the POL tree label span."""
        from apps.ingestion.extractors.legacy_navigation import (
            SEL_DADOS_DO_PACIENTE,
            click_dados_do_paciente,
        )

        page = FakeNavigationPage()
        page.make_selector_visible(SEL_DADOS_DO_PACIENTE)

        click_dados_do_paciente(page, timeout_ms=2000)

        assert SEL_DADOS_DO_PACIENTE in page.locator_calls
        # R5: the supplied timeout budget bounds the wait_for call.
        assert all(t <= 2000 for t in page.wait_timeouts)
        assert page.wait_timeouts, "click_dados must pass a bounded timeout"

    def test_raises_navigation_error_when_label_not_visible(self) -> None:
        """NavigationError raised when 'Dados do Paciente' is unavailable."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
            click_dados_do_paciente,
        )

        page = FakeNavigationPage()
        # Nothing made visible
        with pytest.raises(NavigationError):
            click_dados_do_paciente(page, timeout_ms=500)


class TestWaitForDemographicsFrame:
    """Tests for wait_for_demographics_frame() (R6: visible + identity ready)."""

    def test_returns_frame_when_cadastro_and_identity_visible(self) -> None:
        """Returns frame_pol when Cadastro tab AND prontuario input are
        visible (positive readiness, not merely attached)."""
        from apps.ingestion.extractors.legacy_navigation import (
            DEMOGRAPHIC_FIELD_SELECTORS,
            SEL_CADASTRO_TAB,
            wait_for_demographics_frame,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame()
        frame.make_selector_visible(SEL_CADASTRO_TAB)
        frame.make_selector_visible(DEMOGRAPHIC_FIELD_SELECTORS["prontuario"])
        page.set_frame(frame)

        result = wait_for_demographics_frame(page, timeout_ms=2000)
        assert result is frame

    def test_attached_cadastro_without_identity_not_accepted(self) -> None:
        """R6: Cadastro visible but prontuario input not readable must not
        yield success."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            SEL_CADASTRO_TAB,
            NavigationError,
            wait_for_demographics_frame,
        )

        page = FakeNavigationPage()
        frame = FakeNavigationFrame()
        frame.make_selector_visible(SEL_CADASTRO_TAB)
        # prontuario input NOT made visible
        page.set_frame(frame)

        with pytest.raises(NavigationError):
            wait_for_demographics_frame(page, timeout_ms=300)

    def test_raises_navigation_error_on_timeout(self) -> None:
        """NavigationError when frame_pol never appears."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
            wait_for_demographics_frame,
        )

        page = FakeNavigationPage()
        # No frame set
        with pytest.raises(NavigationError):
            wait_for_demographics_frame(page, timeout_ms=300)


class TestReadDemographicFields:
    """Tests for read_demographic_fields() (R2: fail-closed global read)."""

    _FULL_SAMPLE = {
        "prontuario": "14160147",
        "nome": "MARIA DE FATIMA SILVA",
        "nome_social": "",
        "data_nascimento": "15/03/1965",
        "sexo": "Feminino",
        "genero": "Cisgênero",
        "nome_mae": "JOSEFA SILVA",
        "nome_pai": "JOAO SILVA",
        "raca_cor": "Branca",
        "naturalidade": "Sao Paulo",
        "nacionalidade": "Brasileira",
        "estado_civil": "Casado",
        "grau_instrucao": "Ensino Medio Completo",
        "profissao": "Motorista",
        "ddd_fone_residencial": "11",
        "fone_residencial": "12345678",
        "ddd_fone_celular": "11",
        "fone_celular": "987654321",
        "ddd_fone_recado": "",
        "fone_recado": "",
        "cns": "898001234567890",
        "cpf": "12345678900",
        "logradouro": "Rua das Flores",
        "numero": "123",
        "complemento": "Apto 2",
        "bairro": "Centro",
        "cep": "01001000",
        "cidade": "Sao Paulo",
        "uf": "SP",
    }

    def test_reads_all_consumed_fields_from_frame(self) -> None:
        """read_demographic_fields returns every key consumed by
        upsert_patient_demographics with the frame's evaluated values."""
        from apps.ingestion.extractors.legacy_navigation import (
            DEMOGRAPHIC_FIELD_SELECTORS,
            read_demographic_fields,
        )

        frame = FakeNavigationFrame()
        frame.set_evaluate_result(dict(self._FULL_SAMPLE))

        result = read_demographic_fields(frame)

        assert set(result.keys()) == set(DEMOGRAPHIC_FIELD_SELECTORS.keys())
        assert result["nome"] == "MARIA DE FATIMA SILVA"
        assert result["cpf"] == "12345678900"
        assert result["data_nascimento"] == "15/03/1965"
        # Optional empty values preserved as empty strings, not dropped.
        assert result["nome_social"] == ""
        assert result["fone_recado"] == ""

    def test_missing_optional_fields_returned_as_empty_string(self) -> None:
        """R2: missing optional selectors yield "" for that field only; the
        global read still succeeds with a valid mapping."""
        from apps.ingestion.extractors.legacy_navigation import (
            DEMOGRAPHIC_FIELD_SELECTORS,
            read_demographic_fields,
        )

        frame = FakeNavigationFrame()
        # Only one field populated; the rest must default to "".
        frame.set_evaluate_result({"nome": "UNICO DADO"})

        result = read_demographic_fields(frame)

        assert set(result.keys()) == set(DEMOGRAPHIC_FIELD_SELECTORS.keys())
        assert result["nome"] == "UNICO DADO"
        assert result["cpf"] == ""
        assert result["data_nascimento"] == ""

    def test_global_evaluate_failure_raises_navigation_error(self) -> None:
        """R2: a whole-frame evaluate() failure raises NavigationError,
        never an all-empty success sentinel."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
            read_demographic_fields,
        )

        class _BrokenFrame(FakeNavigationFrame):
            def evaluate(self, expression: str, arg: Any = None) -> Any:  # noqa: ARG002
                raise RuntimeError("frame detached")

        frame = _BrokenFrame()
        with pytest.raises(NavigationError):
            read_demographic_fields(frame)

    def test_non_object_evaluate_result_raises_navigation_error(self) -> None:
        """R2: a non-mapping evaluate result raises NavigationError."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
            read_demographic_fields,
        )

        class _ListFrame(FakeNavigationFrame):
            def evaluate(self, expression: str, arg: Any = None) -> Any:  # noqa: ARG002
                return ["not", "an", "object"]

        frame = _ListFrame()
        with pytest.raises(NavigationError):
            read_demographic_fields(frame)

    def test_evaluate_playwright_timeout_raises_typed(self) -> None:
        """D13: a real Playwright TimeoutError from Frame.evaluate() must
        become a typed NavigationTimeoutError."""
        import pytest
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationTimeoutError,
            read_demographic_fields,
        )

        class _TimeoutFrame(FakeNavigationFrame):
            def evaluate(self, expression: str, arg: Any = None) -> Any:  # noqa: ARG002
                raise PlaywrightTimeoutError("Timeout 30000ms")

        frame = _TimeoutFrame()
        with pytest.raises(NavigationTimeoutError):
            read_demographic_fields(frame)

    def test_evaluate_non_timeout_failure_stays_navigation_error(self) -> None:
        """D13: a non-timeout evaluate failure stays ordinary NavigationError."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
            NavigationTimeoutError,
            read_demographic_fields,
        )

        class _BrokenFrame(FakeNavigationFrame):
            def evaluate(self, expression: str, arg: Any = None) -> Any:  # noqa: ARG002
                raise RuntimeError("frame detached")

        frame = _BrokenFrame()
        with pytest.raises(NavigationError) as exc_info:
            read_demographic_fields(frame)
        assert not isinstance(exc_info.value, NavigationTimeoutError)


class TestBuildDemographics:
    """Tests for build_demographics()."""

    def test_clicks_waits_and_reads_returning_in_memory_dict(self) -> None:
        """build_demographics performs click + wait + read and returns a dict."""
        from apps.ingestion.extractors.legacy_navigation import (
            DEMOGRAPHIC_FIELD_SELECTORS,
            SEL_CADASTRO_TAB,
            SEL_DADOS_DO_PACIENTE,
            build_demographics,
        )

        page = FakeNavigationPage()
        page.make_selector_visible(SEL_DADOS_DO_PACIENTE)
        frame = FakeNavigationFrame()
        frame.make_selector_visible(SEL_CADASTRO_TAB)
        frame.make_selector_visible(DEMOGRAPHIC_FIELD_SELECTORS["prontuario"])
        frame.set_evaluate_result(
            {"prontuario": "14160147", "nome": "PACIENTE TESTE", "cpf": ""}
        )
        page.set_frame(frame)

        result = build_demographics(page, timeout_ms=2000)

        assert isinstance(result, dict)
        assert result["nome"] == "PACIENTE TESTE"
        assert result["cpf"] == ""
        assert SEL_DADOS_DO_PACIENTE in page.locator_calls
        assert "frame_pol" in page.frame_name_calls
        # R5: every wait across the action sequence is bounded by the budget.
        assert page.wait_timeouts or frame.wait_timeouts
        assert all(t <= 2000 for t in page.wait_timeouts)
        assert all(t <= 2000 for t in frame.wait_timeouts)


# ===========================================================================
# PSW-S16 correction: identity validator (R3)
# ===========================================================================


class TestDemographicsIdentityValidator:
    """R3: one shared pure rule governs requested-vs-extracted identity."""

    def test_matching_digits_accepted(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            demographics_identity_matches,
        )

        assert demographics_identity_matches(
            requested_patient_record="14160147",
            demographics={"prontuario": "14160147"},
        )

    def test_normalization_equivalents_accepted(self) -> None:
        """Punctuation/whitespace vs digits normalize to the same record."""
        from apps.ingestion.extractors.legacy_navigation import (
            demographics_identity_matches,
        )

        assert demographics_identity_matches(
            requested_patient_record="141/60147-A",
            demographics={"prontuario": " 14160147 "},
        )

    def test_missing_prontuario_rejected(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            demographics_identity_matches,
        )

        assert not demographics_identity_matches(
            requested_patient_record="14160147", demographics={}
        )

    def test_empty_prontuario_rejected(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            demographics_identity_matches,
        )

        assert not demographics_identity_matches(
            requested_patient_record="14160147",
            demographics={"prontuario": "   "},
        )

    def test_non_string_prontuario_rejected(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            demographics_identity_matches,
        )

        assert not demographics_identity_matches(
            requested_patient_record="14160147",
            demographics={"prontuario": 14160147},  # type: ignore[dict-item]
        )

    def test_genuinely_different_record_rejected(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import (
            demographics_identity_matches,
        )

        assert not demographics_identity_matches(
            requested_patient_record="DEMO-2",
            demographics={"prontuario": "DEMO-1"},
        )


# ===========================================================================
# PSW-S16 final closure: deadline states (R1) and timeout fidelity (R2)
# ===========================================================================


class TestDeadlineHelpers:
    """R1: deadline helpers distinguish None / active / expired unambiguously.

    A real Playwright ``timeout=0`` means *disabled*, so an expired budget
    must raise rather than be passed as zero.
    """

    def test_bound_ms_returns_default_when_no_deadline(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import _bound_ms

        assert _bound_ms(None, 5000) == 5000

    def test_remaining_ms_returns_none_when_no_deadline(self) -> None:
        from apps.ingestion.extractors.legacy_navigation import _remaining_ms

        assert _remaining_ms(None) is None

    def test_expired_deadline_raises_not_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            NavigationError,
            _bound_ms,
        )

        clock = FakeClock(start=1000.0, step=0.0)
        monkeypatch.setattr("time.monotonic", clock.monotonic)
        past = 990.0  # expired (10 s ago), deterministic
        with pytest.raises(NavigationError):
            _bound_ms(past, 5000)

    def test_sub_millisecond_remainder_is_positive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.ingestion.extractors.legacy_navigation import _remaining_ms

        clock = FakeClock(start=1000.0, step=0.0)
        monkeypatch.setattr("time.monotonic", clock.monotonic)
        deadline = 1000.0 + 0.0001  # ~0.1 ms remaining, deterministic
        result = _remaining_ms(deadline)
        assert result is not None
        assert result >= 1  # never zero for an active deadline

    def test_bound_ms_active_never_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.ingestion.extractors.legacy_navigation import _bound_ms

        clock = FakeClock(start=1000.0, step=0.0)
        monkeypatch.setattr("time.monotonic", clock.monotonic)
        # A barely-active deadline must yield a strictly positive bound.
        deadline = 1000.0 + 0.0005
        assert _bound_ms(deadline, 5000) >= 1

    def test_expired_navigation_error_not_swallowed_by_fallback(self) -> None:
        """An expired deadline raises in strategy 1 before any fallback."""
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            SEL_POL_MENU,
            NavigationError,
            ensure_search_screen,
        )

        page = FakeNavigationPage()
        with pytest.raises(NavigationError):
            # timeout_ms=0 -> deadline is now -> immediately expired.
            ensure_search_screen(page, timeout_ms=0)
        # Expiry must raise in strategy 1, before the POL menu fallback.
        assert SEL_POL_MENU not in page.locator_calls

    def test_deadline_expired_message_constant_and_sanitized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pytest

        from apps.ingestion.extractors.legacy_navigation import (
            DEADLINE_EXPIRED_MESSAGE,
            NavigationError,
            _bound_ms,
        )

        clock = FakeClock(start=1000.0, step=0.0)
        monkeypatch.setattr("time.monotonic", clock.monotonic)
        with pytest.raises(NavigationError) as exc_info:
            _bound_ms(999.0, 5000)  # expired, deterministic
        message = str(exc_info.value)
        assert message == DEADLINE_EXPIRED_MESSAGE
        # No patient/selector/URL payload in the constant message.
        assert "patient" not in message.lower()
        assert "http" not in message.lower()


class TestWaitForDemographicsFrameDeadline:
    """R1: ``wait_for_demographics_frame`` recomputes the monotonic budget
    immediately before every blocking operation.

    The Cadastro wait, identity wait, polling pause, and successful return
    each independently recompute the remaining budget. If a prior operation
    consumes the budget, ``NavigationError(DEADLINE_EXPIRED_MESSAGE)`` is
    raised before the next operation starts. No operation may reuse a value
    computed before another blocking operation.
    """

    @staticmethod
    def _ready(
        monkeypatch: pytest.MonkeyPatch,
        *,
        cadastro_visible: bool = True,
        identity_visible: bool = True,
    ):
        from apps.ingestion.extractors.legacy_navigation import (
            DEMOGRAPHIC_FIELD_SELECTORS,
            SEL_CADASTRO_TAB,
            wait_for_demographics_frame,
        )

        clock = FakeClock(start=1000.0, step=0.0)
        monkeypatch.setattr("time.monotonic", clock.monotonic)

        page = FakeNavigationPage()
        frame = FakeNavigationFrame()
        page.set_frame(frame)
        if cadastro_visible:
            frame.make_selector_visible(SEL_CADASTRO_TAB)
        if identity_visible:
            frame.make_selector_visible(DEMOGRAPHIC_FIELD_SELECTORS["prontuario"])
        return (
            clock,
            page,
            frame,
            wait_for_demographics_frame,
            SEL_CADASTRO_TAB,
            DEMOGRAPHIC_FIELD_SELECTORS["prontuario"],
        )

    @staticmethod
    def _wire(page, frame, *, advance_on=None, seconds=0.0):
        """Install a shared recording hook; optionally advance the clock.

        ``advance_on`` is a selector string; whenever a fake action targets
        that selector, the shared ``FakeClock`` jumps forward by ``seconds``.
        Returns the chronological event log.
        """
        events: list[tuple[str, str, int | None]] = []

        clock_ref = {"clock": None}  # filled by caller after wiring

        def hook(action: str, selector: str, timeout: int | None) -> None:
            events.append((action, selector, timeout))
            if advance_on is not None and selector == advance_on:
                if clock_ref["clock"] is not None:
                    clock_ref["clock"].advance(seconds)

        page.set_action_hook(hook)
        frame.set_action_hook(hook)
        return events, clock_ref

    def test_cadastro_consumes_budget_identity_wait_never_started(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pytest

        from apps.ingestion.extractors.legacy_navigation import NavigationError

        clock, page, frame, fn, cad_sel, id_sel = self._ready(monkeypatch)
        events, clock_ref = self._wire(
            page, frame, advance_on=cad_sel, seconds=10.0
        )
        clock_ref["clock"] = clock

        with pytest.raises(NavigationError):
            fn(page, timeout_ms=1000)

        identity_waits = [e for e in events if e[0] == "wait" and e[1] == id_sel]
        assert identity_waits == [], (
            "identity wait must not start after Cadastro consumed the budget"
        )

    def test_identity_receives_strictly_smaller_timeout_after_cadastro(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock, page, frame, fn, cad_sel, id_sel = self._ready(monkeypatch)
        events, clock_ref = self._wire(
            page, frame, advance_on=cad_sel, seconds=0.5
        )
        clock_ref["clock"] = clock

        frame_returned = fn(page, timeout_ms=800)
        assert frame_returned is frame

        cad_t = next(t for a, s, t in events if a == "wait" and s == cad_sel)
        id_t = next(t for a, s, t in events if a == "wait" and s == id_sel)
        assert cad_t == 500
        assert id_t < cad_t, (cad_t, id_t)
        assert id_t >= 1

    def test_identity_consumes_budget_prevents_successful_return(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pytest

        from apps.ingestion.extractors.legacy_navigation import NavigationError

        clock, page, frame, fn, cad_sel, id_sel = self._ready(monkeypatch)
        events, clock_ref = self._wire(
            page, frame, advance_on=id_sel, seconds=10.0
        )
        clock_ref["clock"] = clock

        returned = {}
        with pytest.raises(NavigationError):
            returned["frame"] = fn(page, timeout_ms=1000)
        assert "frame" not in returned, (
            "frame must not be returned after identity consumed the deadline"
        )

    def test_failed_readiness_consumes_budget_pause_never_started(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pytest

        from apps.ingestion.extractors.legacy_navigation import NavigationError

        clock, page, frame, fn, cad_sel, id_sel = self._ready(
            monkeypatch, cadastro_visible=False
        )
        events, clock_ref = self._wire(
            page, frame, advance_on=cad_sel, seconds=10.0
        )
        clock_ref["clock"] = clock

        with pytest.raises(NavigationError):
            fn(page, timeout_ms=1000)

        assert page.wait_for_timeout_calls == [], (
            "polling pause must not start after a readiness wait consumed "
            "the budget"
        )

    def test_failed_readiness_partial_budget_reduces_pause_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pytest

        from apps.ingestion.extractors.legacy_navigation import NavigationError

        clock, page, frame, fn, cad_sel, id_sel = self._ready(
            monkeypatch, cadastro_visible=False
        )
        events, clock_ref = self._wire(
            page, frame, advance_on=cad_sel, seconds=0.5
        )
        clock_ref["clock"] = clock

        with pytest.raises(NavigationError):
            fn(page, timeout_ms=800)

        assert page.wait_for_timeout_calls, "polling pause must run at least once"
        first_pause = page.wait_for_timeout_calls[0]
        assert first_pause < 500, first_pause
        assert first_pause >= 1, first_pause

    def test_no_readiness_wait_or_pause_receives_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock, page, frame, fn, cad_sel, id_sel = self._ready(monkeypatch)
        events, clock_ref = self._wire(page, frame)
        clock_ref["clock"] = clock

        frame_returned = fn(page, timeout_ms=1000)
        assert frame_returned is frame

        wait_timeouts = [t for a, s, t in events if a == "wait"]
        assert wait_timeouts, "readiness waits must be recorded"
        assert all(t is not None and t >= 1 for t in wait_timeouts), wait_timeouts
        # Success path issues no polling pause.
        assert page.wait_for_timeout_calls == []
        # No wait or pause ever received zero (Playwright treats 0 as disabled).
        assert all(t != 0 for t in wait_timeouts), wait_timeouts


class TestGetByTextActionHookFidelity:
    """R4: a locator returned by ``FakeNavigationPage.get_by_text()`` must
    participate in the shared deterministic action hook, exactly like
    ``locator()`` and ``get_by_role()``.

    ``wait_for()``, ``click()``, and ``fill()`` on a text locator must emit
    chronological hook events with action, selector, and timeout.
    """

    def test_get_by_text_locator_emits_wait_click_fill_events(self) -> None:
        events: list[tuple[str, str, int | None]] = []

        page = FakeNavigationPage()
        page.set_action_hook(
            lambda action, selector, timeout: events.append(
                (action, selector, timeout)
            )
        )
        page.make_selector_visible("text:Pesquisa Avançada")

        locator = page.get_by_text("Pesquisa Avançada")
        assert locator is not None

        locator.wait_for(state="visible", timeout=1500)
        locator.click(timeout=2500)
        locator.fill("SENTINEL", timeout=3500)

        assert events == [
            ("wait", "text:Pesquisa Avançada", 1500),
            ("click", "text:Pesquisa Avançada", 2500),
            ("fill", "text:Pesquisa Avançada", 3500),
        ], events
