"""Tests for proxy configuration and census subprocess authentication."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from automation.source_system.proxy_config import get_playwright_proxy


def test_get_playwright_proxy_env_absent_returns_none() -> None:
    """When PLAYWRIGHT_PROXY_SERVER is unset, helper returns None."""
    with patch.dict(os.environ, {}, clear=True):
        result = get_playwright_proxy()
    assert result is None


def test_get_playwright_proxy_env_empty_returns_none() -> None:
    """When PLAYWRIGHT_PROXY_SERVER is empty string, helper returns None."""
    with patch.dict(os.environ, {"PLAYWRIGHT_PROXY_SERVER": ""}, clear=True):
        result = get_playwright_proxy()
    assert result is None


def test_get_playwright_proxy_env_present_returns_config() -> None:
    """When PLAYWRIGHT_PROXY_SERVER is set, helper returns proxy config dict."""
    with patch.dict(
        os.environ,
        {"PLAYWRIGHT_PROXY_SERVER": "socks5://tailscale-app:1055"},
        clear=True,
    ):
        result = get_playwright_proxy()
    assert result == {"server": "socks5://tailscale-app:1055"}


def test_extract_census_passes_proxy_to_chromium_launch(tmp_path: Path) -> None:
    """When PLAYWRIGHT_PROXY_SERVER is set, extract_census.run passes
    proxy config to chromium.launch."""
    from automation.source_system.current_inpatients import extract_census as ec

    mock_launch = MagicMock()
    mock_browser = MagicMock()
    mock_browser.new_context.return_value.new_page.return_value = MagicMock()
    mock_launch.return_value = mock_browser

    mock_pw = MagicMock()
    mock_pw.chromium.launch = mock_launch

    _fake_xlsx = tmp_path / "fake_test_setor.xlsx"
    _fake_xlsx.touch()

    try:
        with (
            patch.object(ec, "sync_playwright") as mock_sync_pw,
            patch.object(ec, "bootstrap_legacy_session"),
            patch.object(ec, "fechar_dialogos_iniciais"),
            patch.object(ec, "click_censo_icon"),
            patch.object(ec, "get_censo_frame"),
            patch.object(ec, "wait_ajax_idle"),
            patch.object(ec, "extract_setores", return_value=["test_setor"]),
            patch.object(ec, "select_setor", return_value=True),
            patch.object(ec, "clear_setor"),
            patch.object(ec, "click_pesquisar", return_value=True),
            patch.object(
                ec,
                "census_result_state",
                return_value=_census_result_state(
                    row_count=1,
                    first_row_cell_count=1,
                    content_hash=101,
                    view_state_hash=201,
                    empty_message=True,
                ),
            ),
            patch.object(
                ec,
                "wait_for_census_result_refresh",
                return_value=_census_result_state(
                    row_count=1,
                    first_row_cell_count=1,
                    content_hash=202,
                    view_state_hash=202,
                    empty_message=True,
                ),
            ),
            patch.object(ec, "get_current_setor_info", return_value={}),
            patch.object(ec, "_click_export_button"),
            patch.object(ec, "_click_xls_tudo"),
            patch.object(ec, "export_setor_xlsx", return_value=_fake_xlsx),
            patch.object(ec, "parse_setor_xlsx", return_value=[]),
            patch.object(ec, "save_results", return_value=("/tmp/fake.json", "/tmp/fake.csv")),
            patch.dict(
                os.environ,
                {"PLAYWRIGHT_PROXY_SERVER": "socks5://tailscale-app:1055"},
                clear=True,
            ),
        ):
            mock_sync_pw.return_value.__enter__.return_value = mock_pw
            ec.run(
                source_system_url="http://test-url",
                username="test-user",
                password="test-pass",
                headless=True,
                max_setores=0,
                pause_ms=100,
            )

        mock_launch.assert_called_once()
        _call_kwargs = mock_launch.call_args.kwargs
        assert "proxy" in _call_kwargs
        assert _call_kwargs["proxy"] == {"server": "socks5://tailscale-app:1055"}
        # Verify --ignore-certificate-errors is preserved
        assert "--ignore-certificate-errors" in _call_kwargs.get("args", [])
    finally:
        if _fake_xlsx.exists():
            _fake_xlsx.unlink()


def test_extract_census_does_not_pass_proxy_when_env_absent(tmp_path: Path) -> None:
    """When PLAYWRIGHT_PROXY_SERVER is not set, extract_census.run does
    NOT pass proxy config to chromium.launch."""
    from automation.source_system.current_inpatients import extract_census as ec

    mock_launch = MagicMock()
    mock_browser = MagicMock()
    mock_browser.new_context.return_value.new_page.return_value = MagicMock()
    mock_launch.return_value = mock_browser

    mock_pw = MagicMock()
    mock_pw.chromium.launch = mock_launch

    _fake_xlsx = tmp_path / "fake_test_setor.xlsx"
    _fake_xlsx.touch()

    try:
        with (
            patch.object(ec, "sync_playwright") as mock_sync_pw,
            patch.object(ec, "bootstrap_legacy_session"),
            patch.object(ec, "fechar_dialogos_iniciais"),
            patch.object(ec, "click_censo_icon"),
            patch.object(ec, "get_censo_frame"),
            patch.object(ec, "wait_ajax_idle"),
            patch.object(ec, "extract_setores", return_value=["test_setor"]),
            patch.object(ec, "select_setor", return_value=True),
            patch.object(ec, "clear_setor"),
            patch.object(ec, "click_pesquisar", return_value=True),
            patch.object(
                ec,
                "census_result_state",
                return_value=_census_result_state(
                    row_count=1,
                    first_row_cell_count=1,
                    content_hash=101,
                    view_state_hash=201,
                    empty_message=True,
                ),
            ),
            patch.object(
                ec,
                "wait_for_census_result_refresh",
                return_value=_census_result_state(
                    row_count=1,
                    first_row_cell_count=1,
                    content_hash=202,
                    view_state_hash=202,
                    empty_message=True,
                ),
            ),
            patch.object(ec, "get_current_setor_info", return_value={}),
            patch.object(ec, "_click_export_button"),
            patch.object(ec, "_click_xls_tudo"),
            patch.object(ec, "export_setor_xlsx", return_value=_fake_xlsx),
            patch.object(ec, "parse_setor_xlsx", return_value=[]),
            patch.object(ec, "save_results", return_value=("/tmp/fake.json", "/tmp/fake.csv")),
            patch.dict(os.environ, {}, clear=True),
        ):
            mock_sync_pw.return_value.__enter__.return_value = mock_pw
            ec.run(
                source_system_url="http://test-url",
                username="test-user",
                password="test-pass",
                headless=True,
                max_setores=0,
                pause_ms=100,
            )

        mock_launch.assert_called_once()
        _call_kwargs = mock_launch.call_args.kwargs
        assert "proxy" not in _call_kwargs
        # Verify --ignore-certificate-errors is still there
        assert "--ignore-certificate-errors" in _call_kwargs.get("args", [])
    finally:
        if _fake_xlsx.exists():
            _fake_xlsx.unlink()


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_AUTOMATION_ROOT = _PROJECT_ROOT / "automation" / "source_system"
_USERNAME_SELECTOR = 'input[placeholder="Nome de usuário"]'
_PASSWORD_SELECTOR = 'input[placeholder="Senha"]'


class _StopAfterAuthentication(RuntimeError):
    """Stop a census run immediately after authenticated dialog handling."""


def _load_script(relative_path: str, module_name: str) -> ModuleType:
    script_path = _AUTOMATION_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _playwright_harness() -> tuple[MagicMock, MagicMock]:
    page = MagicMock()
    page.get_by_role.side_effect = AssertionError(
        "census login must not use the button-click path"
    )

    context = MagicMock()
    context.new_page.return_value = page
    browser = MagicMock()
    browser.new_context.return_value = context
    playwright = MagicMock()
    playwright.chromium.launch.return_value = browser
    manager = MagicMock()
    manager.__enter__.return_value = playwright
    manager.__exit__.return_value = False
    return manager, page


@pytest.mark.parametrize(
    ("relative_path", "module_name", "run_kwargs", "expected_exception"),
    [
        (
            "official_census/extract_official_census.py",
            "_official_census_auth_regression",
            {
                "source_url": "https://source.invalid/login",
                "username": "synthetic-user",
                "password": "synthetic-password",
                "headless": True,
                "date_value": "01/01/2026",
                "output_dir": Path("/tmp"),
            },
            SystemExit,
        ),
        (
            "current_inpatients/extract_census.py",
            "_current_census_auth_regression",
            {
                "source_system_url": "https://source.invalid/login",
                "username": "synthetic-user",
                "password": "synthetic-password",
                "headless": True,
                "max_setores": 0,
                "pause_ms": 0,
                "csv_only": True,
            },
            _StopAfterAuthentication,
        ),
    ],
)
def test_census_run_uses_canonical_authenticated_bootstrap(
    monkeypatch,
    relative_path: str,
    module_name: str,
    run_kwargs: dict[str, object],
    expected_exception: type[BaseException],
) -> None:
    """Both census runs submit with Enter and await a valid session counter."""
    module = _load_script(relative_path, module_name)
    manager, page = _playwright_harness()
    reached_authenticated_dialogs = False

    def stop_after_authentication(_page) -> None:
        nonlocal reached_authenticated_dialogs
        reached_authenticated_dialogs = True
        raise _StopAfterAuthentication

    monkeypatch.setattr(module, "sync_playwright", lambda: manager)
    monkeypatch.setattr(
        module,
        "fechar_dialogos_iniciais",
        stop_after_authentication,
    )
    monkeypatch.setattr(module, "save_debug", lambda _page: None)

    with pytest.raises(expected_exception):
        module.run(**run_kwargs)

    assert reached_authenticated_dialogs
    page.locator.assert_any_call(_USERNAME_SELECTOR)
    page.locator.assert_any_call(_PASSWORD_SELECTOR)
    page.locator.return_value.press.assert_called_once_with("Enter")
    page.wait_for_selector.assert_called_once_with(
        "#tempoSessao",
        timeout=180_000,
    )
    readiness_expression = page.wait_for_function.call_args.args[0]
    assert "values.length >= 3" in readiness_expression
    assert "\\d+" in readiness_expression
    page.get_by_role.assert_not_called()


def test_legacy_bootstrap_import_does_not_initialize_django_apps() -> None:
    """Standalone census subprocesses can import the canonical helper."""
    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import apps.ingestion.extractors.legacy_session_bootstrap",
        ],
        cwd=_PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


def _census_result_state(
    *,
    row_count: int,
    first_row_cell_count: int,
    content_hash: int,
    view_state_hash: int,
    loading_visible: bool = False,
    empty_message: bool = False,
    has_patient_rows: bool = False,
) -> dict[str, object]:
    return {
        "tbody_exists": True,
        "row_count": row_count,
        "first_row_cell_count": first_row_cell_count,
        "content_hash": content_hash,
        "view_state_hash": view_state_hash,
        "loading_visible": loading_visible,
        "empty_message": empty_message,
        "has_patient_rows": has_patient_rows,
    }


def test_current_census_wait_ignores_stale_empty_result() -> None:
    """A stale empty row cannot decide the next sector's result."""
    from automation.source_system.current_inpatients import extract_census as ec

    stale_empty = _census_result_state(
        row_count=1,
        first_row_cell_count=1,
        content_hash=101,
        view_state_hash=201,
        empty_message=True,
    )
    loading = {
        **stale_empty,
        "loading_visible": True,
        "view_state_hash": 202,
    }
    refreshed = _census_result_state(
        row_count=32,
        first_row_cell_count=18,
        content_hash=303,
        view_state_hash=203,
        has_patient_rows=True,
    )
    frame = MagicMock()
    frame.evaluate.side_effect = [stale_empty, loading, refreshed]
    page = MagicMock()

    result = ec.wait_for_census_result_refresh(
        frame,
        page,
        stale_empty,
        timeout_ms=1_000,
        stable_ms=0,
    )

    assert result == refreshed
    assert frame.evaluate.call_count == 3
    assert page.wait_for_timeout.call_count == 2


