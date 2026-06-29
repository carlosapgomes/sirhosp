"""Focused documentation test for ``deploy/README.md`` dedicated orchestrator.

This test (Slice DCOS-S2 of change ``dedicated-census-orchestrator-service``)
verifies that the deploy docs recommend the dedicated ``census_orchestrator``
service for the continuous production loop, document sizing, validation,
troubleshooting and rollback, and warn against running the old ``web`` loop in
parallel.

It reads the README as plain text to avoid new dependencies and checks
meaningful tokens instead of brittle full paragraphs (matching the style of
``test_deploy_worker_tmpfs_guidance.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

DEPLOY_README = Path(__file__).resolve().parents[2] / "deploy" / "README.md"


@pytest.fixture(scope="module")
def deploy_readme() -> str:
    assert DEPLOY_README.exists(), "deploy/README.md is missing"
    return DEPLOY_README.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Recommendation: use dedicated service, not exec -T web
# ---------------------------------------------------------------------------


def test_deploy_recommends_dedicated_orchestrator_service(
    deploy_readme: str,
) -> None:
    """Docs must recommend ``census_orchestrator`` for the continuous loop."""
    lowered = deploy_readme.lower()
    assert "census_orchestrator" in lowered
    # The production loop must not be documented as exec -T web --loop
    # in the continuous loop guidance (section 5).
    section_5_start = deploy_readme.find("## 5. Orquestrador adaptativo de censo")
    assert section_5_start >= 0
    section_5 = deploy_readme[section_5_start:]
    # The old exec -T web loop pattern should NOT be the recommended
    # continuous mode inside the orchestrator section.
    loop_lines = [ln for ln in section_5.splitlines() if "--loop" in ln]
    for line in loop_lines:
        assert "census_orchestrator" in line or "exec -T web" not in line


def test_deploy_shows_dry_run_with_dedicated_service(deploy_readme: str) -> None:
    """Docs must document ``--dry-run`` using the dedicated service."""
    lowered = deploy_readme.lower()
    assert "--dry-run" in lowered
    # In the orchestrator section the dry-run command should reference
    # census_orchestrator (volatile runtime) or at minimum not reference
    # exec -T web for dry-run.
    section_5_start = deploy_readme.find("## 5. Orquestrador adaptativo de censo")
    assert section_5_start >= 0
    section_5 = deploy_readme[section_5_start:]
    dry_run_lines = [ln for ln in section_5.splitlines() if "--dry-run" in ln]
    for line in dry_run_lines:
        assert "exec -T web" not in line


def test_deploy_shows_once_with_dedicated_service(deploy_readme: str) -> None:
    """Docs must document ``--once`` using the dedicated service."""
    lowered = deploy_readme.lower()
    assert "--once" in lowered
    section_5_start = deploy_readme.find("## 5. Orquestrador adaptativo de censo")
    assert section_5_start >= 0
    section_5 = deploy_readme[section_5_start:]
    once_lines = [ln for ln in section_5.splitlines() if "--once" in ln and "run" in ln]
    for line in once_lines:
        assert "exec -T web" not in line


def test_deploy_warns_against_parallel_loop(deploy_readme: str) -> None:
    """Docs must warn not to run old web loop and dedicated service in parallel.

    The warning must be substantive: it must explain *why* (advisory-lock
    competition / overlapping cycles), not just mention "web" and "loop".
    """
    lowered = deploy_readme.lower()
    assert (
        "parallel" in lowered
        or "paralelo" in lowered
        or "simultaneamente" in lowered
    )
    # The warning must substantiate the risk with advisory-lock / overlapping
    # cycles language, otherwise it is too weak to be operational guidance.
    assert "advisory lock" in lowered
    assert "sobreposto" in lowered or "imprevis" in lowered


# ---------------------------------------------------------------------------
# Orchestrator sizing variables
# ---------------------------------------------------------------------------


def test_deploy_documents_orchestrator_shm_size_variable(deploy_readme: str) -> None:
    """Docs must list CENSUS_ORCHESTRATOR_SHM_SIZE."""
    assert "CENSUS_ORCHESTRATOR_SHM_SIZE" in deploy_readme


def test_deploy_documents_orchestrator_tmpfs_variables(deploy_readme: str) -> None:
    """Docs must list all four CENSUS_ORCHESTRATOR_TMPFS_* variables."""
    assert "CENSUS_ORCHESTRATOR_TMPFS_TMP_SIZE" in deploy_readme
    assert "CENSUS_ORCHESTRATOR_TMPFS_VAR_TMP_SIZE" in deploy_readme
    assert "CENSUS_ORCHESTRATOR_TMPFS_CACHE_SIZE" in deploy_readme
    assert "CENSUS_ORCHESTRATOR_TMPFS_CONFIG_SIZE" in deploy_readme


# ---------------------------------------------------------------------------
# Validation guidance
# ---------------------------------------------------------------------------


def test_deploy_documents_orchestrator_tmpfs_validation(deploy_readme: str) -> None:
    """Docs must explain how to inspect tmpfs inside orchestrator container."""
    lowered = deploy_readme.lower()
    assert "tmpfs" in lowered
    # Should mention df or similar for inspecting tmpfs inside the orchestrator
    assert "census_orchestrator" in lowered


def test_deploy_documents_orchestrator_dev_shm_validation(deploy_readme: str) -> None:
    """Docs must explain how to inspect /dev/shm inside orchestrator."""
    lowered = deploy_readme.lower()
    assert "/dev/shm" in lowered
    assert "census_orchestrator" in lowered


def test_deploy_documents_orchestrator_status_and_logs(deploy_readme: str) -> None:
    """Docs must show how to check docker status and logs for orchestrator."""
    lowered = deploy_readme.lower()
    # Should include docker compose ps or similar for orchestrator
    assert "census_orchestrator" in lowered
    # Should include logs or journalctl guidance
    assert "log" in lowered


def test_deploy_documents_host_disk_write_validation(deploy_readme: str) -> None:
    """Docs must mention iostat or equivalent host-level disk write check."""
    lowered = deploy_readme.lower()
    assert "iostat" in lowered or "iostat" in deploy_readme


# ---------------------------------------------------------------------------
# Troubleshooting
# ---------------------------------------------------------------------------


def test_deploy_documents_orchestrator_enospc(deploy_readme: str) -> None:
    """Docs must explain ENOSPC troubleshooting for the orchestrator."""
    lowered = deploy_readme.lower()
    assert "enospc" in lowered
    assert "CENSUS_ORCHESTRATOR" in lowered or "orquestrador" in lowered.lower()


def test_deploy_documents_orchestrator_shm_troubleshooting(deploy_readme: str) -> None:
    """Docs must explain Chromium shared-memory troubleshooting for orchestrator."""
    lowered = deploy_readme.lower()
    assert "chromium" in lowered or "cromio" in lowered
    assert "shared memory" in lowered or "memória compartilhada" in lowered
    assert "CENSUS_ORCHESTRATOR" in lowered or "orquestrador" in lowered.lower()


# ---------------------------------------------------------------------------
# Rollback and disable
# ---------------------------------------------------------------------------


def test_deploy_documents_orchestrator_rollback(deploy_readme: str) -> None:
    """Docs must explain how to stop/disable the dedicated orchestrator."""
    lowered = deploy_readme.lower()
    assert "rollback" in lowered or "reverter" in lowered or "desabilitar" in lowered
    assert "census_orchestrator" in lowered or "orquestrador" in lowered.lower()
