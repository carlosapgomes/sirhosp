"""Production contract for the persistent-session ingestion worker service.

The service is an explicit-profile production runtime: normal Compose startup
must not activate it, while an authorized operator can start the real continuous
queue path with isolated volatile storage and sanitized worker identity.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

COMPOSE_PROD = Path(__file__).resolve().parents[2] / "compose.prod.yml"


def _persistent_worker_block() -> str:
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    match = re.search(
        r"^  persistent_worker:\n((?:    .*\n|\n)+)",
        text,
        re.MULTILINE,
    )
    assert match, "persistent_worker service block not found in compose.prod.yml"
    return match.group(1)


@pytest.fixture(scope="module")
def persistent_worker_block() -> str:
    return _persistent_worker_block()


def _tmpfs_line(block: str, mount: str) -> str:
    pattern = re.compile(r"^\s*-\s*\"?" + re.escape(mount) + r".*$", re.MULTILINE)
    match = pattern.search(block)
    assert match, f"tmpfs entry for {mount!r} not found"
    return match.group(0)


def test_persistent_worker_requires_explicit_profile(
    persistent_worker_block: str,
) -> None:
    assert 'profiles: ["persistent-worker"]' in persistent_worker_block


def test_persistent_worker_runs_closed_continuous_real_mode(
    persistent_worker_block: str,
) -> None:
    required_tokens = (
        "process_ingestion_runs_persistent_session",
        '"--loop"',
        '"--sleep-seconds"',
        '"5"',
        '"--real-handle"',
        '"--enable-real-queue"',
    )
    for token in required_tokens:
        assert token in persistent_worker_block
    assert '"--run-id"' not in persistent_worker_block
    assert '"--validation-run-id"' not in persistent_worker_block
    assert '"--max-runs"' not in persistent_worker_block


def test_persistent_worker_has_distinct_identity_and_real_access(
    persistent_worker_block: str,
) -> None:
    assert "SIRHOSP_WORKER_LABEL=persistent-worker" in persistent_worker_block
    assert "SOURCE_SYSTEM_URL=" in persistent_worker_block
    assert "SOURCE_SYSTEM_USERNAME=" in persistent_worker_block
    assert "SOURCE_SYSTEM_PASSWORD=" in persistent_worker_block
    assert "PLAYWRIGHT_PROXY_SERVER=" in persistent_worker_block
    assert "hospital_edge:" in persistent_worker_block


def test_persistent_worker_has_production_lifecycle(
    persistent_worker_block: str,
) -> None:
    assert "init: true" in persistent_worker_block
    assert "restart: unless-stopped" in persistent_worker_block
    assert "condition: service_healthy" in persistent_worker_block


def test_persistent_worker_uses_bounded_exclusive_volatile_paths(
    persistent_worker_block: str,
) -> None:
    assert "tmpfs:" in persistent_worker_block
    for mount in (
        "/tmp:",
        "/var/tmp:",
        "/home/10001/.cache:",
        "/home/10001/.config:",
    ):
        line = _tmpfs_line(persistent_worker_block, mount)
        assert "size=" in line
    assert "PERSISTENT_WORKER_TMPFS_TMP_SIZE:-1g" in persistent_worker_block
    assert "PERSISTENT_WORKER_TMPFS_VAR_TMP_SIZE:-128m" in persistent_worker_block
    assert "PERSISTENT_WORKER_TMPFS_CACHE_SIZE:-256m" in persistent_worker_block
    assert "PERSISTENT_WORKER_TMPFS_CONFIG_SIZE:-64m" in persistent_worker_block
    assert "uid=10001" in persistent_worker_block
    assert "gid=10001" in persistent_worker_block
    assert "mode=700" in persistent_worker_block


def test_persistent_worker_has_parametrizable_shared_memory(
    persistent_worker_block: str,
) -> None:
    assert "PERSISTENT_WORKER_SHM_SIZE:-512m" in persistent_worker_block


def test_persistent_worker_redirects_runtime_writes_to_tmpfs(
    persistent_worker_block: str,
) -> None:
    for value in (
        "TMPDIR=/tmp",
        "TEMP=/tmp",
        "TMP=/tmp",
        "XDG_CACHE_HOME=/tmp/xdg-cache",
        "XDG_CONFIG_HOME=/tmp/xdg-config",
    ):
        assert value in persistent_worker_block


def test_persistent_worker_has_bounded_log_rotation(
    persistent_worker_block: str,
) -> None:
    assert 'driver: "json-file"' in persistent_worker_block
    assert 'max-size: "10m"' in persistent_worker_block
    assert 'max-file: "3"' in persistent_worker_block
