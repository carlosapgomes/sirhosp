"""Characterization tests for the production ``historical_recovery`` service
runtime IO configuration in ``compose.prod.yml``.

These tests assert that the dedicated historical recovery batch runtime uses
volatile container storage (tmpfs), a parametrizable ``shm_size``, runtime
temp/cache environment variables, bounded Docker log rotation, source-system
connectivity and a safe non-mutating default command. They read the Compose
file as text to keep the characterization dependency-free.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

COMPOSE_PROD = Path(__file__).resolve().parents[2] / "compose.prod.yml"


def _historical_recovery_block() -> str:
    """Return the YAML text for the ``historical_recovery`` service only."""
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    match = re.search(
        r"^  historical_recovery:\n((?:    .*\n|\n)+)", text, re.MULTILINE
    )
    assert match, (
        "historical_recovery service block not found in compose.prod.yml"
    )
    return match.group(1)


@pytest.fixture(scope="module")
def recovery_block() -> str:
    return _historical_recovery_block()


# ---------------------------------------------------------------------------
# Profile and build
# ---------------------------------------------------------------------------


def test_recovery_uses_explicit_profile(recovery_block: str) -> None:
    """Service must be behind the ``recovery`` profile for explicit start."""
    assert "profiles:" in recovery_block
    assert "recovery" in recovery_block


def test_recovery_builds_from_prod_target(recovery_block: str) -> None:
    """Service must use the production image target."""
    assert "target: prod" in recovery_block
    assert "dockerfile: Dockerfile" in recovery_block


# ---------------------------------------------------------------------------
# Container name and init
# ---------------------------------------------------------------------------


def test_recovery_has_fixed_container_name(recovery_block: str) -> None:
    """Service must have a fixed container name for operator recognition."""
    assert "container_name: sirhosp-historical-recovery" in recovery_block


def test_recovery_uses_init(recovery_block: str) -> None:
    """Service must use init: true to reap child processes (Playwright/Chromium)."""
    assert "init: true" in recovery_block


# ---------------------------------------------------------------------------
# Command — safe and non-mutating
# ---------------------------------------------------------------------------


def test_recovery_command_is_safe_and_non_mutating(recovery_block: str) -> None:
    """Default command must print help, not execute a real recovery."""
    assert "recover_historical_data" in recovery_block
    assert "--help" in recovery_block


def test_recovery_command_does_not_run_web_or_gunicorn(recovery_block: str) -> None:
    """Command must not reference web, Gunicorn, loops or schedulers."""
    assert "gunicorn" not in recovery_block.lower()
    assert "--loop" not in recovery_block
    assert "process_ingestion_runs" not in recovery_block
    assert "run_adaptive_census_cycles" not in recovery_block


# ---------------------------------------------------------------------------
# Tmpfs
# ---------------------------------------------------------------------------


def _tmpfs_line(block: str, mount: str) -> str:
    pattern = re.compile(r"^\s*-\s*\"?" + re.escape(mount) + r".*$", re.MULTILINE)
    match = pattern.search(block)
    assert match, f"tmpfs entry for {mount!r} not found"
    return match.group(0)


def test_recovery_defines_tmpfs_for_temp_cache_and_config(
    recovery_block: str,
) -> None:
    """Must mount /tmp, /var/tmp, .cache and .config as tmpfs."""
    assert "/tmp:" in recovery_block
    assert "/var/tmp:" in recovery_block
    assert "/home/10001/.cache:" in recovery_block
    assert "/home/10001/.config:" in recovery_block
    assert "tmpfs:" in recovery_block


def test_recovery_tmpfs_mounts_are_bounded(recovery_block: str) -> None:
    """tmpfs mounts must declare an explicit size limit."""
    for mount in (
        "/tmp:",
        "/var/tmp:",
        "/home/10001/.cache:",
        "/home/10001/.config:",
    ):
        line = _tmpfs_line(recovery_block, mount)
        assert "size=" in line, f"{mount!r} tmpfs entry lacks a size bound"


def test_recovery_tmpfs_defaults_are_independent(recovery_block: str) -> None:
    """Default tmpfs sizes must use HISTORICAL_RECOVERY_ variables."""
    assert "HISTORICAL_RECOVERY_TMPFS_TMP_SIZE:-2g" in recovery_block
    assert "HISTORICAL_RECOVERY_TMPFS_VAR_TMP_SIZE:-256m" in recovery_block
    assert "HISTORICAL_RECOVERY_TMPFS_CACHE_SIZE:-512m" in recovery_block
    assert "HISTORICAL_RECOVERY_TMPFS_CONFIG_SIZE:-128m" in recovery_block


def test_recovery_tmpfs_uses_unprivileged_user_ownership(
    recovery_block: str,
) -> None:
    """cache/config tmpfs must be owned by uid/gid 10001 with restrictive mode."""
    cache_line = _tmpfs_line(recovery_block, "/home/10001/.cache:")
    config_line = _tmpfs_line(recovery_block, "/home/10001/.config:")
    for line in (cache_line, config_line):
        assert "uid=10001" in line
        assert "gid=10001" in line
        assert "mode=700" in line


# ---------------------------------------------------------------------------
# Shared memory
# ---------------------------------------------------------------------------


def test_recovery_defines_parametrizable_shm_size(recovery_block: str) -> None:
    """Must define shm_size with HISTORICAL_RECOVERY_SHM_SIZE override (default 1g)."""
    assert "shm_size:" in recovery_block
    assert "HISTORICAL_RECOVERY_SHM_SIZE:-1g" in recovery_block


# ---------------------------------------------------------------------------
# Runtime environment variables
# ---------------------------------------------------------------------------


def test_recovery_defines_temp_and_xdg_environment(recovery_block: str) -> None:
    """Runtime must redirect temp dirs and XDG caches into volatile storage."""
    assert "TMPDIR=/tmp" in recovery_block
    assert "TEMP=/tmp" in recovery_block
    assert "TMP=/tmp" in recovery_block
    assert "XDG_CACHE_HOME=/tmp/xdg-cache" in recovery_block
    assert "XDG_CONFIG_HOME=/tmp/xdg-config" in recovery_block


def test_recovery_defines_source_system_environment(recovery_block: str) -> None:
    """Runtime must include source-system credentials and proxy variables."""
    assert "SOURCE_SYSTEM_URL=" in recovery_block
    assert "SOURCE_SYSTEM_USERNAME=" in recovery_block
    assert "SOURCE_SYSTEM_PASSWORD=" in recovery_block
    assert "PLAYWRIGHT_PROXY_SERVER=" in recovery_block


def test_recovery_defines_uv_environment(recovery_block: str) -> None:
    """Runtime must define UV_PROJECT_ENVIRONMENT, UV_CACHE_DIR and UV_NO_CACHE."""
    assert "UV_PROJECT_ENVIRONMENT=/opt/venv" in recovery_block
    assert "UV_CACHE_DIR=/opt/.uv_cache" in recovery_block
    assert "UV_NO_CACHE=1" in recovery_block


# ---------------------------------------------------------------------------
# Bounded log rotation
# ---------------------------------------------------------------------------


def test_recovery_has_bounded_docker_log_rotation(recovery_block: str) -> None:
    """Must use json-file driver with bounded max-size and max-file."""
    assert "logging:" in recovery_block
    assert (
        'driver: "json-file"' in recovery_block
        or "driver: json-file" in recovery_block
    )
    assert "max-size:" in recovery_block
    assert "max-file:" in recovery_block


# ---------------------------------------------------------------------------
# Dependencies and networking
# ---------------------------------------------------------------------------


def test_recovery_depends_on_db(recovery_block: str) -> None:
    """Must depend on a healthy db service."""
    assert "depends_on:" in recovery_block
    assert "db:" in recovery_block
    assert "condition: service_healthy" in recovery_block


def test_recovery_joins_hospital_edge_network(recovery_block: str) -> None:
    """Must connect to default and hospital_edge networks."""
    assert "networks:" in recovery_block
    assert "hospital_edge:" in recovery_block


# ---------------------------------------------------------------------------
# Restart policy — not long-running daemon style
# ---------------------------------------------------------------------------


def test_recovery_does_not_have_long_running_restart(recovery_block: str) -> None:
    """Must not use restart: unless-stopped or always (no daemon restart)."""
    assert "restart: unless-stopped" not in recovery_block
    assert "restart: always" not in recovery_block
    assert "restart: on-failure" not in recovery_block
