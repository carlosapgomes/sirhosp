"""Tests for proxy configuration helper.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

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
            patch.object(ec, "aguardar_pagina_estavel"),
            patch.object(ec, "fechar_dialogos_iniciais"),
            patch.object(ec, "click_censo_icon"),
            patch.object(ec, "get_censo_frame"),
            patch.object(ec, "wait_ajax_idle"),
            patch.object(ec, "extract_setores", return_value=["test_setor"]),
            patch.object(ec, "select_setor", return_value=True),
            patch.object(ec, "clear_setor"),
            patch.object(ec, "click_pesquisar", return_value=True),
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
            patch.object(ec, "aguardar_pagina_estavel"),
            patch.object(ec, "fechar_dialogos_iniciais"),
            patch.object(ec, "click_censo_icon"),
            patch.object(ec, "get_censo_frame"),
            patch.object(ec, "wait_ajax_idle"),
            patch.object(ec, "extract_setores", return_value=["test_setor"]),
            patch.object(ec, "select_setor", return_value=True),
            patch.object(ec, "clear_setor"),
            patch.object(ec, "click_pesquisar", return_value=True),
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
