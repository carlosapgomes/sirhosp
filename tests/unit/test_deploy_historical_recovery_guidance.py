"""Focused test for historical recovery operator guidance in ``deploy/README.md``.

This test (Slice DHRR-S2 of change
``dedicated-historical-recovery-runtime``) verifies that the deploy docs include
concise guidance for operating the dedicated historical recovery batch runtime
(tmpfs, shared memory, dry-run, date-range, extractor selection, monitoring,
sizing, troubleshooting and rollback). It reads the README as plain text to
avoid new dependencies and checks meaningful tokens instead of brittle full
paragraphs.
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


# ---------------------------------------------------------------------------
# Purpose and batch-only nature
# ---------------------------------------------------------------------------


def test_docs_mention_historical_recovery(deploy_readme: str) -> None:
    """Docs must mention the historical_recovery runtime."""
    assert "historical_recovery" in deploy_readme


def test_docs_mention_recovery_profile(deploy_readme: str) -> None:
    """Docs must mention the recovery profile."""
    assert "--profile recovery" in deploy_readme or "recovery" in deploy_readme


def test_docs_describe_batch_only_nature(deploy_readme: str) -> None:
    """Docs must clarify that the runtime is batch-only, not a daemon."""
    lowered = deploy_readme.lower()
    assert "batch" in lowered
    assert "batch-only" in lowered or "batch only" in lowered
    assert "run --rm" in lowered


# ---------------------------------------------------------------------------
# Run commands
# ---------------------------------------------------------------------------


def test_docs_show_run_rm_command(deploy_readme: str) -> None:
    """Docs must show ``docker compose run --rm historical_recovery``."""
    lowered = deploy_readme.lower()
    assert "docker compose" in lowered
    assert "run --rm" in lowered
    assert "historical_recovery" in lowered
    assert "--profile recovery" in lowered


def test_docs_show_dry_run_example(deploy_readme: str) -> None:
    """Docs must include a ``--dry-run`` example through the dedicated runtime."""
    assert "--dry-run" in deploy_readme


def test_docs_show_single_date_example(deploy_readme: str) -> None:
    """Docs must include a ``--date`` example."""
    assert "--date" in deploy_readme


def test_docs_show_date_range_example(deploy_readme: str) -> None:
    """Docs must include ``--start-date`` and ``--end-date`` examples."""
    assert "--start-date" in deploy_readme
    assert "--end-date" in deploy_readme


# ---------------------------------------------------------------------------
# Extractor selection
# ---------------------------------------------------------------------------


def test_docs_show_single_extractor_usage(deploy_readme: str) -> None:
    """Docs must show ``--extractor`` usage for selecting one extractor."""
    assert "--extractor" in deploy_readme


def test_docs_show_multiple_extractor_usage(deploy_readme: str) -> None:
    """Docs must show that ``--extractor`` can be repeated."""
    assert "--extractor" in deploy_readme
    lowered = deploy_readme.lower()
    assert "repet" in lowered or "multiple" in lowered


def test_docs_list_valid_extractor_names(deploy_readme: str) -> None:
    """Docs must list all valid extractor names: discharges, admissions, deaths, official_census."""
    assert "discharges" in deploy_readme.lower()
    assert "admissions" in deploy_readme.lower()
    assert "deaths" in deploy_readme.lower()
    assert "official_census" in deploy_readme.lower()


def test_docs_mention_extractor_deterministic_order(deploy_readme: str) -> None:
    """Docs must mention that selected extractors run in deterministic order."""
    lowered = deploy_readme.lower()
    assert "ordem" in lowered or "deterministic" in lowered or "determinística" in lowered


# ---------------------------------------------------------------------------
# Tmpfs and /dev/shm validation
# ---------------------------------------------------------------------------


def test_docs_mention_tmpfs_validation(deploy_readme: str) -> None:
    """Docs must include commands to validate tmpfs inside the container."""
    lowered = deploy_readme.lower()
    assert "tmpfs" in lowered
    assert "df -h" in lowered


def test_docs_mention_dev_shm_validation(deploy_readme: str) -> None:
    """Docs must include guidance to inspect /dev/shm."""
    lowered = deploy_readme.lower()
    assert "/dev/shm" in lowered


# ---------------------------------------------------------------------------
# Monitoring commands
# ---------------------------------------------------------------------------


def test_docs_mention_docker_stats(deploy_readme: str) -> None:
    """Docs must mention docker stats for monitoring."""
    lowered = deploy_readme.lower()
    assert "docker stats" in lowered


def test_docs_mention_logs_access(deploy_readme: str) -> None:
    """Docs must include how to access Docker logs."""
    lowered = deploy_readme.lower()
    assert "logs" in lowered


def test_docs_mention_host_ram_check(deploy_readme: str) -> None:
    """Docs must include commands to check host RAM."""
    lowered = deploy_readme.lower()
    assert "free" in lowered
    assert "ram" in lowered or "swap" in lowered or "mem" in lowered


def test_docs_mention_host_disk_write_check(deploy_readme: str) -> None:
    """Docs must include commands like iostat to check host disk writes."""
    lowered = deploy_readme.lower()
    assert "iostat" in lowered or "disk" in lowered or "escrita" in lowered


# ---------------------------------------------------------------------------
# Sizing variables
# ---------------------------------------------------------------------------


def test_docs_list_historical_recovery_shm_size(deploy_readme: str) -> None:
    """Docs must list HISTORICAL_RECOVERY_SHM_SIZE variable."""
    assert "HISTORICAL_RECOVERY_SHM_SIZE" in deploy_readme


def test_docs_list_historical_recovery_tmpfs_variables(deploy_readme: str) -> None:
    """Docs must list all four HISTORICAL_RECOVERY_TMPFS_* variables."""
    assert "HISTORICAL_RECOVERY_TMPFS_TMP_SIZE" in deploy_readme
    assert "HISTORICAL_RECOVERY_TMPFS_VAR_TMP_SIZE" in deploy_readme
    assert "HISTORICAL_RECOVERY_TMPFS_CACHE_SIZE" in deploy_readme
    assert "HISTORICAL_RECOVERY_TMPFS_CONFIG_SIZE" in deploy_readme


def test_docs_show_default_values(deploy_readme: str) -> None:
    """Docs must show default values for HISTORICAL_RECOVERY_* variables."""
    lowered = deploy_readme.lower()
    assert "2g" in lowered
    assert "256m" in lowered
    assert "512m" in lowered
    assert "128m" in lowered
    assert "1g" in lowered


# ---------------------------------------------------------------------------
# Troubleshooting and safety
# ---------------------------------------------------------------------------


def test_docs_mention_enospc(deploy_readme: str) -> None:
    """Docs must explain what to do on tmpfs ENOSPC."""
    lowered = deploy_readme.lower()
    assert "enospc" in lowered


def test_docs_mention_chromium_shared_memory_troubleshooting(
    deploy_readme: str,
) -> None:
    """Docs must explain Chromium shared-memory troubleshooting."""
    lowered = deploy_readme.lower()
    assert "chromium" in lowered
    assert "shared" in lowered or "/dev/shm" in lowered


def test_docs_warn_against_parallel_batches(deploy_readme: str) -> None:
    """Docs must warn against running multiple heavy batches in parallel."""
    lowered = deploy_readme.lower()
    assert "paralel" in lowered or "parallel" in lowered


def test_docs_include_rollback_instructions(deploy_readme: str) -> None:
    """Docs must include rollback/fallback instructions."""
    lowered = deploy_readme.lower()
    assert "rollback" in lowered or "fallback" in lowered


def test_docs_warn_against_secrets_exposure(deploy_readme: str) -> None:
    """Docs must warn against committing or printing real secrets."""
    lowered = deploy_readme.lower()
    assert "docker compose config" in lowered or "docker compose" in lowered and "config" in lowered
    assert "secret" in lowered or "credencial" in lowered
