"""Deploy contract tests for the DSRS-S8 daily-statistics runtime and runbook.

Static text/parse assertions plus synthetic management-command calls (the
activation boundary and the non-positive finalization window are both refused
before any date is processed): the suite never invokes ``systemctl``,
``docker``, the materialization command against real data or any other
production surface. It pins:

- R1: the service runs ``materialize_daily_statistics --finalize`` exactly
  once through the hospital one-shot runtime
  (``compose.hospital.yml`` + ``--profile recovery run --rm`` on
  ``historical_recovery``), and the timer carries one documented
  ``America/Bahia`` calendar that only fires after the target local day is
  closed and the maximum D-1 recovery window of the existing units elapsed;
  the 07:30 trigger is documented as staggered from the existing :13/:47/05:00
  offsets with no guarantee of non-overlap and no cross-workflow mutual
  exclusion (the finalization itself is bounded, idempotent, atomic and
  PostgreSQL-coordinated, while the existing cadences keep their own
  coordination);
- R2: the activation boundary is declared in the hospital environment file,
  forwarded explicitly into the one-shot container, documented as required in
  ``.env.example`` and refused when undeclared, so no earlier date is ever
  reconstructed; the bounded finalization window is forwarded by reference the
  same way, with a safe unit default of 7 and no silent fallback when a
  declared value is non-positive;
- R3: the units declare user, working directory, environment, dependencies,
  failure policy and journal output like the existing units;
- R4/R5: ``deploy/README.md`` carries the install, enable, verify, observe,
  single-date rerun, disable and rollback runbook plus the activation
  preconditions for the intraday discharge, D-1 and death cadences;
- R6: the units and runbook use dates, revisions, status and counts only,
  never clinical identity, and never a mutating or extraction command.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.statistics_reports.management.commands import materialize_daily_statistics

ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_DIR = ROOT / "deploy" / "systemd"
README = ROOT / "deploy" / "README.md"
ENV_EXAMPLE = ROOT / ".env.example"
SETTINGS_SOURCE = ROOT / "config" / "settings.py"

LOOKBACK_VAR = "STATISTICS_FINALIZATION_LOOKBACK_DAYS"
LOOKBACK_UNIT_DEFAULT = "7"
ENV_FILE_LINE = "EnvironmentFile=-/srv/apps/prisma/.env"

SERVICE_NAME = "sirhosp-daily-statistics.service"
TIMER_NAME = "sirhosp-daily-statistics.timer"
ALL_UNIT_FILES = (SERVICE_NAME, TIMER_NAME)

D1_RECOVERY_TIMER = "sirhosp-historical-recovery.timer"
D1_RECOVERY_SERVICE = "sirhosp-historical-recovery.service"

CALENDAR_LITERAL = "OnCalendar=*-*-* 07:30:00 America/Bahia"
BAHIA_DAILY_CALENDAR_RE = re.compile(
    r"^OnCalendar=\*-\*-\* (\d{2}):(\d{2}):(\d{2}) America/Bahia$", re.MULTILINE
)

# The 07:30 trigger is staggered from the existing :13/:47/05:00 offsets, but
# executions are not mutually exclusive, so no S8 artifact may fall back to an
# absolute non-collision claim.
FORBIDDEN_ABSOLUTE_NON_COLLISION = (
    "não colide",
    "nao colide",
    "does not collide",
    "sem colisão",
    "sem colisao",
    "sem sobreposição",
    "sem sobreposicao",
    "não sobrepõe",
    "nao sobrepoe",
)

IDENTITY_TOKENS = (
    "paciente",
    "patient",
    "prontuario",
    "prontuário",
    "cpf",
    "obito_em",
    "saida_em",
    "select ",
    "psql",
    "--name",
    "identity",
)

MUTATING_OR_EXTRACTION_COMMANDS = (
    "extract_census",
    "extract_deaths",
    "extract_prescriptions",
    "extract_medical_evolutions",
    "sync_current_inpatients",
    "recover_historical_data",
    "run_exit_reconciliation_runtime",
    "reconcile_admission_history",
    "reconcile_stale_admissions",
    "rollback_admission_reconciliation",
    "process_discharge_pdf",
    "materialize_daily_statistics --date",
    "migrate",
    "flush",
    "dbshell",
    "loaddata",
    "dumpdata",
    "compose up",
    "compose down",
    "compose stop",
    "docker rm",
    "rm -f",
    "systemctl",
    "--loop",
)


def _unit_text(name: str) -> str:
    path = SYSTEMD_DIR / name
    assert path.exists(), f"systemd unit {name!r} must exist"
    return path.read_text(encoding="utf-8")


def _calendar_seconds(text: str) -> int:
    """Seconds-of-day of the single ``America/Bahia`` daily calendar."""
    matches = BAHIA_DAILY_CALENDAR_RE.findall(text)
    assert len(matches) == 1, "unit must declare exactly one daily Bahia calendar"
    hour, minute, second = (int(part) for part in matches[0])
    return hour * 3600 + minute * 60 + second


def _exec_start(text: str) -> str:
    """The single ``ExecStart=`` line of a unit file."""
    lines = [line for line in text.splitlines() if line.startswith("ExecStart=")]
    assert len(lines) == 1, "unit must declare exactly one ExecStart line"
    return lines[0]


def _forwarded_env_vars(text: str) -> list[str]:
    """Variable names the unit repasses to the one-shot container with ``-e``."""
    return re.findall(r"(?:^|\s)-e ([A-Z][A-Z0-9_]*)(?=\s|$)", _exec_start(text))


def _section(document: str, start_heading: str) -> str:
    """Text from ``start_heading`` until the next same-level heading.

    Lines inside fenced code blocks are never treated as headings, so
    documented shell comments do not truncate the section.
    """
    lines = document.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith(start_heading.lower()):
            start = idx
            break
    assert start is not None, f"heading {start_heading!r} not found"
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    chunk: list[str] = []
    in_fence = False
    for line in lines[start + 1 :]:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("#"):
            stripped = line.lstrip("#")
            if (len(line) - len(stripped)) <= level:
                break
        chunk.append(line)
    return "\n".join(chunk)


@pytest.fixture(scope="module")
def runbook() -> str:
    return _section(README.read_text(encoding="utf-8"), "## 5c.")


def _deploy_docs() -> dict[str, str]:
    """The S8 timer comment and runbook text that state the cadence contract."""
    return {
        TIMER_NAME: _unit_text(TIMER_NAME),
        "deploy/README.md": README.read_text(encoding="utf-8"),
    }


# ---------------------------------------------------------------------------
# R1 — scheduled command, hospital one-shot runtime and timer calendar
# ---------------------------------------------------------------------------


def test_service_runs_only_the_finalize_command_once() -> None:
    text = _unit_text(SERVICE_NAME)
    assert text.count("ExecStart=") == 1
    assert "materialize_daily_statistics --finalize" in text
    assert "--date" not in text
    assert re.findall(r"manage\.py ([a-z_]+)", text) == ["materialize_daily_statistics"]


def test_service_uses_the_hospital_oneshot_runtime() -> None:
    text = _unit_text(SERVICE_NAME)
    for marker in (
        "docker compose",
        "--env-file /srv/apps/prisma/.env",
        "-f /srv/apps/prisma/compose.hospital.yml",
        "--profile recovery",
        "run --rm",
        "historical_recovery",
        "uv run --no-sync python manage.py",
    ):
        assert marker in text, f"service must use {marker!r}"
    lowered = text.lower()
    assert "compose.prod.yml" not in lowered
    assert "/opt/sirhosp" not in lowered
    assert "process_discharge_pdf" not in lowered
    assert not re.search(r"\bweb\b", lowered)


def test_timer_declares_one_documented_bahia_calendar() -> None:
    text = _unit_text(TIMER_NAME)
    assert text.count("OnCalendar=") == 1
    assert CALENDAR_LITERAL in text
    assert "America/Bahia" in text
    assert "Persistent=true" in text
    assert "RemainAfterElapse=no" in text
    assert "RandomizedDelay" not in text
    assert "ExecStart=" not in text


def test_timer_fires_after_the_day_close_and_the_d1_recovery_window() -> None:
    """The target day must already be closed (after midnight, past the
    20:00–24:00 closing window) and the maximum D-1 recovery window derived
    from the existing units (05:00 + ``TimeoutStartSec``) must have elapsed,
    so the finalization never runs before its evidence cadence finished."""
    schedule = _calendar_seconds(_unit_text(TIMER_NAME))
    assert schedule >= 1 * 3600, "the target local day must already be closed"

    d1_start = _calendar_seconds(_unit_text(D1_RECOVERY_TIMER))
    timeout_match = re.search(
        r"TimeoutStartSec=(\d+)", _unit_text(D1_RECOVERY_SERVICE)
    )
    assert timeout_match is not None, "D-1 recovery unit must declare TimeoutStartSec"
    d1_timeout = int(timeout_match.group(1))
    assert schedule >= d1_start + d1_timeout


def test_docs_reject_the_absolute_non_collision_claim() -> None:
    """Distinct trigger instants are not a guarantee that executions cannot
    overlap, so no S8 artifact may claim 07:30 never collides with :13/:47."""
    for label, text in _deploy_docs().items():
        lowered = text.lower()
        for forbidden in FORBIDDEN_ABSOLUTE_NON_COLLISION:
            assert forbidden not in lowered, (
                f"{label} must not claim the executions cannot collide "
                f"(found {forbidden!r})"
            )


def test_docs_document_staggered_triggers_with_possible_overlap() -> None:
    """The timer comment and runbook must state the truthful contract: the
    trigger instants are staggered, executions can still overlap because the
    service timeout (``TimeoutStartSec=1800``) outlasts the gap to the next
    cadence, no ordering/conflict relationship exists, and the supported
    behavior is bounded, idempotent, atomic and PostgreSQL-coordinated while
    the existing ingestion/reconciliation cadences keep their own
    coordination."""
    for label, text in _deploy_docs().items():
        lowered = text.lower()
        for marker in (
            "escalonad",
            "sobreposi",
            "timeoutstartsec=1800",
            "não há",
            "exclusão mútua",
            "idempotent",
            "limitad",
            "atômic",
            "postgresql",
            "coordena",
        ):
            assert marker in lowered, f"{label} must document {marker!r}"


def test_docs_disclaim_cross_workflow_mutual_exclusion() -> None:
    """The docs explicitly disclaim any mutual exclusion between this
    finalization and the existing cadences; only the finalization's own
    bounded/idempotent/atomic/PostgreSQL-coordinated behavior is claimed."""
    docs = _deploy_docs()
    assert "não afirma exclusão mútua entre workflows" in docs[
        "deploy/README.md"
    ].lower()
    assert "não há relação de ordem nem de exclusão mútua" in docs[
        TIMER_NAME
    ].lower()


# ---------------------------------------------------------------------------
# R2 — required, declared activation boundary and no implicit backfill
# ---------------------------------------------------------------------------


def test_env_example_documents_the_required_activation_date() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "STATISTICS_ACTIVATION_DATE=" in text
    lowered = text.lower()
    assert "obrigat" in lowered
    assert "futura" in lowered
    assert "backfill" in lowered


def test_service_forwards_the_declared_activation_date() -> None:
    text = _unit_text(SERVICE_NAME)
    # Empty default so an undeclared boundary fails closed inside the command
    # instead of silently materializing history.
    assert "Environment=STATISTICS_ACTIVATION_DATE=" in text
    assert "EnvironmentFile=-/srv/apps/prisma/.env" in text
    # Compose starts the hospital containers with a fixed environment mapping,
    # so the boundary is repassed explicitly to the one-shot container.
    assert re.search(r"-e STATISTICS_ACTIVATION_DATE(\s|$)", text)


@override_settings(STATISTICS_ACTIVATION_DATE=None)
def test_undeclared_activation_date_fails_closed_without_materializing() -> None:
    with pytest.raises(CommandError, match="STATISTICS_ACTIVATION_DATE"):
        call_command("materialize_daily_statistics", "--finalize")


def test_service_forwards_the_configured_finalization_lookback() -> None:
    """``compose.hospital.yml`` starts the containers with a fixed environment
    mapping that does not list the DSRS variables, so a window declared in the
    hospital ``.env`` only reaches the one-shot container when the unit repasses
    it explicitly."""
    text = _unit_text(SERVICE_NAME)
    assert set(_forwarded_env_vars(text)) == {
        "STATISTICS_ACTIVATION_DATE",
        LOOKBACK_VAR,
    }
    # Repassed by reference: the value comes from the unit environment
    # (``EnvironmentFile`` included), never from a literal inline in the unit.
    assert f"-e {LOOKBACK_VAR}=" not in _exec_start(text)


def test_service_establishes_the_safe_lookback_default_of_seven() -> None:
    """An unset window must resolve to the safe default of 7 in the unit and in
    Django settings; an empty forwarded value would break the container instead
    of running the bounded batch."""
    assert f"Environment={LOOKBACK_VAR}={LOOKBACK_UNIT_DEFAULT}" in _unit_text(
        SERVICE_NAME
    )
    settings_source = SETTINGS_SOURCE.read_text(encoding="utf-8")
    assert f'os.getenv("{LOOKBACK_VAR}", "{LOOKBACK_UNIT_DEFAULT}")' in settings_source


def test_environment_file_overrides_the_lookback_default() -> None:
    """systemd applies ``EnvironmentFile`` after ``Environment``, so a window
    declared in the hospital ``.env`` overrides the unit default of 7 and, being
    repassed by reference, is the value the container and Django receive."""
    text = _unit_text(SERVICE_NAME)
    default_index = text.index(f"Environment={LOOKBACK_VAR}={LOOKBACK_UNIT_DEFAULT}")
    env_file_index = text.index(ENV_FILE_LINE)
    assert default_index < env_file_index
    assert LOOKBACK_VAR in _forwarded_env_vars(text)


@pytest.mark.parametrize("configured_days", [0, -1])
@override_settings(STATISTICS_ACTIVATION_DATE=date(2026, 10, 1))
def test_non_positive_configured_lookback_is_refused_before_processing(
    configured_days: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A non-positive window that reaches Django is refused before any date is
    inspected or materialized — it is never silently reset to 7."""
    inspected: list[str] = []

    def _must_not_run(*_args: object, **_kwargs: object) -> None:
        inspected.append("called")
        raise AssertionError("the command must refuse before inspecting any date")

    monkeypatch.setattr(
        materialize_daily_statistics, "eligible_finalization_dates", _must_not_run
    )
    monkeypatch.setattr(
        materialize_daily_statistics, "close_daily_statistics", _must_not_run
    )

    with override_settings(STATISTICS_FINALIZATION_LOOKBACK_DAYS=configured_days):
        with pytest.raises(CommandError, match=LOOKBACK_VAR):
            call_command("materialize_daily_statistics", "--finalize")

    assert inspected == []
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# R3 — declared user, directory, environment, dependencies, failure and output
# ---------------------------------------------------------------------------


