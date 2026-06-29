"""Characterization tests for the production ``worker`` service runtime IO
configuration in ``compose.prod.yml``.

These tests assert that the production ingestion worker uses volatile container
storage (tmpfs), a parametrizable ``shm_size``, runtime temp/cache environment
variables and bounded Docker log rotation. They read the Compose file as text
to keep the characterization dependency-free.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

COMPOSE_PROD = Path(__file__).resolve().parents[2] / "compose.prod.yml"


def _worker_block() -> str:
    """Return the YAML text for the production ``worker`` service only."""
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    match = re.search(r"^  worker:\n((?:    .*\n|\n)+)", text, re.MULTILINE)
    assert match, "worker service block not found in compose.prod.yml"
    return match.group(1)


@pytest.fixture(scope="module")
def worker_block() -> str:
    return _worker_block()


def test_worker_defines_tmpfs_for_temp_cache_and_config(worker_block: str) -> None:
    """Worker must mount /tmp, /var/tmp, /home/10001/.cache and .config as tmpfs."""
    assert "/tmp:" in worker_block
    assert "/var/tmp:" in worker_block
    assert "/home/10001/.cache:" in worker_block
    assert "/home/10001/.config:" in worker_block
    assert "tmpfs:" in worker_block


def test_worker_tmpfs_mounts_are_bounded(worker_block: str) -> None:
    """tmpfs mounts must declare an explicit size limit (conservative defaults)."""
    # Each tmpfs entry should carry a :size= token.
    for mount in (
        "/tmp:",
        "/var/tmp:",
        "/home/10001/.cache:",
        "/home/10001/.config:",
    ):
        line = _tmpfs_line(worker_block, mount)
        assert "size=" in line, f"{mount!r} tmpfs entry lacks a size bound"


def _tmpfs_line(worker_block: str, mount: str) -> str:
    pattern = re.compile(r"^\s*-\s*\"?" + re.escape(mount) + r".*$", re.MULTILINE)
    match = pattern.search(worker_block)
    assert match, f"tmpfs entry for {mount!r} not found"
    return match.group(0)


def test_worker_tmpfs_defaults_are_conservative(worker_block: str) -> None:
    """Default tmpfs sizes must match the conservatively bounded design."""
    assert "WORKER_TMPFS_TMP_SIZE:-1g" in worker_block
    assert "WORKER_TMPFS_VAR_TMP_SIZE:-128m" in worker_block
    assert "WORKER_TMPFS_CACHE_SIZE:-256m" in worker_block
    assert "WORKER_TMPFS_CONFIG_SIZE:-64m" in worker_block


def test_worker_tmpfs_uses_unprivileged_user_ownership(worker_block: str) -> None:
    """cache/config tmpfs must be owned by uid/gid 10001 with restrictive mode."""
    cache_line = _tmpfs_line(worker_block, "/home/10001/.cache:")
    config_line = _tmpfs_line(worker_block, "/home/10001/.config:")
    for line in (cache_line, config_line):
        assert "uid=10001" in line
        assert "gid=10001" in line
        assert "mode=700" in line


def test_worker_defines_parametrizable_shm_size(worker_block: str) -> None:
    """Worker must define shm_size with a WORKER_SHM_SIZE override (default 512m)."""
    assert "shm_size:" in worker_block
    assert "WORKER_SHM_SIZE:-512m" in worker_block


def test_worker_defines_temp_and_xdg_environment(worker_block: str) -> None:
    """Runtime must redirect temp dirs and XDG caches into volatile storage."""
    assert "TMPDIR=/tmp" in worker_block
    assert "TEMP=/tmp" in worker_block
    assert "TMP=/tmp" in worker_block
    assert "XDG_CACHE_HOME=/tmp/xdg-cache" in worker_block
    assert "XDG_CONFIG_HOME=/tmp/xdg-config" in worker_block


def test_worker_has_bounded_docker_log_rotation(worker_block: str) -> None:
    """Worker must use json-file driver with bounded max-size and max-file."""
    assert "logging:" in worker_block
    assert 'driver: "json-file"' in worker_block or "driver: json-file" in worker_block
    assert "max-size:" in worker_block
    assert "max-file:" in worker_block
