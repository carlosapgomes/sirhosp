"""Deploy contract tests for the OASF-S4 adaptive statistics handoff.

Static text/parse assertions plus synthetic management-command calls (the
activation boundary and the non-positive finalization window are both refused
before any date is processed): the suite never invokes ``systemctl``,
``docker``, the materialization command against real data or any other
production surface. It pins:

- R1: ``sirhosp-discharges.timer``, ``sirhosp-historical-recovery.timer``,
  ``sirhosp-daily-statistics.timer`` and
  ``sirhosp-daily-statistics.service`` declare themselves an inert manual
  fallback owned by the adaptive census orchestrator, never the normal
  schedule, and never instruct enabling or starting a timer;
- R2: ``.env.example`` documents a future boundary by default, the same-day
  bootstrap allowed only before 20:00 ``America/Bahia`` and the permanent
  refusal of any past date; the fallback one-shot still forwards the declared
  boundary and the bounded finalization window, with the safe default of 7 and
  no silent fallback when a declared value is non-positive;
- R3-R7, R9-R10: ``deploy/README.md`` (section 5c) documents installation,
  configuration, preflight, human acceptance and activation as separate ordered
  checkpoints, activates only through
  ``docker compose up -d --no-deps --force-recreate census_orchestrator``,
  preserves the natural hourly/D-1 evidence before recreation, validates the
  three fallback timers ``disabled``/``inactive``, proves zero reports before
  the boundary with an aggregate count, observes only dates, revisions, status,
  counts and aggregate markers, declares the read-only Docker socket privilege,
  documents the post-05:00 ``d1_recovery_not_confirmed`` recovery and the 07:30
  human checkpoint, restricts the manual warning removal to a proven D-1
  success and rolls back without deleting revisions or reverting migrations;
- R8: ``docs/releases/v0.1.0-rc.32-upgrade.md`` carries backup, dormant deploy,
  fail-closed preflight, acceptance, isolated activation, observation and the
  exact-tag rollback with guarded mutable blocks;
- PDSPA-S2: the immutable release workflow verifies and attaches both
  statistics units (plus the activation preflight) in its single draft
  creation.
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
RC32_RUNBOOK = ROOT / "docs" / "releases" / "v0.1.0-rc.32-upgrade.md"

LOOKBACK_VAR = "STATISTICS_FINALIZATION_LOOKBACK_DAYS"
LOOKBACK_UNIT_DEFAULT = "7"
ENV_FILE_LINE = "EnvironmentFile=-/srv/apps/prisma/.env"

WORKFLOW = ROOT / ".github" / "workflows" / "publish-release-image.yml"
PREFLIGHT_ASSET = "deploy/daily-statistics-activation-preflight.sh"

SERVICE_NAME = "sirhosp-daily-statistics.service"
TIMER_NAME = "sirhosp-daily-statistics.timer"
ALL_UNIT_FILES = (SERVICE_NAME, TIMER_NAME)

HOURLY_TIMER = "sirhosp-discharges.timer"
D1_RECOVERY_TIMER = "sirhosp-historical-recovery.timer"
D1_RECOVERY_SERVICE = "sirhosp-historical-recovery.service"

# R1: the three fixed timers and the statistics one-shot are inert manual
# fallback — every one of them stays disabled/inactive on the adaptive path.
FALLBACK_UNITS = (HOURLY_TIMER, D1_RECOVERY_TIMER, SERVICE_NAME, TIMER_NAME)
FALLBACK_TIMERS = (HOURLY_TIMER, D1_RECOVERY_TIMER, TIMER_NAME)
FALLBACK_OWNER = {
    HOURLY_TIMER: "adaptive census orchestrator",
    D1_RECOVERY_TIMER: "adaptive census orchestrator",
    SERVICE_NAME: "orquestrador adaptativo",
    TIMER_NAME: "orquestrador adaptativo",
}

CALENDAR_LITERAL = "OnCalendar=*-*-* 07:30:00 America/Bahia"
D1_CALENDAR_LITERAL = "OnCalendar=*-*-* 05:00:00 America/Bahia"
HOURLY_CALENDAR_LITERAL = "OnCalendar=*-*-* *:13:00 America/Bahia"
BAHIA_DAILY_CALENDAR_RE = re.compile(
    r"^OnCalendar=\*-\*-\* (\d{2}):(\d{2}):(\d{2}) America/Bahia$", re.MULTILINE
)

ADAPTIVE_MARKERS = (
    "mode=d1-recovery result=success source=adaptive-orchestrator",
    "mode=hourly-discharges result=success source=adaptive-orchestrator",
)
PREFLIGHT_ASSET_NAME = PREFLIGHT_ASSET.split("/")[-1]
TAG_PLACEHOLDER = "v1.0.0-rc.N"

RECREATE_COMMAND = "up -d --no-deps --force-recreate census_orchestrator"
PREFLIGHT_COMMAND = f"./deploy/{PREFLIGHT_ASSET_NAME} {TAG_PLACEHOLDER}"

# Executions are not mutually exclusive, so no artifact may fall back to an
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


def _read(path: Path) -> str:
    assert path.exists(), f"{path} must exist"
    return path.read_text(encoding="utf-8")


def _unit_text(name: str) -> str:
    path = SYSTEMD_DIR / name
    assert path.exists(), f"systemd unit {name!r} must exist"
    return path.read_text(encoding="utf-8")


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


FENCED_SHELL_BLOCK_RE = re.compile(
    r"^```(?:bash|sh)\n(.*?)^```$", re.DOTALL | re.MULTILINE
)


def _shell_blocks(document: str) -> list[str]:
    """Fenced ``bash``/``sh`` snippets of a document, fences stripped."""
    return FENCED_SHELL_BLOCK_RE.findall(document)


@pytest.fixture(scope="module")
def runbook() -> str:
    return _section(_read(README), "## 5c.")


@pytest.fixture(scope="module")
def rc32_runbook() -> str:
    return _read(RC32_RUNBOOK)


def _deploy_docs() -> dict[str, str]:
    """The fallback timer comment and runbook text that state the contract."""
    return {
        TIMER_NAME: _unit_text(TIMER_NAME),
        "deploy/README.md": _read(README),
    }


# ---------------------------------------------------------------------------
# R1 — the fixed units are inert manual fallback, never the normal schedule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", FALLBACK_UNITS)
def test_fallback_units_declare_inert_manual_fallback(name: str) -> None:
    lowered = _unit_text(name).lower()
    for marker in ("fallback", "manual", "census_orchestrator"):
        assert marker in lowered, f"{name} must declare {marker!r}"
    assert FALLBACK_OWNER[name] in lowered, f"{name} must name the adaptive owner"
    assert ("disabled" in lowered) or ("desabilitado" in lowered)
    assert ("inactive" in lowered) or ("inativo" in lowered)


@pytest.mark.parametrize("name", FALLBACK_UNITS)
def test_fallback_units_never_offer_a_normal_schedule(name: str) -> None:
    """No fallback unit may present itself as the primary scheduler or tell the
    operator to enable/start it."""
    lowered = _unit_text(name).lower()
    for forbidden in (
        "systemctl enable",
        "systemctl start",
        "enable --now",
        "enabled only",
        "habilite",
        "scheduler prim",
        "primary schedul",
        "agendamento principal",
        "o único dono",
    ):
        assert forbidden not in lowered, f"{name} must not instruct {forbidden!r}"


def test_fallback_timers_keep_one_documented_bahia_calendar() -> None:
    calendars = {
        HOURLY_TIMER: HOURLY_CALENDAR_LITERAL,
        D1_RECOVERY_TIMER: D1_CALENDAR_LITERAL,
        TIMER_NAME: CALENDAR_LITERAL,
    }
    daily_calendars = (D1_RECOVERY_TIMER, TIMER_NAME)
    for name, literal in calendars.items():
        text = _unit_text(name)
        assert text.count("OnCalendar=") == 1
        assert literal in text
        assert "America/Bahia" in text
        assert "Persistent=true" in text
        assert "RemainAfterElapse=no" in text
        assert "RandomizedDelay" not in text
        assert "ExecStart=" not in text
        if name in daily_calendars:
            assert len(BAHIA_DAILY_CALENDAR_RE.findall(text)) == 1


def test_fallback_service_runs_only_the_manual_finalize_command() -> None:
    text = _unit_text(SERVICE_NAME)
    assert text.count("ExecStart=") == 1
    assert "materialize_daily_statistics --finalize" in text
    assert "--date" not in text
    assert re.findall(r"manage\.py ([a-z_]+)", text) == ["materialize_daily_statistics"]


def test_fallback_service_uses_the_hospital_oneshot_runtime() -> None:
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


def test_fallback_service_declares_the_full_runtime_contract() -> None:
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


def test_daily_statistics_timer_declares_documentation_and_install_target() -> None:
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


def test_docs_reject_the_absolute_non_collision_claim() -> None:
    """Distinct trigger instants are not a guarantee that executions cannot
    overlap, so no artifact may claim 07:30 never collides with :13/:47."""
    for label, text in _deploy_docs().items():
        lowered = text.lower()
        for forbidden in FORBIDDEN_ABSOLUTE_NON_COLLISION:
            assert forbidden not in lowered, (
                f"{label} must not claim the executions cannot collide "
                f"(found {forbidden!r})"
            )


def test_docs_disclaim_cross_workflow_mutual_exclusion() -> None:
    """The docs explicitly disclaim any mutual exclusion between the fallback
    finalization and the existing cadences; only the finalization's own
    bounded/idempotent/atomic/PostgreSQL-coordinated behavior is claimed."""
    docs = _deploy_docs()
    assert "não afirma exclusão mútua entre workflows" in docs["deploy/README.md"].lower()
    assert "não há relação de ordem nem de exclusão mútua" in docs[TIMER_NAME].lower()


def test_units_are_install_inert() -> None:
    for name in ALL_UNIT_FILES:
        text = _unit_text(name)
        assert "systemctl enable" not in text
        assert "systemctl start" not in text
        assert "enable --now" not in text


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
# R2 — declared, fail-closed boundary and the bounded manual window
# ---------------------------------------------------------------------------


def test_env_example_documents_the_boundary_rules() -> None:
    text = _read(ENV_EXAMPLE)
    assert "STATISTICS_ACTIVATION_DATE=" in text
    lowered = text.lower()
    for marker in ("obrigat", "futura", "bootstrap", "20:00", "passada", "backfill"):
        assert marker in lowered, f".env.example must document {marker!r}"
    assert "America/Bahia" in text


def test_fallback_service_forwards_the_declared_activation_date() -> None:
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


def test_fallback_service_forwards_the_configured_finalization_lookback() -> None:
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


def test_fallback_service_establishes_the_safe_lookback_default_of_seven() -> None:
    """An unset window must resolve to the safe default of 7 in the unit and in
    Django settings; an empty forwarded value would break the container instead
    of running the bounded batch."""
    assert f"Environment={LOOKBACK_VAR}={LOOKBACK_UNIT_DEFAULT}" in _unit_text(
        SERVICE_NAME
    )
    settings_source = _read(SETTINGS_SOURCE)
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
# R3-R7, R9-R10 — deploy/README.md, section 5c
# ---------------------------------------------------------------------------


def test_runbook_documents_the_adaptive_owner_and_fallback_units(
    runbook: str,
) -> None:
    for marker in (
        "census_orchestrator",
        "materialize_daily_statistics --date",
        "materialize_daily_statistics --finalize",
        "fallback manual",
        "ADR-0012",
        "historical_recovery",
        "--profile recovery",
        "run --rm",
        "America/Bahia",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"
    for unit in FALLBACK_TIMERS:
        assert unit in runbook, f"runbook must name the fallback unit {unit!r}"


def test_runbook_downloads_preflight_and_units_from_the_same_immutable_tag(
    runbook: str,
) -> None:
    """The read-only preflight and both units are downloaded from one single
    immutable release tag, never from a working copy or another version."""
    downloads = re.findall(r"releases/download/([^/\s\"']+)/([A-Za-z0-9._-]+)", runbook)
    assert downloads, "runbook must download the release assets by tag"
    assert {tag for tag, _asset in downloads} == {TAG_PLACEHOLDER}
    assets = {asset for _tag, asset in downloads}
    for asset in (PREFLIGHT_ASSET_NAME, SERVICE_NAME, TIMER_NAME):
        assert asset in assets, f"runbook must download {asset!r} from the release"
    assert f"chmod +x deploy/{PREFLIGHT_ASSET_NAME}" in runbook


def test_runbook_documents_installation_as_a_disabled_baseline(runbook: str) -> None:
    for marker in (
        "install -m 0644",
        "systemctl daemon-reload",
        "NÃO habilita",
        "systemctl is-enabled",
        "disabled",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"


def test_runbook_never_enables_a_legacy_timer(runbook: str) -> None:
    """R4: activation never enables the hourly, D-1 or statistics timer."""
    assert "systemctl enable" not in runbook
    assert "systemctl start" not in runbook
    for unit in FALLBACK_TIMERS:
        assert f"systemctl enable --now {unit}" not in runbook


def test_runbook_validates_the_three_fallback_timers_disabled_and_inactive(
    runbook: str,
) -> None:
    """R5: the runbook validates the three fallback timers before activating."""
    for unit in FALLBACK_TIMERS:
        assert unit in runbook, f"runbook must validate {unit!r}"
    for marker in (
        "systemctl is-enabled",
        "systemctl is-active",
        "legacy_timer_state",
        "inactive",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"


def test_runbook_documents_the_preflight_interface_and_fail_closed_checks(
    runbook: str,
) -> None:
    for marker in (
        "somente leitura",
        "fail-closed",
        f"{PREFLIGHT_ASSET.split('/')[-1]} <release-tag-exata>",
        "[preflight] result=PASS",
        "[preflight] result=FAIL",
        "não existe caminho de exceção",
        "release",
        "asset_match",
        "scheduler_contract",
        "image_version",
        "activation_date",
        "legacy_timer_state",
        "orchestrator_service",
        "cadence_hourly_discharges",
        "cadence_d1_recovery",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"
    for reason in (
        "local_asset_mismatch",
        "activation_date_in_past",
        "bootstrap_after_boundary",
        "cadence_stale",
        "compose_logs_unavailable",
        "timer_not_disabled",
        "orchestrator_service_missing",
    ):
        assert reason in runbook, f"runbook must enumerate {reason!r}"
    for forbidden in ("--skip", "bypass", "override", "sem-preflight"):
        assert forbidden not in runbook.lower(), (
            f"runbook must not document a bypass ({forbidden!r})"
        )


def test_runbook_declares_the_read_only_docker_socket_privilege(runbook: str) -> None:
    """R9: the operator privilege needed by the read-only Docker interface."""
    lowered = runbook.lower()
    for marker in ("socket do docker", "privilégio", "somente leitura"):
        assert marker in lowered, f"runbook must declare {marker!r}"


def test_runbook_orders_install_preflight_acceptance_and_activation(
    runbook: str,
) -> None:
    """R3: install (disabled) < preflight execution < human acceptance < the
    isolated activation, so no activation can precede the preflight or its
    review."""
    markers = (
        "sudo install -m 0644",
        PREFLIGHT_COMMAND,
        "aceite humano",
        RECREATE_COMMAND,
    )
    for marker in markers:
        assert marker in runbook, f"runbook must document {marker!r}"
    indices = [runbook.index(marker) for marker in markers]
    assert indices == sorted(indices), "runbook steps are out of order"


def test_runbook_preflight_collection_preserves_a_nonzero_status(
    runbook: str,
) -> None:
    """The aggregated preflight output is collected through ``tee`` only under
    ``pipefail`` plus an explicit nonzero-status abort, so a failed preflight is
    never masked by the successful ``tee`` nor archived as approved evidence."""
    blocks = [
        block
        for block in _shell_blocks(runbook)
        if "tee " in block and PREFLIGHT_ASSET.split("/")[-1] in block
    ]
    assert len(blocks) == 1, "exactly one block collects the preflight output"
    block = blocks[0]
    assert "pipefail" in block, "tee must not mask the preflight status"
    tee_pipeline = block.index("| tee ")
    assert block.index("pipefail") < tee_pipeline
    assert PREFLIGHT_COMMAND in block[:tee_pipeline]
    collected = block[tee_pipeline:]
    assert "exit 1" in collected, (
        "a failed preflight must abort the collection with a nonzero status"
    )
    for swallow in ("|| true", "|| :"):
        assert swallow not in collected, (
            f"the preflight status must not be swallowed by {swallow!r}"
        )


ACTIVATION_GUARD_RE = re.compile(
    r'test "\$\{(?P<count>\w+)\}" -gt 0 \\\n\s*\|\| \{[^\n]*exit 1[^\n]*\}',
)


def _recreate_blocks(document: str) -> list[str]:
    """Blocks that recreate the orchestrator (activation and rollback)."""
    return [block for block in _shell_blocks(document) if RECREATE_COMMAND in block]


def test_runbook_activation_recreates_only_the_orchestrator(runbook: str) -> None:
    """R4: every recreation block recreates only the orchestrator, with the
    documented flags, and enables no timer."""
    blocks = _recreate_blocks(runbook)
    assert blocks, "the recreation must be documented"
    for block in blocks:
        assert "set -euo pipefail" in block
        assert re.findall(r"up -d[^\n]*", block) == [
            "up -d --no-deps --force-recreate census_orchestrator"
        ]
        assert "systemctl enable" not in block


def test_runbook_guards_evidence_and_fallback_state_before_the_recreate(
    runbook: str,
) -> None:
    """R5: the activation block confirms the boundary, the inert fallback
    timers and the fresh natural cadence evidence before the recreation."""
    block = _recreate_blocks(runbook)[0]
    recreate = block.index(RECREATE_COMMAND)
    assert "STATISTICS_ACTIVATION_DATE" in block[:recreate]
    for unit in FALLBACK_TIMERS:
        assert block.index(unit) < recreate, f"{unit!r} must be validated first"
    assert block.index("systemctl is-enabled") < recreate
    assert block.index("systemctl is-active") < recreate
    guarded = ACTIVATION_GUARD_RE.findall(block)
    assert guarded == [
        "hourly_discharges_success",
        "d1_recovery_success",
    ], f"both cadence counts must be guarded by an explicit test, got {guarded!r}"
    first_guard = ACTIVATION_GUARD_RE.search(block)
    assert first_guard is not None
    assert block.index("grep -cF") < first_guard.start()
    for count in guarded:
        assert f'{count}="$(' in block, f"{count!r} must be assigned before the guard"
    assert block.rindex("exit 1") < recreate, "every guard must abort before it"


def test_runbook_collects_only_aggregate_cadence_evidence(runbook: str) -> None:
    """R5/R7: the natural D-1/hourly evidence is collected from the orchestrator
    container as aggregated marker counts before recreation, without copying raw
    log lines and without triggering any extraction."""
    for marker in ADAPTIVE_MARKERS:
        assert marker in runbook, f"runbook must collect {marker!r}"
    assert "grep -cF" in runbook
    assert "agregad" in runbook.lower()
    for forbidden in (
        "| tail",
        "tail -",
        "-o json",
        "MESSAGE",
        "extract_",
        "run_exit_reconciliation_runtime",
        "reset-failed",
    ):
        assert forbidden not in runbook, f"runbook must not use {forbidden!r}"
    for line in runbook.replace("\\\n", " ").splitlines():
        if "journalctl" in line:
            assert "grep" in line or SERVICE_NAME in line, (
                f"runbook must not copy raw journal lines ({line.strip()!r})"
            )


def test_runbook_confirms_health_and_zero_reports_before_the_boundary(
    runbook: str,
) -> None:
    """R5: after activation the operator confirms health and proves that no
    report earlier than the boundary exists, using an aggregate count only."""
    for marker in (
        "docker compose --env-file .env -f \"$COMPOSE_FILE\" ps census_orchestrator",
        "reports_before_boundary",
        "local_date__lt",
        'test "${reports_before_boundary}" = "0"',
    ):
        assert marker in runbook, f"runbook must document {marker!r}"


def test_runbook_documents_aggregate_observation_without_identity(
    runbook: str,
) -> None:
    """R7: observation uses dates, revisions, status, counts and aggregate
    markers only — never names, records, beds, clinical text or raw logs."""
    for marker in (
        "date=",
        "status=",
        "revision=",
        "created=",
        "quality=",
        "contagens",
        "identidade",
        "Daily statistics finalization finished",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"


def test_runbook_documents_the_post_05_recovery_and_0730_checkpoint(
    runbook: str,
) -> None:
    """R10: after 05:00 an unexpected missing revision triggers the adaptive
    recovery and at 07:30 the absence of a ready revision raises an alert and
    requires a human decision with no automatic retry."""
    for marker in (
        "05:00",
        "07:30",
        "d1_recovery_not_confirmed",
        "d1_recovery_incomplete",
        "alerta",
        "decisão humana",
        "nenhum retry automático",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"
    lowered = runbook.lower()
    assert "não dispara" in lowered
    assert "não executa" in lowered


def test_runbook_documents_the_manual_warning_removal_rules(runbook: str) -> None:
    """R10: the manual fallback only removes the degraded D-1 warnings after a
    proven D-1 success and never uses ``--finalize`` to clean them."""
    lowered = runbook.lower()
    for marker in (
        "depois de sucesso d-1 comprovado",
        "nunca usa `--finalize` para limpá-lo",
        "`--date`",
    ):
        assert marker in lowered, f"runbook must document {marker!r}"


def test_runbook_documents_the_boundary_bootstrap_window(runbook: str) -> None:
    """R2: future boundary by default, same-day bootstrap only before 20:00
    ``America/Bahia`` and no past date ever."""
    lowered = runbook.lower()
    for marker in (
        "20:00",
        "bootstrap",
        "data passada",
        "futura",
    ):
        assert marker in lowered, f"runbook must document {marker!r}"


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


def test_runbook_documents_single_date_rerun_and_rollback(runbook: str) -> None:
    for marker in (
        "materialize_daily_statistics --date",
        "rollback",
        "fontes clínicas",
    ):
        assert marker in runbook, f"runbook must document {marker!r}"


ROLLBACK_HEADING = "### 5c.7 "
UPSTREAM_UNIT_NAMES = ("sirhosp-discharges", "sirhosp-historical-recovery")


def test_runbook_rollback_removes_the_boundary_without_destroying_data(
    runbook: str,
) -> None:
    """R6: the rollback removes or reverts the boundary and recreates only the
    orchestrator, preserving revisions, clinical sources and migrations."""
    rollback = _section(runbook, ROLLBACK_HEADING)
    for marker in (
        "STATISTICS_ACTIVATION_DATE",
        RECREATE_COMMAND,
        "revisões",
        "migrations",
        "fontes clínicas",
        "desabilitad",
    ):
        assert marker in rollback, f"rollback must document {marker!r}"
    for forbidden in ("systemctl enable", "manage.py migrate", "DROP ", "flush"):
        assert forbidden not in rollback, f"rollback must not use {forbidden!r}"
    for upstream in UPSTREAM_UNIT_NAMES:
        assert upstream not in rollback, f"rollback must not touch {upstream!r}"


def test_runbook_rejects_the_absolute_non_overlap_claim(runbook: str) -> None:
    """The fallback trigger keeps the staggered-trigger contract with possible
    overlap and never claims non-overlap between workflows."""
    lowered = runbook.lower()
    for forbidden in FORBIDDEN_ABSOLUTE_NON_COLLISION:
        assert forbidden not in lowered, (
            f"runbook must not claim non-overlapping executions ({forbidden!r})"
        )
    assert "não afirma exclusão mútua entre workflows" in lowered


# ---------------------------------------------------------------------------
# PDSPA-S2 — both unit assets travel with the immutable release draft
# ---------------------------------------------------------------------------


def test_units_are_verified_and_attached_in_the_single_release_draft() -> None:
    """R1/R2: the release workflow checks both unit files (and the activation
    preflight) with ``test -f`` before the draft exists and attaches them as
    arguments of the single draft creation preceding the image build."""
    workflow = _read(WORKFLOW)
    normalized = " ".join(workflow.split())
    create = normalized.index("gh release create")

    for name in ALL_UNIT_FILES:
        asset = f"deploy/systemd/{name}"
        assert asset in workflow, f"release draft must attach {asset!r}"
    assert 'for asset in "${SYSTEMD_ASSETS[@]}"' in workflow
    assert normalized.index('test -f "${asset}"') < create
    assert f'PREFLIGHT_ASSET="{PREFLIGHT_ASSET}"' in workflow
    assert normalized.index('test -f "${PREFLIGHT_ASSET}"') < create

    create_statement = normalized[create : create + 400]
    assert '"${SYSTEMD_ASSETS[@]}"' in create_statement
    assert '"${PREFLIGHT_ASSET}"' in create_statement
    assert create < normalized.index("uses: docker/build-push-action@")


# ---------------------------------------------------------------------------
# R8 — docs/releases/v0.1.0-rc.32-upgrade.md
# ---------------------------------------------------------------------------

RC32_TAG = "v0.1.0-rc.32"
RC31_TAG = "v0.1.0-rc.31"


def test_rc32_runbook_declares_the_change_and_the_base_release(
    rc32_runbook: str,
) -> None:
    for marker in (
        RC32_TAG,
        RC31_TAG,
        "orchestrate-adaptive-statistics-finalization",
        "ADR-0012",
        "census_orchestrator",
        "Nenhuma migration",
        "Nenhuma credencial nova",
    ):
        assert marker in rc32_runbook, f"RC32 runbook must declare {marker!r}"


def test_rc32_runbook_backs_up_and_deploys_dormant_assets(
    rc32_runbook: str,
) -> None:
    for marker in (
        "pg_dump",
        "--format=custom",
        "pg_restore --list",
        "backups/",
        "up -d --remove-orphans",
        "migrate --noinput",
        "dormente",
        "systemctl is-enabled",
    ):
        assert marker in rc32_runbook, f"RC32 runbook must document {marker!r}"
    for unit in FALLBACK_TIMERS:
        assert unit in rc32_runbook, f"RC32 runbook must name {unit!r}"


def test_rc32_runbook_orders_backup_preflight_acceptance_and_activation(
    rc32_runbook: str,
) -> None:
    markers = (
        "pg_dump",
        "up -d --remove-orphans",
        './deploy/daily-statistics-activation-preflight.sh "${NEW_VERSION}"',
        "aceite humano",
        RECREATE_COMMAND,
    )
    for marker in markers:
        assert marker in rc32_runbook, f"RC32 runbook must document {marker!r}"
    indices = [rc32_runbook.index(marker) for marker in markers]
    assert indices == sorted(indices), "RC32 runbook steps are out of order"


def test_rc32_runbook_guards_every_mutable_block(rc32_runbook: str) -> None:
    blocks = _shell_blocks(rc32_runbook)
    assert blocks, "RC32 runbook must document guarded shell blocks"
    for block in blocks:
        assert "set -euo pipefail" in block, (
            f"every mutable block must fail closed: {block.splitlines()[:1]!r}"
        )


def test_rc32_runbook_activates_only_the_orchestrator_and_enables_no_timer(
    rc32_runbook: str,
) -> None:
    lowered = rc32_runbook.lower()
    for forbidden in ("systemctl enable", "systemctl start", "systemctl restart"):
        assert forbidden not in lowered, f"RC32 runbook must not use {forbidden!r}"
    for line in rc32_runbook.splitlines():
        if "up -d" in line and "census_orchestrator" in line:
            assert RECREATE_COMMAND in line, (
                "the orchestrator must only be recreated in isolation"
            )


def test_rc32_runbook_preserves_natural_evidence_before_recreation(
    rc32_runbook: str,
) -> None:
    for marker in ADAPTIVE_MARKERS:
        assert marker in rc32_runbook, f"RC32 runbook must collect {marker!r}"
    assert "grep -cF" in rc32_runbook
    assert rc32_runbook.index("grep -cF") < rc32_runbook.index(RECREATE_COMMAND)
    for forbidden in ("| tail", "-o json", "MESSAGE", "extract_", "reset-failed"):
        assert forbidden not in rc32_runbook, (
            f"RC32 runbook must not use {forbidden!r}"
        )


def test_rc32_runbook_observes_and_verifies_without_identity(
    rc32_runbook: str,
) -> None:
    for marker in (
        "date=",
        "status=",
        "revision=",
        "reports_before_boundary",
        "identidade",
        "somente leitura",
        "socket do Docker",
    ):
        assert marker in rc32_runbook, f"RC32 runbook must document {marker!r}"


def test_rc32_runbook_documents_the_recovery_checkpoints(rc32_runbook: str) -> None:
    for marker in (
        "05:00",
        "07:30",
        "d1_recovery_not_confirmed",
        "d1_recovery_incomplete",
        "decisão humana",
        "nenhum retry automático",
        "depois de sucesso D-1 comprovado",
        "nunca usa `--finalize` para limpá-lo",
    ):
        assert marker in rc32_runbook, f"RC32 runbook must document {marker!r}"


def test_rc32_runbook_rolls_back_the_exact_previous_tag_without_data_loss(
    rc32_runbook: str,
) -> None:
    rollback_index = rc32_runbook.index("## Rollback")
    rollback = rc32_runbook[rollback_index:]
    for marker in (
        f"OLD_VERSION={RC31_TAG}",
        "STATISTICS_ACTIVATION_DATE",
        RECREATE_COMMAND,
        "revisões",
        "Nenhuma migration",
    ):
        assert marker in rollback, f"RC32 rollback must document {marker!r}"
    for forbidden in ("systemctl enable", "manage.py migrate", "DROP "):
        assert forbidden not in rollback, f"RC32 rollback must not use {forbidden!r}"