def test_service_declares_the_full_runtime_contract() -> None:
    text = _unit_text(SERVICE_NAME)
    for marker in (
        "[Unit]",
        "[Service]",
        "[Install]",
        "Description=",
        "Documentation=https://github.com/carlosapgomes/sirhosp",
        "After=network-online.target docker.service",
        "Wants=network-online.target docker.service",
        "Type=oneshot",
        "User=root",
        "WorkingDirectory=/srv/apps/prisma",
        "TimeoutStartSec=",
        "StandardOutput=journal",
        "StandardError=journal",
        "SyslogIdentifier=sirhosp-daily-statistics",
        "WantedBy=multi-user.target",
    ):
        assert marker in text, f"service must declare {marker!r}"
    assert "Restart=" not in text


def test_timer_declares_documentation_and_install_target() -> None:
    text = _unit_text(TIMER_NAME)
    for marker in (
        "[Unit]",
        "[Timer]",
        "[Install]",
        "Description=",
        "Documentation=",
        "WantedBy=timers.target",
    ):
        assert marker in text, f"timer must declare {marker!r}"


def test_units_are_install_inert() -> None:
    for name in ALL_UNIT_FILES:
        text = _unit_text(name)
        assert "systemctl enable" not in text
        assert "systemctl start" not in text
        assert "enable --now" not in text