def test_current_census_run_uses_refreshed_result_before_export(
    tmp_path: Path,
) -> None:
    """The run exports only after the post-search table state is fresh."""
    from automation.source_system.current_inpatients import extract_census as ec

    stale_empty = _census_result_state(
        row_count=1,
        first_row_cell_count=1,
        content_hash=101,
        view_state_hash=201,
        empty_message=True,
    )
    refreshed = _census_result_state(
        row_count=32,
        first_row_cell_count=18,
        content_hash=303,
        view_state_hash=203,
        has_patient_rows=True,
    )
    fake_xlsx = tmp_path / "current-census.xlsx"
    fake_xlsx.touch()
    page = MagicMock()
    context = MagicMock()
    context.new_page.return_value = page
    browser = MagicMock()
    browser.new_context.return_value = context
    playwright = MagicMock()
    playwright.chromium.launch.return_value = browser
    manager = MagicMock()
    manager.__enter__.return_value = playwright
    manager.__exit__.return_value = False
    frame = MagicMock()

    with (
        patch.object(ec, "sync_playwright", return_value=manager),
        patch.object(ec, "bootstrap_legacy_session"),
        patch.object(ec, "fechar_dialogos_iniciais"),
        patch.object(ec, "click_censo_icon"),
        patch.object(ec, "get_censo_frame", return_value=frame),
        patch.object(ec, "wait_ajax_idle"),
        patch.object(ec, "extract_setores", return_value=["synthetic-sector"]),
        patch.object(ec, "select_setor", return_value=True),
        patch.object(ec, "click_pesquisar", return_value=True),
        patch.object(ec, "census_result_state", return_value=stale_empty),
        patch.object(
            ec,
            "wait_for_census_result_refresh",
            return_value=refreshed,
        ) as wait_refresh,
        patch.object(
            ec,
            "get_current_setor_info",
            return_value={"codigo": "123", "nome": "synthetic-sector"},
        ),
        patch.object(ec, "export_setor_xlsx", return_value=fake_xlsx) as export,
        patch.object(
            ec,
            "parse_setor_xlsx",
            return_value=[
                {
                    "qrt_leito": "A-01",
                    "prontuario": "100001",
                    "nome": "PATIENT SYNTHETIC",
                }
            ],
        ),
        patch.object(
            ec,
            "save_results",
            return_value=("/tmp/fake.json", "/tmp/fake.csv"),
        ),
    ):
        ec.run(
            source_system_url="https://source.invalid/login",
            username="synthetic-user",
            password="synthetic-password",
            headless=True,
            max_setores=0,
            pause_ms=0,
        )

    wait_refresh.assert_called_once_with(
        frame,
        page,
        stale_empty,
        timeout_ms=60_000,
    )
    export.assert_called_once_with(frame, page)
