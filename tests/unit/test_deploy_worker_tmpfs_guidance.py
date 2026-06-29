"""Focused test for operator validation guidance in ``deploy/README.md``.

This test (Slice S2 of change
``reduce-worker-scraping-disk-writes``) verifies that the deploy docs include
concise guidance for validating the production ``worker`` volatile runtime
(tmpfs, shared memory, override variables, RAM/swap checks and rollback). It
reads the README as plain text to avoid new dependencies and checks meaningful
tokens instead of brittle full paragraphs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DEPLOY_README = Path(__file__).resolve().parents[2] / "deploy" / "README.md"


@pytest.fixture(scope="module")
def deploy_readme() -> str:
    assert DEPLOY_README.exists(), "deploy/README.md is missing"
    return DEPLOY_README.read_text(encoding="utf-8")


def _section(deploy_readme: str, start_heading: str) -> str:
    """Return the text from ``start_heading`` until the next heading of the
    same or higher level (or end of file)."""
    lines = deploy_readme.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith(start_heading.lower()):
            start = idx
            break
    assert start is not None, f"heading {start_heading!r} not found"
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    chunk: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.lstrip("#")
        if line.startswith("#") and (len(line) - len(stripped)) <= level:
            break
        chunk.append(line)
    return "\n".join(chunk)


def test_deploy_documents_worker_tmpfs(deploy_readme: str) -> None:
    """Deploy docs must explain that production worker uses tmpfs."""
    section = _section(deploy_readme, "## ")
    joined = deploy_readme.lower()
    assert "tmpfs" in joined
    assert "/tmp" in section or "/tmp" in deploy_readme


def test_deploy_documents_default_tmpfs_sizing(deploy_readme: str) -> None:
    """Docs must mention default sizing for /tmp, /var/tmp, cache and config."""
    lowered = deploy_readme.lower()
    assert "1g" in lowered or "1 g" in lowered
    assert "128m" in lowered or "128 m" in lowered
    assert "256m" in lowered or "256 m" in lowered
    assert "64m" in lowered or "64 m" in lowered


def test_deploy_documents_override_variables(deploy_readme: str) -> None:
    """Docs must list all five WORKER_* override variables."""
    assert "WORKER_SHM_SIZE" in deploy_readme
    assert "WORKER_TMPFS_TMP_SIZE" in deploy_readme
    assert "WORKER_TMPFS_VAR_TMP_SIZE" in deploy_readme
    assert "WORKER_TMPFS_CACHE_SIZE" in deploy_readme
    assert "WORKER_TMPFS_CONFIG_SIZE" in deploy_readme


def test_deploy_documents_scaling_up_to_15_workers(deploy_readme: str) -> None:
    """Docs must explain how to run up to 15 workers."""
    lowered = deploy_readme.lower()
    assert "--scale worker" in lowered
    assert "15" in deploy_readme


def test_deploy_documents_dev_shm_validation(deploy_readme: str) -> None:
    """Docs must include guidance to inspect /dev/shm."""
    lowered = deploy_readme.lower()
    assert "/dev/shm" in lowered


def test_deploy_documents_blockio_ram_and_swap_checks(deploy_readme: str) -> None:
    """Docs must include commands for Docker BlockIO, RAM and swap."""
    lowered = deploy_readme.lower()
    assert "blocki" in lowered or "block i/o" in lowered
    assert "free" in lowered
    assert "swap" in lowered


def test_deploy_documents_enospc_handling(deploy_readme: str) -> None:
    """Docs must explain what to do if /tmp fills (ENOSPC)."""
    lowered = deploy_readme.lower()
    assert "enospc" in lowered


def test_deploy_documents_chromium_shared_memory_handling(
    deploy_readme: str,
) -> None:
    """Docs must explain what to do when Chromium needs more shared memory."""
    lowered = deploy_readme.lower()
    assert "chromium" in lowered
    assert "shared memory" in lowered or "shm" in lowered


def test_deploy_documents_rollback(deploy_readme: str) -> None:
    """Docs must include high-level rollback guidance."""
    lowered = deploy_readme.lower()
    assert "rollback" in lowered


def test_deploy_warns_about_compose_config_secrets(deploy_readme: str) -> None:
    """Docs must warn against printing/committing real secrets via compose config."""
    lowered = deploy_readme.lower()
    assert "docker compose" in lowered and "config" in lowered
    assert "secret" in lowered or "credencial" in lowered or "credenciais" in lowered