# ---------------------------------------------------------------------------
# R6/R7 — no clinical identity, no mutating command, no production execution
# ---------------------------------------------------------------------------


def test_units_never_carry_patient_identity() -> None:
    for name in ALL_UNIT_FILES:
        lowered = _unit_text(name).lower()
        for token in IDENTITY_TOKENS:
            assert token not in lowered, f"{name} must not carry {token!r}"


def test_units_never_run_an_extraction_or_destructive_command() -> None:
    for name in ALL_UNIT_FILES:
        lowered = _unit_text(name).lower()
        for token in MUTATING_OR_EXTRACTION_COMMANDS:
            assert token not in lowered, f"{name} must not reference {token!r}"


def test_contract_suite_reads_text_only() -> None:
    """R7: the validation is static/synthetic — this module imports no process
    execution primitive, so it cannot shell out to systemctl, docker or the
    materialization command against real data."""
    imported = set(globals())
    for primitive in ("subprocess", "os", "shutil", "socket"):
        assert primitive not in imported


# ---------------------------------------------------------------------------
# R4 — runbook: install, enable, verify, observe, rerun, disable, rollback
# ---------------------------------------------------------------------------


def test_runbook_documents_units_calendar_and_command(runbook: str) -> None:
    for marker in (
        SERVICE_NAME,
        TIMER_NAME,
        CALENDAR_LITERAL,
        "materialize_daily_statistics --finalize",
        "historical_recovery",
        "--profile recovery",
        "run --rm",
        "America/Bahia",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"


def test_runbook_documents_installation_as_a_disabled_baseline(runbook: str) -> None:
    for marker in (
        "install -m 0644",
        "systemctl daemon-reload",
        "NÃO habilita",
        "systemctl is-enabled",
        "disabled",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"


def test_runbook_documents_activation_requiring_the_future_date(runbook: str) -> None:
    for marker in (
        "STATISTICS_ACTIVATION_DATE",
        "obrigatória",
        "futura",
        "systemctl enable --now sirhosp-daily-statistics.timer",
        "list-timers",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"


def test_runbook_forbids_backfill_before_activation(runbook: str) -> None:
    assert "backfill" in runbook
    assert "indisponíveis" in runbook
    assert "reconstrói" in runbook


def test_runbook_documents_the_forwarded_lookback_window(runbook: str) -> None:
    for marker in (
        LOOKBACK_VAR,
        f"-e {LOOKBACK_VAR}",
        "default 7",
        "recusad",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"


def test_runbook_documents_single_date_rerun_disable_and_rollback(runbook: str) -> None:
    for marker in (
        "materialize_daily_statistics --date",
        "systemctl disable --now sirhosp-daily-statistics.timer",
        "rollback",
        "fontes clínicas",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"


# ---------------------------------------------------------------------------
# R5/R6 — cadence preconditions and identity-free observation
# ---------------------------------------------------------------------------


def test_runbook_conditions_activation_on_cadence_evidence(runbook: str) -> None:
    for marker in (
        "sirhosp-discharges.timer",
        "*:13:00 America/Bahia",
        "sirhosp-historical-recovery.timer",
        "05:00:00 America/Bahia",
        "deaths",
        "journalctl",
        "evidência",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"


def test_runbook_documents_aggregate_observation_without_identity(runbook: str) -> None:
    for marker in (
        "journalctl -u sirhosp-daily-statistics.service",
        "date=",
        "status=",
        "revision=",
        "created=",
        "identidade",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"
