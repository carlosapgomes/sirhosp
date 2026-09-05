"""Deploy contract tests for the RPSA-S12 systemd suite and runbook.

Pure text/YAML/unit-parse assertions plus one bounded executable harness
(no Docker or systemd CLI required) pinning the exit-reconciliation
scheduling ground truth:

- three fixed Bahia-literal schedules with distinct offsets — D-1
  recovery ``05:00:00``, hourly current-day discharges ``*:13:00``,
  stale safety sweep ``*:47:00`` — all ``Persistent=true`` and with no
  ``RandomizedDelay`` anywhere;
- the bounded scheduler script ``deploy/exit-reconciliation-scheduler.sh``
  with three explicit modes, always resolving the hospital Compose under
  ``/srv/apps/prisma`` (``.env`` + ``compose.hospital.yml``) through
  ``--profile recovery run --rm historical_recovery`` and never through
  ``web``, the legacy PDF command or ``/opt/sirhosp``;
- exit-75 retry semantics at script level — a hard-coded bound of six
  TOTAL invocations with a fixed 600 s interval between attempts, then
  definitive failure — and immediate failure for any other nonzero exit
  (the bound and interval are never environment-configurable);
- the canonical extractor order asserted against the runtime dispatch
  the scheduler's ``d1-recovery`` mode constructs, not only README prose;
- six ``Type=oneshot`` units with journal output, per-unit
  ``SyslogIdentifier`` and no ``Restart=``; installation never enables
  anything;
- same-tag immutable release assets (scheduler + six units) in
  ``publish-release-image.yml``;
- ``deploy/README.md`` runbook content (activation baseline, independent
  benchmark gates, contention, RPSA-S10 monitoring options/daily command,
  authorized backfill runbook, disablement/rollback, no cron/PDF, legacy
  deprecation, RPSA-S5/S8 notes);
- the ``apps/ingestion/pipeline_health.py`` threshold comment consistent
  with the README section that documents the options.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEDULER = ROOT / "deploy" / "exit-reconciliation-scheduler.sh"
SYSTEMD_DIR = ROOT / "deploy" / "systemd"
WORKFLOW = ROOT / ".github" / "workflows" / "publish-release-image.yml"
README = ROOT / "deploy" / "README.md"
PIPELINE_HEALTH = ROOT / "apps" / "ingestion" / "pipeline_health.py"

SERVICE_FILES = [
    "sirhosp-discharges.service",
    "sirhosp-historical-recovery.service",
    "sirhosp-stale-reconciliation.service",
]
TIMER_FILES = [
    "sirhosp-discharges.timer",
    "sirhosp-historical-recovery.timer",
    "sirhosp-stale-reconciliation.timer",
]
ALL_UNIT_FILES = SERVICE_FILES + TIMER_FILES

D1_CALENDAR = "OnCalendar=*-*-* 05:00:00 America/Bahia"
HOURLY_CALENDAR = "OnCalendar=*-*-* *:13:00 America/Bahia"
STALE_CALENDAR = "OnCalendar=*-*-* *:47:00 America/Bahia"

CANONICAL_EXTRACTORS = "discharges, admissions, deaths, official_census"

SCHEDULER_MODES = {
    "sirhosp-historical-recovery.service": "d1-recovery",
    "sirhosp-discharges.service": "hourly-discharges",
    "sirhosp-stale-reconciliation.service": "stale-sweep",
}


def _unit_text(name: str) -> str:
    path = SYSTEMD_DIR / name
    assert path.exists(), f"systemd unit {name!r} must exist"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def scheduler_text() -> str:
    assert SCHEDULER.exists(), "scheduler script must exist"
    return SCHEDULER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def scheduler_executable() -> bool:
    return bool(SCHEDULER.stat().st_mode & stat.S_IXUSR)


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW.exists(), "publish workflow must exist"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme_text() -> str:
    assert README.exists(), "deploy/README.md must exist"
    return README.read_text(encoding="utf-8")


def _run_scheduler(
    mode: str,
    fake_seq: list[int],
    tmp_path: Path,
    env_overrides: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
    """Run the real scheduler with fake ``docker`` and ``sleep`` on PATH.

    The docker fake records every full Docker Compose argv and exits
    according to ``fake_seq`` (last code repeats once the sequence is
    exhausted). The sleep fake records its argv — so the fixed 600 s
    interval is asserted from captured arguments instead of bypassed —
    and returns immediately. Each call starts from clean invocation logs.
    """
    docker_log = tmp_path / "docker.log"
    sleep_log = tmp_path / "sleep.log"
    docker_log.unlink(missing_ok=True)
    sleep_log.unlink(missing_ok=True)

    docker_shim = tmp_path / "docker"
    docker_shim.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        'log = os.environ["FAKE_DOCKER_LOG"]\n'
        'codes = [int(c) for c in os.environ["FAKE_DOCKER_SEQ"].split(",")]\n'
        'line = " ".join(sys.argv[1:]) + "\\n"\n'
        "try:\n"
        "    with open(log) as f:\n"
        "        calls = sum(1 for _ in f)\n"
        "except FileNotFoundError:\n"
        "    calls = 0\n"
        "with open(log, \"a\") as f:\n"
        "    f.write(line)\n"
        "code = codes[calls] if calls < len(codes) else codes[-1]\n"
        "sys.exit(code)\n",
        encoding="utf-8",
    )
    docker_shim.chmod(docker_shim.stat().st_mode | stat.S_IXUSR)

    sleep_shim = tmp_path / "sleep"
    sleep_shim.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        'log = os.environ["FAKE_SLEEP_LOG"]\n'
        'line = " ".join(sys.argv[1:]) + "\\n"\n'
        "with open(log, \"a\") as f:\n"
        "    f.write(line)\n",
        encoding="utf-8",
    )
    sleep_shim.chmod(sleep_shim.stat().st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_DOCKER_LOG"] = str(docker_log)
    env["FAKE_DOCKER_SEQ"] = ",".join(str(code) for code in fake_seq)
    env["FAKE_SLEEP_LOG"] = str(sleep_log)
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        ["bash", str(SCHEDULER), mode],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    invocations = (
        docker_log.read_text(encoding="utf-8").splitlines()
        if docker_log.exists()
        else []
    )
    sleeps = (
        sleep_log.read_text(encoding="utf-8").splitlines()
        if sleep_log.exists()
        else []
    )
    return result, invocations, sleeps


# ---------------------------------------------------------------------------
# Scheduler script: existence, modes and hospital Compose contract
# ---------------------------------------------------------------------------


def test_scheduler_script_exists_and_is_executable(
    scheduler_executable: bool,
) -> None:
    assert scheduler_executable, "scheduler script must be executable"


def test_scheduler_script_documents_three_bounded_modes(
    scheduler_text: str,
) -> None:
    for mode in (
        "d1-recovery",
        "hourly-discharges",
        "stale-sweep",
    ):
        assert mode in scheduler_text, f"mode {mode!r} must be documented"


def test_scheduler_script_resolves_hospital_compose_runtime(
    scheduler_text: str,
) -> None:
    """Every invocation resolves the hospital runtime, never a clone or
    the domestic compose pair."""
    for marker in (
        "/srv/apps/prisma",
        ".env",
        "compose.hospital.yml",
        "historical_recovery",
        "--profile recovery",
        "run --rm",
    ):
        assert marker in scheduler_text, f"scheduler must use {marker!r}"


def test_scheduler_script_modes_map_to_runner_commands(
    scheduler_text: str,
) -> None:
    """d1-recovery and hourly-discharges dispatch the S11 runtime with the
    fixed mode flag; stale-sweep dispatches the bounded sweep command."""
    assert "RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode d1)" in scheduler_text
    assert "RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode hourly)" in scheduler_text
    assert "RUNNER_COMMAND=(reconcile_stale_admissions)" in scheduler_text


def test_scheduler_script_never_targets_web_pdf_or_opt(
    scheduler_text: str,
) -> None:
    lowered = scheduler_text.lower()
    assert "process_discharge_pdf" not in lowered
    assert "/opt/sirhosp" not in lowered
    assert "compose.prod.yml" not in lowered
    assert not re.search(r"\bweb\b", lowered)


def test_scheduler_script_retry_contract_is_fixed_and_hard_coded(
    scheduler_text: str,
) -> None:
    """Six TOTAL attempts maximum and a fixed 600 s interval, hard-coded
    at script level — never shrinkable or stretchable via environment."""
    assert "MAX_TOTAL_ATTEMPTS=6" in scheduler_text
    assert "RETRY_SLEEP_SECONDS=600" in scheduler_text
    for env_var in (
        "EXIT_RECON_MAX_RETRIES",
        "EXIT_RECON_RETRY_SLEEP_SECONDS",
    ):
        assert env_var not in scheduler_text


def test_scheduler_rejects_unknown_mode_without_running(
    tmp_path: Path,
) -> None:
    result, invocations, sleeps = _run_scheduler(
        "unsupported-mode", [0], tmp_path
    )
    assert result.returncode == 2
    assert invocations == []
    assert sleeps == []
    assert "Usage:" in result.stderr


# ---------------------------------------------------------------------------
# Scheduler script: executable exit-code matrix (75 vs any other exit)
# ---------------------------------------------------------------------------


def test_scheduler_75_is_bounded_to_six_total_invocations_then_fails(
    tmp_path: Path,
) -> None:
    """A persistent code-75 contention is bounded at SIX total
    invocations (initial attempt plus five retries, each 600 s apart) and
    then exits 75 definitively; the loop cannot exceed the bound."""
    seq = [75] * 20
    result, invocations, sleeps = _run_scheduler("d1-recovery", seq, tmp_path)
    assert result.returncode == 75
    assert len(invocations) == 6
    assert sleeps == ["600"] * 5
    for argv in invocations:
        assert "run_exit_reconciliation_runtime --mode d1" in argv
        assert "--profile recovery run --rm historical_recovery" in argv


def test_scheduler_75_is_retried_then_succeeds(tmp_path: Path) -> None:
    """Success on a later attempt exits 0 after exactly one 600 s
    interval (captured from the sleep stub, never zeroed)."""
    result, invocations, sleeps = _run_scheduler(
        "hourly-discharges", [75, 0], tmp_path
    )
    assert result.returncode == 0
    assert len(invocations) == 2
    assert sleeps == ["600"]
    assert "run_exit_reconciliation_runtime --mode hourly" in invocations[0]


def test_scheduler_success_on_first_attempt_exits_zero(
    tmp_path: Path,
) -> None:
    for mode in ("d1-recovery", "hourly-discharges", "stale-sweep"):
        result, invocations, sleeps = _run_scheduler(mode, [0], tmp_path)
        assert result.returncode == 0
        assert len(invocations) == 1
        assert sleeps == []


def test_scheduler_immediate_nonzero_exit_is_not_retried(
    tmp_path: Path,
) -> None:
    """Any nonzero exit other than 75 fails immediately: exactly ONE
    invocation, with the exit code propagated."""
    for code in (1, 3, 70, 76):
        result, invocations, sleeps = _run_scheduler(
            "d1-recovery", [code], tmp_path
        )
        assert result.returncode == code
        assert len(invocations) == 1
        assert sleeps == []


def test_scheduler_non_75_after_75_is_immediate(tmp_path: Path) -> None:
    """Once a non-75 failure appears the scheduler stops retrying."""
    result, invocations, sleeps = _run_scheduler(
        "d1-recovery", [75, 3], tmp_path
    )
    assert result.returncode == 3
    assert len(invocations) == 2
    assert sleeps == ["600"]


def test_scheduler_retry_contract_is_not_environment_configurable(
    tmp_path: Path,
) -> None:
    """Leaked EXIT_RECON_* variables must not change the fixed contract:
    a persistent 75 still stops at six total invocations with 600 s
    sleeps, and any other nonzero still fails immediately."""
    overrides = {
        "EXIT_RECON_MAX_RETRIES": "1",
        "EXIT_RECON_RETRY_SLEEP_SECONDS": "1",
    }
    result, invocations, sleeps = _run_scheduler(
        "d1-recovery", [75] * 20, tmp_path, env_overrides=overrides
    )
    assert result.returncode == 75
    assert len(invocations) == 6
    assert sleeps == ["600"] * 5
    result, invocations, sleeps = _run_scheduler(
        "d1-recovery", [7], tmp_path, env_overrides=overrides
    )
    assert result.returncode == 7
    assert len(invocations) == 1
    assert sleeps == []


def test_scheduler_stale_sweep_dispatches_sweep_command(
    tmp_path: Path,
) -> None:
    result, invocations, sleeps = _run_scheduler("stale-sweep", [0], tmp_path)
    assert result.returncode == 0
    assert len(invocations) == 1
    assert sleeps == []
    assert "reconcile_stale_admissions" in invocations[0]
    assert "process_discharge_pdf" not in invocations[0]
    assert "--profile recovery run --rm historical_recovery" in invocations[0]


def test_scheduler_d1_recovery_dispatches_canonical_extractor_order(
    tmp_path: Path,
) -> None:
    """The canonical extractor order is pinned at the runtime dispatch:
    the d1-recovery mode constructs the S11 runtime ``--mode d1``
    command, and the runtime resolves that mode to the canonical
    ``DEFAULT_EXTRACTOR_ORDER`` (discharges, admissions, deaths,
    official_census) — not merely README prose."""
    from apps.ingestion.historical_recovery import DEFAULT_EXTRACTOR_ORDER
    from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
        _CANONICAL_EXTRACTORS,
        MODE_D1,
    )

    assert MODE_D1 == "d1"
    assert _CANONICAL_EXTRACTORS == DEFAULT_EXTRACTOR_ORDER
    assert DEFAULT_EXTRACTOR_ORDER == [
        "discharges",
        "admissions",
        "deaths",
        "official_census",
    ]
    assert ", ".join(DEFAULT_EXTRACTOR_ORDER) == CANONICAL_EXTRACTORS

    result, invocations, sleeps = _run_scheduler("d1-recovery", [0], tmp_path)
    assert result.returncode == 0
    assert len(invocations) == 1
    assert sleeps == []
    assert (
        "python manage.py run_exit_reconciliation_runtime --mode d1"
        in invocations[0]
    )


# ---------------------------------------------------------------------------
# Timers: Bahia-literal calendars, distinct offsets, Persistent, no delay
# ---------------------------------------------------------------------------


def test_d1_timer_runs_0500_bahia_persistent() -> None:
    text = _unit_text("sirhosp-historical-recovery.timer")
    assert text.count("OnCalendar=") == 1
    assert D1_CALENDAR in text
    assert "Persistent=true" in text


def test_discharge_timer_runs_hourly_at_minute_13_bahia() -> None:
    text = _unit_text("sirhosp-discharges.timer")
    assert text.count("OnCalendar=") == 1
    assert HOURLY_CALENDAR in text
    assert "Persistent=true" in text


def test_stale_timer_runs_hourly_at_minute_47_bahia() -> None:
    text = _unit_text("sirhosp-stale-reconciliation.timer")
    assert text.count("OnCalendar=") == 1
    assert STALE_CALENDAR in text
    assert "Persistent=true" in text


def test_timers_have_three_distinct_offsets_and_no_randomized_delay() -> None:
    for name in TIMER_FILES:
        text = _unit_text(name)
        assert "RandomizedDelay" not in text
        assert text.count("OnCalendar=") == 1
        assert "Persistent=true" in text
    # The three literal calendars are pairwise distinct (fixed offsets).
    assert len({_unit_text(name) for name in TIMER_FILES}) == 3
    assert D1_CALENDAR in _unit_text("sirhosp-historical-recovery.timer")
    assert HOURLY_CALENDAR in _unit_text("sirhosp-discharges.timer")
    assert STALE_CALENDAR in _unit_text("sirhosp-stale-reconciliation.timer")


def test_timers_never_start_services_directly() -> None:
    for name in TIMER_FILES:
        text = _unit_text(name)
        assert "ExecStart=" not in text
        assert "[Install]" in text
        assert "WantedBy=timers.target" in text


# ---------------------------------------------------------------------------
# Services: oneshot, journal output, SyslogIdentifier, no Restart=
# ---------------------------------------------------------------------------


def test_services_are_oneshot_journal_without_restart() -> None:
    for name in SERVICE_FILES:
        text = _unit_text(name)
        assert "Type=oneshot" in text
        assert "StandardOutput=journal" in text
        assert "StandardError=journal" in text
        assert "SyslogIdentifier=" in text
        assert "Restart=" not in text


def test_service_syslog_identifiers_are_unique_per_unit() -> None:
    def _syslog_identifier(name: str) -> str:
        text = _unit_text(name)
        return text.split("SyslogIdentifier=")[1].splitlines()[0].strip()

    identifiers = [_syslog_identifier(name) for name in SERVICE_FILES]
    assert len(set(identifiers)) == 3
    for name, identifier in zip(SERVICE_FILES, identifiers, strict=True):
        assert identifier == Path(name).stem


def test_services_call_scheduler_with_matching_modes() -> None:
    for name, mode in SCHEDULER_MODES.items():
        text = _unit_text(name)
        assert "Type=oneshot" in text
        assert (
            f"ExecStart=/srv/apps/prisma/deploy/exit-reconciliation-scheduler.sh {mode}"
            in text
        )
        assert "WorkingDirectory=/srv/apps/prisma" in text


def test_units_never_use_web_pdf_or_legacy_opt_paths() -> None:
    for name in ALL_UNIT_FILES:
        lowered = _unit_text(name).lower()
        assert "process_discharge_pdf" not in lowered
        assert "/opt/sirhosp" not in lowered
        assert "compose.prod.yml" not in lowered
        assert not re.search(r"\bweb\b", lowered)


def test_unit_files_are_install_inert() -> None:
    """Copying the units must never enable or start a schedule; only
    explicit operator ``systemctl enable`` does (documented in README)."""
    for name in ALL_UNIT_FILES:
        text = _unit_text(name)
        assert "systemctl enable" not in text
        assert "systemctl start" not in text
        assert "enable --now" not in text


# ---------------------------------------------------------------------------
# Release workflow: scheduler + six units as same-tag immutable assets
# ---------------------------------------------------------------------------


def test_workflow_release_assets_include_scheduler_and_six_units(
    workflow_text: str,
) -> None:
    """The immutable release command must attach the compose file, the
    per-tag runbook, the scheduler script and all six unit files."""
    normalized = " ".join(workflow_text.split())
    create_at = normalized.find(
        'gh release create "$RELEASE_TAG" compose.hospital.yml '
        '"${UPGRADE_ASSET}"'
    )
    assert create_at >= 0
    create_statement = normalized[create_at : create_at + 400]
    positions = [
        create_statement.find("${UPGRADE_ASSET}"),
        create_statement.find("${SCHEDULER_ASSET}"),
        create_statement.find("${SYSTEMD_ASSETS[@]}"),
        create_statement.find("${release_args[@]}"),
    ]
    assert all(position >= 0 for position in positions)
    assert positions == sorted(positions)
    for asset in [
        "deploy/exit-reconciliation-scheduler.sh",
        "deploy/systemd/sirhosp-discharges.service",
        "deploy/systemd/sirhosp-discharges.timer",
        "deploy/systemd/sirhosp-historical-recovery.service",
        "deploy/systemd/sirhosp-historical-recovery.timer",
        "deploy/systemd/sirhosp-stale-reconciliation.service",
        "deploy/systemd/sirhosp-stale-reconciliation.timer",
    ]:
        assert asset in workflow_text, f"release must carry {asset!r}"


def test_workflow_validates_assets_before_release_creation(
    workflow_text: str,
) -> None:
    normalized = " ".join(workflow_text.split())
    assert 'test -f "${UPGRADE_ASSET}"' in workflow_text
    assert 'test -f "${SCHEDULER_ASSET}"' in workflow_text
    assert "for asset in \"${SYSTEMD_ASSETS[@]}\"" in workflow_text
    create_pos = normalized.find("gh release create")
    assert create_pos >= 0
    # Asset existence checks must precede the create call.
    assert normalized.find('test -f "${SCHEDULER_ASSET}"') < create_pos


def test_release_assets_exist_in_the_repository() -> None:
    assert SCHEDULER.exists()
    for name in ALL_UNIT_FILES:
        assert (SYSTEMD_DIR / name).exists()


# ---------------------------------------------------------------------------
# deploy/README.md: activation baseline and schedules
# ---------------------------------------------------------------------------


def test_readme_documents_the_three_bahia_schedules(readme_text: str) -> None:
    for calendar in (D1_CALENDAR, HOURLY_CALENDAR, STALE_CALENDAR):
        assert calendar in readme_text
    assert readme_text.count("America/Bahia") >= 3
    assert "Persistent=true" in readme_text


def test_readme_activation_baseline_disabled_and_d1_smoke(
    readme_text: str,
) -> None:
    """Timers are installed disabled-by-default; a manual all-extractor D-1
    smoke test precedes enablement."""
    lowered = readme_text.lower()
    for marker in ("desabilitado", "disabled"):
        if marker in lowered:
            break
    else:
        pytest.fail("readme must state timers are disabled by default")
    assert "smoke test" in lowered or "smoke-test" in lowered
    assert "enable" in lowered or "habilitar" in lowered


def test_readme_benchmark_gates_are_independent(readme_text: str) -> None:
    """Hourly approval and seven-date catch-up approval are independent;
    catch-up automation exists only after its own benchmark approval."""
    lowered = readme_text.lower()
    assert "independent" in lowered
    assert "catch-up" in lowered or "catchup" in lowered
    assert "hourly" in lowered or "hora" in lowered
    # Automatic planning stays D-1 until catch-up approval.
    d1_only = (
        "d-1" in lowered
        or "05:00" in readme_text
        or "5b" in lowered
    )
    assert d1_only


def test_readme_documents_calibration_and_queue_caveat(
    readme_text: str,
) -> None:
    lowered = readme_text.lower()
    assert "calibra" in lowered
    assert "pico" in lowered or "peak" in lowered or "residual" in lowered


def test_readme_documents_contention_semantics(readme_text: str) -> None:
    """Exit 75, the six-retry/600 s bound, and the queue/open-batch and
    advisory-lock guards are documented."""
    lowered = readme_text.lower()
    assert "75" in readme_text
    assert "600" in readme_text
    assert "6" in readme_text
    assert "fila" in lowered or "queue" in lowered
    assert "batch" in lowered
    assert "advisory lock" in lowered or "lock" in lowered


def test_readme_documents_s10_options_and_daily_integrity_command(
    readme_text: str,
) -> None:
    """The RPSA-S10 doc gap: the four reconciliation options/defaults and
    the daily integrity command live in the deploy README (section 6.1)."""
    assert "### 6.1 Health check" in readme_text
    for option in (
        "--missing-dates-max",
        "--backlog-age-max-hours",
        "--conflict-max-count",
        "--duplicate-max-count",
    ):
        assert option in readme_text
    assert "report_admission_reconciliation_integrity" in readme_text


def test_readme_documents_authorized_backfill_runbook(
    readme_text: str,
) -> None:
    """RPSA-S9 authorized apply: backup reference, label, canary 50 then
    max 100, duplicate-cohort gating, rollback asymmetry and caps."""
    assert "## 5b." in readme_text
    lowered = readme_text.lower()
    for marker in ("--backup-ref", "--label", "50", "100"):
        assert marker in readme_text or marker in lowered
    assert "dry-run" in lowered
    assert "rollback" in lowered
    assert "duplicate" in lowered or "duplicat" in lowered
    assert "canary" in lowered or "canário" in lowered


def test_readme_documents_disablement_rollback_no_cron_no_pdf(
    readme_text: str,
) -> None:
    lowered = readme_text.lower()
    for marker in ("systemctl disable", "rollback"):
        assert marker in lowered
    # Cron must never duplicate a schedule; the PDF command is never scheduled.
    assert "cron" in lowered
    assert "process_discharge_pdf" in readme_text
    assert "nunca" in lowered or "never" in lowered


def test_readme_marks_legacy_discharges_scheduler_deprecated(
    readme_text: str,
) -> None:
    lowered = readme_text.lower()
    assert "deprecat" in lowered or "legado" in lowered
    assert "discharges-scheduler.sh" in readme_text or "3x" in readme_text


def test_readme_notes_sweep_orchestrator_window_and_summary_axis(
    readme_text: str,
) -> None:
    """RPSA-S5 sweep-vs-orchestrator window and RPSA-S8 summary-series
    axis notes are documented."""
    lowered = readme_text.lower()
    assert "sweep" in lowered or "varredura" in lowered
    assert "orchestrator" in lowered or "orquestrador" in lowered
    assert "série" in lowered or "serie" in lowered or "series" in lowered
    assert "aggregate" in lowered or "agregad" in lowered


def test_canonical_extractor_order_appears_once_in_deploy_tree() -> None:
    """The four extractors in canonical order are named exactly once under
    deploy/ (README), keeping one spelling for the runtime contract."""
    candidates = [README] + [SYSTEMD_DIR / name for name in ALL_UNIT_FILES]
    candidates.append(SCHEDULER)
    occurrences = sum(
        text.count(CANONICAL_EXTRACTORS)
        for path in candidates
        if path.exists()
        for text in [path.read_text(encoding="utf-8")]
    )
    assert occurrences == 1
    assert CANONICAL_EXTRACTORS in README.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# pipeline_health.py comment consistency (authorized comment-only fix)
# ---------------------------------------------------------------------------


def test_pipeline_health_comment_is_consistent_with_readme_section() -> None:
    """The threshold comment may only claim README documentation that the
    README section actually provides (section 6.1 documents the four RPSA-S10
    options and the daily command)."""
    source = PIPELINE_HEALTH.read_text(encoding="utf-8")
    comment_block = source.split("DEFAULT_MISSING_DATES_MAX = 7")[0]
    assert "deploy/README.md" in comment_block
    assert "section 6.1" in comment_block or "seção 6.1" in comment_block
    readme = README.read_text(encoding="utf-8")
    for option in (
        "--missing-dates-max",
        "--backlog-age-max-hours",
        "--conflict-max-count",
        "--duplicate-max-count",
    ):
        assert option in readme
    assert "report_admission_reconciliation_integrity" in readme
