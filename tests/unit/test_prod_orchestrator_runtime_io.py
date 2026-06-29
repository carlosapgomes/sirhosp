"""Characterization tests for the production ``census_orchestrator`` service
runtime IO configuration in ``compose.prod.yml`` and its systemd unit.

These tests assert that the dedicated orchestrator service uses volatile
container storage (tmpfs), a parametrizable ``shm_size``, runtime temp/cache
environment variables, bounded Docker log rotation, and that the systemd unit
manages the dedicated service instead of executing the loop inside ``web``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

COMPOSE_PROD = Path(__file__).resolve().parents[2] / "compose.prod.yml"
SYSTEMD_UNIT = (
    Path(__file__).resolve().parents[2]
    / "deploy"
    / "systemd"
    / "sirhosp-census-orchestrator.service"
)


def _orchestrator_block() -> str:
    """Return the YAML text for the production ``census_orchestrator`` service only."""
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    match = re.search(
        r"^  census_orchestrator:\n((?:    .*\n|\n)+)", text, re.MULTILINE
    )
    assert match, (
        "census_orchestrator service block not found in compose.prod.yml"
    )
    return match.group(1)


@pytest.fixture(scope="module")
def orchestrator_block() -> str:
    return _orchestrator_block()


# ---------------------------------------------------------------------------
# Profile and build
# ---------------------------------------------------------------------------


def test_orchestrator_uses_explicit_profile(orchestrator_block: str) -> None:
    """Orchestrator must be behind the ``orchestrator`` profile for explicit start."""
    assert 'profiles:' in orchestrator_block
    assert 'orchestrator' in orchestrator_block


def test_orchestrator_builds_from_prod_target(orchestrator_block: str) -> None:
    """Orchestrator must use the production image target."""
    assert "target: prod" in orchestrator_block
    assert "dockerfile: Dockerfile" in orchestrator_block


# ---------------------------------------------------------------------------
# Container name and init
# ---------------------------------------------------------------------------


def test_orchestrator_has_fixed_container_name(orchestrator_block: str) -> None:
    """Orchestrator must have a fixed container name for systemd management."""
    assert "container_name: sirhosp-census-orchestrator" in orchestrator_block


def test_orchestrator_uses_init(orchestrator_block: str) -> None:
    """Orchestrator must use init: true to reap child processes."""
    assert "init: true" in orchestrator_block


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


def test_orchestrator_runs_adaptive_census_cycle_loop(orchestrator_block: str) -> None:
    """Orchestrator command must be run_adaptive_census_cycles --loop."""
    assert "run_adaptive_census_cycles" in orchestrator_block
    assert "--loop" in orchestrator_block


# ---------------------------------------------------------------------------
# Tmpfs
# ---------------------------------------------------------------------------


def _tmpfs_line(block: str, mount: str) -> str:
    pattern = re.compile(r"^\s*-\s*\"?" + re.escape(mount) + r".*$", re.MULTILINE)
    match = pattern.search(block)
    assert match, f"tmpfs entry for {mount!r} not found"
    return match.group(0)


def test_orchestrator_defines_tmpfs_for_temp_cache_and_config(
    orchestrator_block: str,
) -> None:
    """Orchestrator must mount /tmp, /var/tmp, .cache and .config as tmpfs."""
    assert "/tmp:" in orchestrator_block
    assert "/var/tmp:" in orchestrator_block
    assert "/home/10001/.cache:" in orchestrator_block
    assert "/home/10001/.config:" in orchestrator_block
    assert "tmpfs:" in orchestrator_block


def test_orchestrator_tmpfs_mounts_are_bounded(orchestrator_block: str) -> None:
    """tmpfs mounts must declare an explicit size limit."""
    for mount in (
        "/tmp:",
        "/var/tmp:",
        "/home/10001/.cache:",
        "/home/10001/.config:",
    ):
        line = _tmpfs_line(orchestrator_block, mount)
        assert "size=" in line, f"{mount!r} tmpfs entry lacks a size bound"


def test_orchestrator_tmpfs_defaults_are_conservative(
    orchestrator_block: str,
) -> None:
    """Default tmpfs sizes must match conservatively bounded design."""
    assert "CENSUS_ORCHESTRATOR_TMPFS_TMP_SIZE:-1g" in orchestrator_block
    assert "CENSUS_ORCHESTRATOR_TMPFS_VAR_TMP_SIZE:-128m" in orchestrator_block
    assert "CENSUS_ORCHESTRATOR_TMPFS_CACHE_SIZE:-256m" in orchestrator_block
    assert "CENSUS_ORCHESTRATOR_TMPFS_CONFIG_SIZE:-64m" in orchestrator_block


def test_orchestrator_tmpfs_uses_unprivileged_user_ownership(
    orchestrator_block: str,
) -> None:
    """cache/config tmpfs must be owned by uid/gid 10001 with restrictive mode."""
    cache_line = _tmpfs_line(orchestrator_block, "/home/10001/.cache:")
    config_line = _tmpfs_line(orchestrator_block, "/home/10001/.config:")
    for line in (cache_line, config_line):
        assert "uid=10001" in line
        assert "gid=10001" in line
        assert "mode=700" in line


# ---------------------------------------------------------------------------
# Shared memory
# ---------------------------------------------------------------------------


def test_orchestrator_defines_parametrizable_shm_size(
    orchestrator_block: str,
) -> None:
    """Orchestrator must define shm_size with orchestrator-specific override."""
    assert "shm_size:" in orchestrator_block
    assert "CENSUS_ORCHESTRATOR_SHM_SIZE:-512m" in orchestrator_block


# ---------------------------------------------------------------------------
# Runtime environment variables
# ---------------------------------------------------------------------------


def test_orchestrator_defines_temp_and_xdg_environment(
    orchestrator_block: str,
) -> None:
    """Runtime must redirect temp dirs and XDG caches into volatile storage."""
    assert "TMPDIR=/tmp" in orchestrator_block
    assert "TEMP=/tmp" in orchestrator_block
    assert "TMP=/tmp" in orchestrator_block
    assert "XDG_CACHE_HOME=/tmp/xdg-cache" in orchestrator_block
    assert "XDG_CONFIG_HOME=/tmp/xdg-config" in orchestrator_block


# ---------------------------------------------------------------------------
# Bounded log rotation
# ---------------------------------------------------------------------------


def test_orchestrator_has_bounded_docker_log_rotation(
    orchestrator_block: str,
) -> None:
    """Orchestrator must use json-file driver with bounded max-size and max-file."""
    assert "logging:" in orchestrator_block
    assert (
        'driver: "json-file"' in orchestrator_block
        or "driver: json-file" in orchestrator_block
    )
    assert "max-size:" in orchestrator_block
    assert "max-file:" in orchestrator_block


# ---------------------------------------------------------------------------
# Dependencies and networking
# ---------------------------------------------------------------------------


def test_orchestrator_depends_on_db(orchestrator_block: str) -> None:
    """Orchestrator must depend on a healthy db service."""
    assert "depends_on:" in orchestrator_block
    assert "db:" in orchestrator_block
    assert "condition: service_healthy" in orchestrator_block


def test_orchestrator_joins_hospital_edge_network(orchestrator_block: str) -> None:
    """Orchestrator must connect to default and hospital_edge networks."""
    assert "networks:" in orchestrator_block
    assert "hospital_edge:" in orchestrator_block


# ---------------------------------------------------------------------------
# Restart policy
# ---------------------------------------------------------------------------


def test_orchestrator_has_restart_unless_stopped(orchestrator_block: str) -> None:
    """Orchestrator must restart unless explicitly stopped by the operator."""
    assert "restart: unless-stopped" in orchestrator_block


# ---------------------------------------------------------------------------
# Systemd unit — must manage the dedicated service, not exec into web
# ---------------------------------------------------------------------------


def _systemd_text() -> str:
    return SYSTEMD_UNIT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def systemd_text() -> str:
    return _systemd_text()


def test_systemd_unit_does_not_use_exec_web(systemd_text: str) -> None:
    """Systemd unit must not call ``docker compose exec -T web``."""
    assert "exec -T web" not in systemd_text


def test_systemd_unit_has_exec_start_for_dedicated_service(
    systemd_text: str,
) -> None:
    """ExecStart must start the dedicated census_orchestrator service."""
    assert "ExecStart=" in systemd_text
    assert "census_orchestrator" in systemd_text.split("ExecStart=")[1].split("\n")[0]


def test_systemd_unit_has_exec_stop_for_dedicated_service(
    systemd_text: str,
) -> None:
    """ExecStop must stop the dedicated census_orchestrator service."""
    assert "ExecStop=" in systemd_text
    assert "stop census_orchestrator" in systemd_text


def test_systemd_unit_uses_orchestrator_profile(systemd_text: str) -> None:
    """Systemd unit must reference the ``orchestrator`` profile."""
    assert "--profile orchestrator" in systemd_text


def test_systemd_unit_has_restart_on_failure(systemd_text: str) -> None:
    """Systemd unit must restart on failure for resilience."""
    assert "Restart=on-failure" in systemd_text
