"""Synthetic host-level contract tests for the daily-statistics preflight.

The preflight is the read-only, fail-closed checkpoint executed on the hospital
host before the human activation checkpoint of the adaptive statistics
finalization. This suite pins, without touching any real production surface:

- R1: the preflight requires one exact release tag, refuses tags that are not
  published and immutable, and compares every required release asset byte by
  byte with the installed copy — the standalone ``compose.hospital.yml``, the
  preflight and the scheduler under the hospital directory, plus the
  finalization and exit-cadence systemd units; the configured image tag is
  proven by ``SIRHOSP_VERSION`` equality because the image is never downloaded
  or inspected here;
- R2: only ``SIRHOSP_VERSION`` and ``STATISTICS_ACTIVATION_DATE`` are read from
  the hospital ``.env`` (never sourced); the activation date must be valid and
  strictly future in ``America/Bahia``, and the initial bootstrap of the
  current day is accepted only before 20:00 local;
- R3: the hourly, D-1 and statistics timers must all be ``disabled`` and
  ``inactive``;
- R4: the canonical aggregated markers
  ``mode=hourly-discharges result=success source=adaptive-orchestrator`` (2
  hours) and ``mode=d1-recovery result=success source=adaptive-orchestrator``
  (30 hours) prove the natural cadences from the ``census_orchestrator``
  container logs;
- R5: during the RC31 transition an ordered, isolated block — start, expected
  mode dispatch, failure-free summary and finish — also proves success, and
  D-1 additionally requires the four canonical extractors and a 4/4 summary;
- R6: an isolated finish, broken order, overlapping blocks, a 3/4 summary,
  ``Failed`` greater than zero, a missing ``deaths`` extractor, unavailable
  logs or evidence that exists only in the manual services journal all fail
  closed;
- R7: Docker is queried only through ``compose ps``/``compose logs``; no
  ``exec``, ``run``, ``up``, ``start``, ``restart``, ``stop``, ``inspect`` or
  Django command may appear in an executable position;
- R8: synthetic clinical content in the logs never reaches stdout or stderr,
  and the output stays fully allowlisted;
- R9: a successful or failed run alters no fixture file or state.

Every scenario runs against fixtures, temporary directories and command
doubles (``curl``, ``systemctl``, ``docker``, ``date``) on ``PATH``; no
network, Docker daemon, systemd, journal or production path is used.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = ROOT / "deploy" / "daily-statistics-activation-preflight.sh"
SCHEDULER_SOURCE = ROOT / "deploy" / "exit-reconciliation-scheduler.sh"
COMPOSE_SOURCE = ROOT / "compose.hospital.yml"
SYSTEMD_SOURCE = ROOT / "deploy" / "systemd"

TAG = "v1.0.0-rc.32"
OTHER_TAG = "v1.0.0-rc.33"
FAKE_TODAY = "2026-09-25"
FAKE_HOUR = "12"
FUTURE_ACTIVATION_DATE = "2026-10-01"
PAST_ACTIVATION_DATE = "2026-09-24"

COMPOSE_ASSET = "compose.hospital.yml"
SCHEDULER_ASSET = "exit-reconciliation-scheduler.sh"
PREFLIGHT_ASSET = "daily-statistics-activation-preflight.sh"
DAILY_SERVICE = "sirhosp-daily-statistics.service"
DAILY_TIMER = "sirhosp-daily-statistics.timer"
HOURLY_SERVICE = "sirhosp-discharges.service"
HOURLY_TIMER = "sirhosp-discharges.timer"
D1_SERVICE = "sirhosp-historical-recovery.service"
D1_TIMER = "sirhosp-historical-recovery.timer"
STALE_SERVICE = "sirhosp-stale-reconciliation.service"
STALE_TIMER = "sirhosp-stale-reconciliation.timer"

LEGACY_TIMERS = (HOURLY_TIMER, D1_TIMER, DAILY_TIMER)

UNIT_ASSETS = (
    DAILY_SERVICE,
    DAILY_TIMER,
    HOURLY_SERVICE,
    HOURLY_TIMER,
    D1_SERVICE,
    D1_TIMER,
    STALE_SERVICE,
    STALE_TIMER,
)
REQUIRED_ASSETS = (COMPOSE_ASSET, SCHEDULER_ASSET, PREFLIGHT_ASSET, *UNIT_ASSETS)

CANONICAL_HOURLY = "mode=hourly-discharges result=success source=adaptive-orchestrator"
CANONICAL_D1 = "mode=d1-recovery result=success source=adaptive-orchestrator"
CANONICAL_SOURCE = "adaptive-orchestrator"
RC31_SOURCE = "rc31-orchestrator"

ORCHESTRATOR_SERVICE = "census_orchestrator"
COMPOSE_PREFIX = "census_orchestrator  | "

HOURLY_START_MESSAGE = (
    "2026-09-25 12:13:01,000 INFO apps.census.orchestration "
    "Intraday hourly recovery start: local time 2026-09-25 12:13:01 "
    "(America/Bahia), queue drained and batch closed."
)
HOURLY_DISPATCH_MESSAGE = (
    "exit_reconciliation_runtime: mode=hourly date=25/09/2026 extractors=discharges"
)
HOURLY_SUMMARY_MESSAGE = "Days: 1 | Steps: 1 | Succeeded: 1 | Failed: 0 | Skipped: 0"
HOURLY_CANONICAL_MESSAGE = (
    "2026-09-25 12:13:41,000 INFO apps.census.orchestration " + CANONICAL_HOURLY
)
HOURLY_FINISH_MESSAGE = (
    "2026-09-25 12:13:41,000 INFO apps.census.orchestration "
    "Intraday hourly recovery finished: local time 2026-09-25 12:13:41, "
    "duration 40 seconds."
)

D1_START_MESSAGE = (
    "2026-09-25 00:35:02,000 INFO apps.census.orchestration "
    "Quiet-window D-1 recovery start: local date 2026-09-24 "
    "(America/Bahia), queue drained and batch closed."
)
D1_DISPATCH_MESSAGE = (
    "exit_reconciliation_runtime: mode=d1 date=24/09/2026 "
    "extractors=discharges,admissions,deaths,official_census"
)
D1_SUMMARY_MESSAGE = "Days: 1 | Steps: 4 | Succeeded: 4 | Failed: 0 | Skipped: 0"
D1_CANONICAL_MESSAGE = (
    "2026-09-25 00:40:10,000 INFO apps.census.orchestration " + CANONICAL_D1
)
D1_FINISH_MESSAGE = (
    "2026-09-25 00:40:10,000 INFO apps.census.orchestration "
    "Quiet-window D-1 recovery finished: local date 2026-09-24, "
    "duration 308 seconds."
)

SECRET_VALUE = "cli-secret-value-must-not-leak"
CLINICAL_MESSAGE = "paciente NOME SOBRENOME prontuario 123456 leito 12A"

RECORD_RE = re.compile(
    r"^\[preflight\] check=[a-z0-9_]+ status=(?:PASS|FAIL)(?: [a-z_]+=\S+)*$"
)
RESULT_RE = re.compile(
    r"^\[preflight\] result=(?:PASS|FAIL) tag=\S+(?: (?:checks|failures)=\d+)?$"
)

# R7: Docker is restricted to the read-only ``ps``/``logs`` subcommands.
# ``docker_query`` is the single closed helper; any other verb must not appear.
ALLOWED_DOCKER_SUBCOMMANDS = {"ps", "logs"}
FORBIDDEN_DOCKER_SUBCOMMANDS = (
    "exec",
    "run",
    "up",
    "start",
    "restart",
    "stop",
    "kill",
    "inspect",
    "down",
    "rm",
    "build",
    "pull",
    "push",
    "create",
    "pause",
    "unpause",
    "top",
    "port",
    "cp",
    "attach",
    "wait",
    "commit",
    "export",
    "import",
    "load",
    "save",
    "tag",
    "update",
    "scale",
)

# R7: no mutating, extractive or database command may be executed by the
# preflight. Quoted literals are stripped before this scan because the script
# legitimately keeps the canonical runtime dispatch string as predicate data;
# only executable code positions are checked.
FORBIDDEN_CODE_PATTERNS = (
    r"\bsystemctl\s+(?:enable|disable|start|stop|restart|reload|daemon-reload|mask|unmask|link)\b",
    r"manage\.py",
    r"\bpsql\b",
    r"\bpg_dump\b",
    r"\bbackfill\b",
    r"materialize_daily_statistics",
    r"\bextract_[a-z_]+",
    r"\brecover_historical_data\b",
    r"run_exit_reconciliation_runtime",
    r"\breconcile_stale_admissions\b",
    r"\bgit\s+(?:clone|fetch|pull)\b",
)
FORBIDDEN_CURL_PATTERNS = (
    r"\s-X\s",
    r"--request",
    r"--data",
    r"\s-d\s",
    r"--upload-file",
    r"\s-T\s",
)
READ_ONLY_SYSTEMCTL_VERBS = {"is-enabled", "is-active"}
MUTATING_SYSTEMD_VERBS = (
    "enable",
    "disable",
    "start",
    "stop",
    "restart",
    "reload",
    "daemon-reload",
    "mask",
    "unmask",
    "link",
)

CURL_SHIM = '''#!/usr/bin/env python3
"""Command double for ``curl``: serves the synthetic release fixtures."""
import os
import pathlib
import sys


def main() -> int:
    args = sys.argv[1:]
    log = os.environ.get("FAKE_CURL_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join(args) + "\\n")
    if not args:
        return 2
    url = args[-1]
    release_dir = pathlib.Path(os.environ["FAKE_RELEASE_DIR"])
    if "/releases/tags/" in url:
        source = release_dir / "release.json"
    else:
        source = release_dir / "assets" / url.rsplit("/", 1)[-1]
    if not source.is_file():
        sys.stderr.write("curl: (22) synthetic download failure\\n")
        return 22
    data = source.read_bytes()
    if "-o" in args:
        pathlib.Path(args[args.index("-o") + 1]).write_bytes(data)
    else:
        sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

SYSTEMCTL_SHIM = '''#!/usr/bin/env python3
"""Command double for ``systemctl``: only the read-only state queries."""
import os
import pathlib
import sys

VERB_FIELD = {"is-enabled": 0, "is-active": 1}


def main() -> int:
    args = sys.argv[1:]
    log = os.environ.get("FAKE_SYSTEMCTL_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join(args) + "\\n")
    if len(args) != 2 or args[0] not in VERB_FIELD:
        sys.stderr.write("synthetic systemctl: unsupported invocation\\n")
        return 2
    state_file = pathlib.Path(os.environ["FAKE_SYSTEMD_STATE"])
    if not state_file.is_file():
        return 1
    for line in state_file.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts and parts[0] == args[1]:
            print(parts[1 + VERB_FIELD[args[0]]])
            return 0
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
'''

JOURNALCTL_SHIM = '''#!/usr/bin/env python3
"""Command double for ``journalctl``: replays synthetic per-unit journals.

The preflight must never consult the manual services journal for cadence
evidence; this double records any call so the suite can prove it stays unused.
"""
import os
import pathlib
import sys


def main() -> int:
    args = sys.argv[1:]
    log = os.environ.get("FAKE_JOURNALCTL_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join(args) + "\\n")
    unit = args[args.index("-u") + 1] if "-u" in args else ""
    source = pathlib.Path(os.environ["FAKE_JOURNAL_DIR"]) / (unit + ".log")
    if source.is_file():
        sys.stdout.write(source.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

DOCKER_SHIM = '''#!/usr/bin/env python3
"""Command double for ``docker``: daemon-free synthetic Compose queries.

The double shells out to nothing: it only reads fixture files below
``FAKE_DOCKER_DIR``. Any verb other than ``compose ps``/``compose logs`` is
refused before any fixture access, so the double can never act on a real
daemon.
"""
import os
import pathlib
import sys

READ_ONLY_SUBCOMMANDS = ("ps", "logs")


def main() -> int:
    args = sys.argv[1:]
    log = os.environ.get("FAKE_DOCKER_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join(args) + "\\n")
    if not args or args[0] != "compose":
        sys.stderr.write("synthetic docker: only compose queries are allowed\\n")
        return 1
    rest = list(args[1:])
    subcommand = None
    sub_args: list[str] = []
    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "-f":
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        subcommand = token
        sub_args = rest[index + 1:]
        break
    if subcommand not in READ_ONLY_SUBCOMMANDS:
        sys.stderr.write("synthetic docker: refused subcommand\\n")
        return 1
    fixture_dir = os.environ.get("FAKE_DOCKER_DIR")
    if not fixture_dir:
        sys.stderr.write("synthetic docker: fixtures unavailable\\n")
        return 1
    fixture = pathlib.Path(fixture_dir)
    if subcommand == "ps":
        services = fixture / "services.txt"
        if not services.is_file():
            sys.stderr.write("synthetic docker: ps unavailable\\n")
            return 1
        sys.stdout.write(services.read_text(encoding="utf-8"))
        return 0
    since = ""
    if "--since" in sub_args:
        since = sub_args[sub_args.index("--since") + 1]
    failed = os.environ.get("FAKE_DOCKER_FAIL_WINDOWS", "")
    if since and since in failed.split(","):
        sys.stderr.write("synthetic docker: logs unavailable\\n")
        return 1
    source = fixture / ("logs-" + since + ".log")
    if source.is_file():
        sys.stdout.write(source.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

DATE_SHIM = '''#!/usr/bin/env python3
"""Command double for ``date``: pins the ``America/Bahia`` clock.

``+%F`` (date) and ``+%H`` (hour) are fixed by the harness. Calendar-date
validation queries (``-d``) are delegated to the real binary so the script's
own round-trip check keeps being exercised. The caller ``TZ`` is recorded so
the suite can pin the Bahia timezone.
"""
import os
import sys

REAL_CANDIDATES = ("/usr/bin/date", "/bin/date")
PINNED = {"+%F": "FAKE_TODAY", "+%H": "FAKE_HOUR"}


def main() -> int:
    args = sys.argv[1:]
    log = os.environ.get("FAKE_DATE_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(f"{os.environ.get('TZ', '')} " + " ".join(args) + "\\n")
    if len(args) == 1 and args[0] in PINNED:
        print(os.environ.get(PINNED[args[0]], ""))
        return 0
    for candidate in REAL_CANDIDATES:
        if os.path.exists(candidate):
            os.execv(candidate, [candidate, *args])
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
'''


class PreflightRun:
    """One preflight invocation and the command doubles it triggered."""

    def __init__(self, completed: subprocess.CompletedProcess[str], logs_dir: Path) -> None:
        self.returncode = completed.returncode
        self.stdout = completed.stdout
        self.stderr = completed.stderr
        self.combined = completed.stdout + completed.stderr
        self.records = [
            line for line in completed.stdout.splitlines() if line.startswith("[preflight]")
        ]
        self._logs_dir = logs_dir

    def records_for(self, check: str) -> list[str]:
        prefix = f"[preflight] check={check} "
        return [line for line in self.records if line.startswith(prefix)]

    def status_for(self, check: str, unit: str | None = None) -> str | None:
        for line in self.records_for(check):
            if unit is not None and f"unit={unit}" not in line:
                continue
            match = re.search(r"status=(PASS|FAIL)", line)
            return match.group(1) if match else None
        return None

    def reasons(self) -> set[str]:
        found: set[str] = set()
        for line in self.records:
            match = re.search(r"reason=(\S+)", line)
            if match:
                found.add(match.group(1))
        return found

    def detail(self, check: str, key: str) -> str | None:
        for line in self.records_for(check):
            match = re.search(rf"(?:^|\s){key}=(\S+)", line)
            if match:
                return match.group(1)
        return None

    def call_lines(self, tool: str) -> list[str]:
        path = self._logs_dir / f"{tool}.log"
        if not path.exists():
            return []
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


class SyntheticHost:
    """Synthetic hospital host: release, installed assets, units and logs."""

    def __init__(self, root: Path) -> None:
        assert PREFLIGHT.exists(), "daily-statistics activation preflight must exist"
        self.root = root
        self.hospital = root / "srv" / "apps" / "prisma"
        self.deploy_dir = self.hospital / "deploy"
        self.systemd_dir = root / "etc-systemd"
        self.release_dir = root / "release"
        self.release_assets_dir = self.release_dir / "assets"
        self.journal_dir = root / "journal"
        self.docker_dir = root / "docker"
        self.logs_dir = root / "logs"
        self.shims_dir = root / "shims"
        self.tmp_work_dir = root / "tmp-work"
        self.state_file = root / "systemd-state.txt"
        for directory in (
            self.deploy_dir,
            self.systemd_dir,
            self.release_assets_dir,
            self.journal_dir,
            self.docker_dir,
            self.logs_dir,
            self.shims_dir,
            self.tmp_work_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self.release_base_url = "https://release.invalid/releases/download"
        self.release_api_url = "https://api.invalid/releases/tags"

        self.env_lines = [
            f"DJANGO_SECRET_KEY={SECRET_VALUE}",
            f"SIRHOSP_VERSION={TAG}",
            f"STATISTICS_ACTIVATION_DATE={FUTURE_ACTIVATION_DATE}",
        ]
        self.unit_states: dict[str, tuple[str, str]] = {
            DAILY_TIMER: ("disabled", "inactive"),
            HOURLY_TIMER: ("disabled", "inactive"),
            D1_TIMER: ("disabled", "inactive"),
        }
        # Manual fallback services keep emitting the aggregate marker in their
        # own journal; the preflight must never accept it as evidence.
        self.journal_lines: dict[str, list[str]] = {
            HOURLY_SERVICE: [f"[exit-reconciliation] {CANONICAL_HOURLY}"],
            D1_SERVICE: [f"[exit-reconciliation] {CANONICAL_D1}"],
        }
        self.compose_services = [
            "db",
            "web",
            "persistent_worker",
            ORCHESTRATOR_SERVICE,
            "summary_worker",
        ]
        self.orchestrator_logs: dict[str, list[str]] = {
            "2h": [
                HOURLY_START_MESSAGE,
                HOURLY_DISPATCH_MESSAGE,
                HOURLY_SUMMARY_MESSAGE,
                HOURLY_CANONICAL_MESSAGE,
                HOURLY_FINISH_MESSAGE,
                f"MESSAGE={CLINICAL_MESSAGE}",
            ],
            "30h": [
                D1_START_MESSAGE,
                D1_DISPATCH_MESSAGE,
                D1_SUMMARY_MESSAGE,
                D1_CANONICAL_MESSAGE,
                D1_FINISH_MESSAGE,
            ],
        }
        self.docker_fail_windows: set[str] = set()
        self.compose_log_prefix = COMPOSE_PREFIX
        self.suppress_env_file = False
        self.suppress_release_json = False
        self.release_meta: dict[str, object] = {
            "tag_name": TAG,
            "draft": False,
            "immutable": True,
            "published_at": "2026-09-01T12:00:00Z",
        }
        self.release_asset_names: list[str] = list(REQUIRED_ASSETS)

        self.publish_release_assets()
        self.install_local_assets()
        self.write_shims()

    # -- fixtures ----------------------------------------------------------

    @staticmethod
    def _source_bytes(asset: str) -> bytes:
        if asset == COMPOSE_ASSET:
            return COMPOSE_SOURCE.read_bytes()
        if asset == SCHEDULER_ASSET:
            return SCHEDULER_SOURCE.read_bytes()
        if asset == PREFLIGHT_ASSET:
            return PREFLIGHT.read_bytes()
        return (SYSTEMD_SOURCE / asset).read_bytes()

    def local_path(self, asset: str) -> Path:
        if asset == COMPOSE_ASSET:
            return self.hospital / asset
        if asset in (SCHEDULER_ASSET, PREFLIGHT_ASSET):
            return self.deploy_dir / asset
        return self.systemd_dir / asset

    def publish_release_assets(self) -> None:
        for asset in self.release_asset_names:
            (self.release_assets_dir / asset).write_bytes(self._source_bytes(asset))

    def install_local_assets(self) -> None:
        for asset in REQUIRED_ASSETS:
            self.local_path(asset).write_bytes(self._source_bytes(asset))

    def write_shims(self) -> None:
        for name, source in (
            ("curl", CURL_SHIM),
            ("systemctl", SYSTEMCTL_SHIM),
            ("journalctl", JOURNALCTL_SHIM),
            ("docker", DOCKER_SHIM),
            ("date", DATE_SHIM),
        ):
            path = self.shims_dir / name
            path.write_text(source, encoding="utf-8")
            path.chmod(
                path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )

    # -- mutations ---------------------------------------------------------

    def corrupt_release_asset(self, asset: str) -> None:
        path = self.release_assets_dir / asset
        path.write_bytes(path.read_bytes() + b"# tampered release asset\n")

    def strip_runtime_dispatch(self, asset: str) -> None:
        """Rewrite both copies identically, dropping the canonical dispatch."""
        for path in (self.release_assets_dir / asset, self.local_path(asset)):
            path.write_bytes(
                path.read_bytes().replace(
                    b"run_exit_reconciliation_runtime", b"legacy_runtime"
                )
            )

    def hide_scheduler_contract_in_comments_and_dead_code(self) -> None:
        """Keep the canonical dispatch only in a comment and in dead code.

        The executable ``case`` branches dispatch a legacy runtime, so an
        unrestricted asset substring search would still be satisfied while the
        real runtime contract is bypassed. Release and installed copies stay
        byte-identical, so ``asset_match`` keeps passing and only
        ``scheduler_contract`` may fail.
        """
        bypassed = SCHEDULER_SOURCE.read_bytes()
        for mode in (b"d1", b"hourly"):
            canonical = (
                b"RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode "
                + mode
                + b")"
            )
            assert canonical in bypassed
            bypassed = bypassed.replace(
                canonical,
                b"# "
                + canonical
                + b"\n        RUNNER_COMMAND=(legacy_exit_reconciliation --mode "
                + mode
                + b")",
            )
        for mode in (b"d1", b"hourly"):
            assert (
                b"RUNNER_COMMAND=(legacy_exit_reconciliation --mode " + mode + b")"
                in bypassed
            )
        bypassed += (
            b"\n# Dead code kept for rollback documentation.\n"
            b"documented_dispatch() {\n"
            b"    RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode d1)\n"
            b"    RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode hourly)\n"
            b"}\n"
        )
        self._write_scheduler_pair(bypassed)

    def annotate_scheduler_contract_with_comment_and_dead_code(self) -> None:
        """Add canonical literals as a comment plus a never-invoked function.

        The executable branches keep the canonical dispatch, so the contract
        must still pass: comments and dead code are not evidence, but neither
        may they turn a real branch into a failure.
        """
        annotated = SCHEDULER_SOURCE.read_bytes() + (
            b"\n# Rollback: RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode d1)\n"
            b"# Rollback: RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode hourly)\n"
            b"documented_dispatch() {\n"
            b"    RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode d1)\n"
            b"    RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode hourly)\n"
            b"}\n"
        )
        self._write_scheduler_pair(annotated)

    def hide_scheduler_contract_behind_indirect_dispatch(self) -> None:
        """Dispatch legacy code indirectly; keep canonical text in dead code.

        The real top-level ``case`` branches call an indirect legacy helper and
        never assign the canonical ``RUNNER_COMMAND``; the canonical labels and
        assignment survive only inside a never-invoked function. A parser that
        scans every line and remembers the last ``case`` label would still
        pass, so the contract must bind evidence to the top-level branch and
        fail closed on the indirect dispatch.
        """
        bypassed = SCHEDULER_SOURCE.read_bytes()
        for mode in (b"d1", b"hourly"):
            canonical = (
                b"RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode "
                + mode
                + b")"
            )
            assert canonical in bypassed
            bypassed = bypassed.replace(
                canonical, b"dispatch_legacy_runner --mode " + mode
            )
        assert (
            b"RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode d1)"
            not in bypassed
        )
        bypassed += (
            b"\n# Canonical dispatch retained for documentation only.\n"
            b"documented_dispatch() {\n"
            b'    case "${mode}" in\n'
            b'        "${MODE_D1}")\n'
            b"            RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode d1)\n"
            b"            ;;\n"
            b'        "${MODE_HOURLY}")\n'
            b"            RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode hourly)\n"
            b"            ;;\n"
            b"    esac\n"
            b"}\n"
        )
        self._write_scheduler_pair(bypassed)

    def _write_scheduler_pair(self, payload: bytes) -> None:
        for path in (
            self.release_assets_dir / SCHEDULER_ASSET,
            self.local_path(SCHEDULER_ASSET),
        ):
            path.write_bytes(payload)

    def drop_release_asset_file(self, asset: str) -> None:
        (self.release_assets_dir / asset).unlink()

    def corrupt_local_asset(self, asset: str) -> None:
        path = self.local_path(asset)
        path.write_bytes(path.read_bytes() + b"# locally modified unit\n")

    def remove_local_asset(self, asset: str) -> None:
        self.local_path(asset).unlink()

    # -- execution ---------------------------------------------------------

    def materialize(self) -> None:
        if not self.suppress_env_file:
            (self.hospital / ".env").write_text(
                "\n".join(self.env_lines) + "\n", encoding="utf-8"
            )
        state_lines = [
            f"{unit} {enabled} {active}"
            for unit, (enabled, active) in sorted(self.unit_states.items())
        ]
        self.state_file.write_text("\n".join(state_lines) + "\n", encoding="utf-8")
        for stale in self.journal_dir.glob("*.log"):
            stale.unlink()
        for unit, lines in self.journal_lines.items():
            (self.journal_dir / f"{unit}.log").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
        (self.docker_dir / "services.txt").write_text(
            "\n".join(self.compose_services) + "\n", encoding="utf-8"
        )
        for window, lines in self.orchestrator_logs.items():
            prefixed = [f"{self.compose_log_prefix}{line}" for line in lines]
            (self.docker_dir / f"logs-{window}.log").write_text(
                "\n".join(prefixed) + "\n", encoding="utf-8"
            )
        release = dict(self.release_meta)
        release["assets"] = [{"name": name} for name in self.release_asset_names]
        if not self.suppress_release_json:
            (self.release_dir / "release.json").write_text(
                json.dumps(release), encoding="utf-8"
            )

    def _reset_logs(self) -> None:
        for path in self.logs_dir.glob("*.log"):
            path.unlink()

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.shims_dir}{os.pathsep}{env.get('PATH', '')}",
                "HOSPITAL_DIR": str(self.hospital),
                "SYSTEMD_UNIT_DIR": str(self.systemd_dir),
                "RELEASE_BASE_URL": self.release_base_url,
                "RELEASE_API_URL": self.release_api_url,
                "TMPDIR": str(self.tmp_work_dir),
                "FAKE_RELEASE_DIR": str(self.release_dir),
                "FAKE_JOURNAL_DIR": str(self.journal_dir),
                "FAKE_SYSTEMD_STATE": str(self.state_file),
                "FAKE_TODAY": FAKE_TODAY,
                "FAKE_HOUR": FAKE_HOUR,
                "FAKE_CURL_LOG": str(self.logs_dir / "curl.log"),
                "FAKE_SYSTEMCTL_LOG": str(self.logs_dir / "systemctl.log"),
                "FAKE_JOURNALCTL_LOG": str(self.logs_dir / "journalctl.log"),
                "FAKE_DOCKER_DIR": str(self.docker_dir),
                "FAKE_DOCKER_LOG": str(self.logs_dir / "docker.log"),
                "FAKE_DOCKER_FAIL_WINDOWS": ",".join(sorted(self.docker_fail_windows)),
                "FAKE_DATE_LOG": str(self.logs_dir / "date.log"),
            }
        )
        return env

    def run_raw_docker(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", *args],
            env=self._environment(),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def run(
        self, *args: str, extra_env: dict[str, str] | None = None
    ) -> PreflightRun:
        self.materialize()
        self._reset_logs()
        env = self._environment()
        if extra_env:
            env.update(extra_env)
        completed = subprocess.run(
            ["bash", str(PREFLIGHT), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return PreflightRun(completed, self.logs_dir)


@pytest.fixture()
def host(tmp_path: Path) -> SyntheticHost:
    return SyntheticHost(tmp_path)


def script_text() -> str:
    assert PREFLIGHT.exists(), "daily-statistics activation preflight must exist"
    return PREFLIGHT.read_text(encoding="utf-8")


def code_lines(text: str) -> list[str]:
    """Executable shell lines: comments and quoted literals removed."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(re.sub(r"'[^']*'|\"[^\"]*\"", "", line))
    return lines


def non_comment_lines(text: str) -> list[str]:
    """Shell lines that are not pure comments (quoted literals kept)."""
    return [
        raw.strip()
        for raw in text.splitlines()
        if raw.strip() and not raw.strip().startswith("#")
    ]


def docker_query_calls(text: str) -> list[str]:
    return re.findall(r"docker_query\s+([a-z][a-z-]*)", text)


def assert_failed(result: PreflightRun, reason: str) -> None:
    assert result.returncode != 0, f"expected failure, got: {result.combined}"
    assert reason in result.reasons(), (
        f"expected reason {reason!r} in {sorted(result.reasons())}"
    )


def assert_allowlisted_output(result: PreflightRun) -> None:
    for line in result.stdout.splitlines():
        assert RECORD_RE.match(line) or RESULT_RE.match(line), (
            f"non-allowlisted stdout line: {line!r}"
        )


def assert_no_secret_or_clinical_content(result: PreflightRun) -> None:
    assert SECRET_VALUE not in result.combined
    assert "prontuario" not in result.combined
    assert "NOME SOBRENOME" not in result.combined
    assert "MESSAGE=" not in result.combined


def assert_no_raw_marker(result: PreflightRun) -> None:
    assert CANONICAL_HOURLY not in result.combined
    assert CANONICAL_D1 not in result.combined


def host_state(host: SyntheticHost) -> dict[str, bytes]:
    state: dict[str, bytes] = {}
    for base in (
        host.hospital,
        host.systemd_dir,
        host.journal_dir,
        host.release_dir,
        host.docker_dir,
        host.shims_dir,
    ):
        for path in sorted(base.rglob("*")):
            if path.is_file():
                state[str(path)] = path.read_bytes()
    state[str(host.state_file)] = host.state_file.read_bytes()
    return state


# ---------------------------------------------------------------------------
# R1 — immutable release provenance
# ---------------------------------------------------------------------------


def test_preflight_script_exists_and_is_executable() -> None:
    assert PREFLIGHT.exists(), "preflight script must exist"
    assert PREFLIGHT.stat().st_mode & stat.S_IXUSR, "preflight script must be executable"
    assert re.search(r"^set -euo pipefail$", preflight_text := script_text(), re.M)
    assert "daily-statistics-activation-preflight" in preflight_text


def test_successful_preflight_proves_provenance_and_cadences(host: SyntheticHost) -> None:
    result = host.run(TAG)

    assert result.returncode == 0, result.combined
    assert result.status_for("release") == "PASS"
    assert result.status_for("asset_match") == "PASS"
    assert result.detail("asset_match", "assets") == str(len(REQUIRED_ASSETS))
    assert result.status_for("scheduler_contract") == "PASS"
    assert result.status_for("image_version") == "PASS"
    assert result.status_for("activation_date") == "PASS"
    assert result.status_for("legacy_timer_state", HOURLY_TIMER) == "PASS"
    assert result.status_for("legacy_timer_state", D1_TIMER) == "PASS"
    assert result.status_for("legacy_timer_state", DAILY_TIMER) == "PASS"
    assert result.status_for("orchestrator_service") == "PASS"
    assert result.detail("orchestrator_service", "service") == ORCHESTRATOR_SERVICE
    assert result.status_for("cadence_hourly_discharges") == "PASS"
    assert result.status_for("cadence_d1_recovery") == "PASS"
    assert result.reasons() == set()
    assert RESULT_RE.match(result.records[-1]), result.records[-1]
    assert result.records[-1].startswith(f"[preflight] result=PASS tag={TAG} ")
    assert "checks=" in result.records[-1]

    api_calls = [
        line
        for line in result.call_lines("curl")
        if f"{host.release_api_url}/{TAG}" in line
    ]
    assert len(api_calls) == 1, "the exact tag release must be queried once"
    for asset in REQUIRED_ASSETS:
        assert any(
            f"{host.release_base_url}/{TAG}/{asset}" in line
            for line in result.call_lines("curl")
        ), f"release asset {asset!r} must be downloaded from the exact tag"


def test_preflight_requires_one_exact_tag_argument(host: SyntheticHost) -> None:
    for args in ((), (TAG, "extra"), ("../evil",), ("v1/evil",), ("-v1.0.0-rc.32",), ("..",)):
        result = host.run(*args)
        assert result.returncode == 2, f"args {args!r} must be refused: {result.combined}"
        assert result.records == []
        assert result.call_lines("curl") == []
        assert result.call_lines("systemctl") == []
        assert result.call_lines("docker") == []
        assert result.stderr.startswith(
            "Uso: daily-statistics-activation-preflight.sh"
        )


def test_unpublished_draft_release_fails_closed(host: SyntheticHost) -> None:
    host.release_meta["draft"] = True
    result = host.run(TAG)

    assert_failed(result, "release_is_draft")
    assert result.status_for("asset_match") == "FAIL"
    assert "release_unverified" in result.reasons()


def test_mutable_release_fails_closed(host: SyntheticHost) -> None:
    host.release_meta["immutable"] = False
    result = host.run(TAG)

    assert_failed(result, "release_not_immutable")
    assert result.status_for("release") == "FAIL"
    assert result.status_for("asset_match") == "FAIL"


def test_release_tag_mismatch_fails_closed(host: SyntheticHost) -> None:
    host.release_meta["tag_name"] = OTHER_TAG
    result = host.run(TAG)

    assert_failed(result, "release_tag_mismatch")


def test_unreachable_release_fails_closed_without_local_substitute(
    host: SyntheticHost,
) -> None:
    host.suppress_release_json = True
    result = host.run(TAG)

    assert_failed(result, "release_unavailable")
    assert "release_unverified" in result.reasons()
    assert result.status_for("asset_match") == "FAIL"
    assert result.status_for("scheduler_contract") == "FAIL"
    # The installed copies exist and match each other; the local copies are
    # still never accepted as proof of the release.
    assert result.status_for("image_version") == "PASS"


def test_release_without_a_required_asset_fails_closed(host: SyntheticHost) -> None:
    host.release_asset_names.remove(D1_TIMER)
    result = host.run(TAG)

    assert_failed(result, "release_asset_missing")
    assert result.status_for("asset_match") == "FAIL"


def test_hospital_compose_is_a_required_release_asset(host: SyntheticHost) -> None:
    host.release_asset_names.remove(COMPOSE_ASSET)
    result = host.run(TAG)

    assert_failed(result, "release_asset_missing")
    assert result.status_for("asset_match") == "FAIL"


def test_unavailable_release_asset_fails_closed(host: SyntheticHost) -> None:
    host.drop_release_asset_file(STALE_TIMER)
    result = host.run(TAG)

    assert_failed(result, "release_asset_unavailable")
    assert result.status_for("asset_match") == "FAIL"


def test_local_asset_divergence_fails_closed(host: SyntheticHost) -> None:
    host.corrupt_local_asset(HOURLY_TIMER)
    result = host.run(TAG)

    assert_failed(result, "local_asset_mismatch")
    assert result.status_for("asset_match") == "FAIL"
    assert any(
        f"asset={HOURLY_TIMER}" in line for line in result.records_for("asset_match")
    )


def test_hospital_compose_is_compared_byte_by_byte(host: SyntheticHost) -> None:
    host.corrupt_local_asset(COMPOSE_ASSET)
    result = host.run(TAG)

    assert_failed(result, "local_asset_mismatch")
    assert any(
        f"asset={COMPOSE_ASSET}" in line for line in result.records_for("asset_match")
    )


def test_missing_local_asset_fails_closed(host: SyntheticHost) -> None:
    host.remove_local_asset(SCHEDULER_ASSET)
    result = host.run(TAG)

    assert_failed(result, "local_asset_missing")
    assert result.status_for("asset_match") == "FAIL"


def test_configured_image_tag_must_equal_the_release_tag(host: SyntheticHost) -> None:
    host.env_lines = [
        line for line in host.env_lines if not line.startswith("SIRHOSP_VERSION=")
    ] + [f"SIRHOSP_VERSION={OTHER_TAG}"]
    result = host.run(TAG)

    assert_failed(result, "image_tag_mismatch")
    assert result.status_for("image_version") == "FAIL"


def test_all_deployed_assets_of_the_release_are_compared(host: SyntheticHost) -> None:
    result = host.run(TAG)

    assert result.status_for("asset_match") == "PASS"
    for asset in REQUIRED_ASSETS:
        path = host.local_path(asset)
        assert path.is_file()
        assert path.read_bytes() == (host.release_assets_dir / asset).read_bytes()


def test_downloaded_release_copy_divergence_fails_closed(host: SyntheticHost) -> None:
    """Only the downloaded copy is tampered: the byte comparison owns it."""
    host.corrupt_release_asset(PREFLIGHT_ASSET)
    result = host.run(TAG)

    assert_failed(result, "local_asset_mismatch")
    assert any(
        f"asset={PREFLIGHT_ASSET}" in line
        for line in result.records_for("asset_match")
    )


def test_scheduler_contract_requires_the_canonical_runtime_dispatch(
    host: SyntheticHost,
) -> None:
    host.strip_runtime_dispatch(SCHEDULER_ASSET)
    result = host.run(TAG)

    assert result.status_for("asset_match") == "PASS", (
        "release and installed bytes are identical here, so the contract check "
        "must be the one that fails"
    )
    assert_failed(result, "scheduler_contract_missing")
    assert result.status_for("scheduler_contract") == "FAIL"


def test_scheduler_contract_rejects_canonical_literals_in_comments_and_dead_code(
    host: SyntheticHost,
) -> None:
    host.hide_scheduler_contract_in_comments_and_dead_code()
    result = host.run(TAG)

    assert result.status_for("asset_match") == "PASS", (
        "release and installed bytes are identical here, so only the executable "
        "contract check may fail"
    )
    assert result.status_for("scheduler_contract") == "FAIL"
    assert_failed(result, "scheduler_contract_missing")
    assert result.detail("scheduler_contract", "mode") == "d1-recovery"


def test_scheduler_contract_accepts_real_branches_plus_comment_and_dead_code(
    host: SyntheticHost,
) -> None:
    host.annotate_scheduler_contract_with_comment_and_dead_code()
    result = host.run(TAG)

    assert result.returncode == 0, result.combined
    assert result.status_for("asset_match") == "PASS"
    assert result.status_for("scheduler_contract") == "PASS"
    assert result.detail("scheduler_contract", "modes") == "d1-recovery,hourly-discharges"


def test_scheduler_contract_rejects_indirect_dispatch_hidden_behind_dead_code(
    host: SyntheticHost,
) -> None:
    host.hide_scheduler_contract_behind_indirect_dispatch()
    result = host.run(TAG)

    assert result.status_for("asset_match") == "PASS", (
        "release and installed bytes are identical here, so only the executable "
        "contract check may fail"
    )
    assert result.status_for("scheduler_contract") == "FAIL"
    assert_failed(result, "scheduler_contract_missing")
    assert result.detail("scheduler_contract", "mode") == "d1-recovery"


# ---------------------------------------------------------------------------
# R2 — allowlisted .env keys and the activation boundary
# ---------------------------------------------------------------------------


def test_future_activation_date_is_approved(host: SyntheticHost) -> None:
    result = host.run(TAG)

    assert result.returncode == 0, result.combined
    assert result.detail("activation_date", "window") == "strictly_future"


@pytest.mark.parametrize("hour", ["00", "07", "19"])
def test_current_day_bootstrap_is_approved_before_2000(
    host: SyntheticHost, hour: str
) -> None:
    host.env_lines = [
        line
        for line in host.env_lines
        if not line.startswith("STATISTICS_ACTIVATION_DATE=")
    ] + [f"STATISTICS_ACTIVATION_DATE={FAKE_TODAY}"]
    result = host.run(TAG, extra_env={"FAKE_HOUR": hour})

    assert result.returncode == 0, result.combined
    assert result.detail("activation_date", "window") == "bootstrap_current"


@pytest.mark.parametrize("hour", ["20", "23"])
def test_current_day_bootstrap_fails_at_or_after_2000(
    host: SyntheticHost, hour: str
) -> None:
    host.env_lines = [
        line
        for line in host.env_lines
        if not line.startswith("STATISTICS_ACTIVATION_DATE=")
    ] + [f"STATISTICS_ACTIVATION_DATE={FAKE_TODAY}"]
    result = host.run(TAG, extra_env={"FAKE_HOUR": hour})

    assert_failed(result, "bootstrap_after_boundary")
    assert result.status_for("activation_date") == "FAIL"


def test_past_activation_date_fails_closed(host: SyntheticHost) -> None:
    host.env_lines = [
        line
        for line in host.env_lines
        if not line.startswith("STATISTICS_ACTIVATION_DATE=")
    ] + [f"STATISTICS_ACTIVATION_DATE={PAST_ACTIVATION_DATE}"]
    result = host.run(TAG)

    assert_failed(result, "activation_date_in_past")
    assert result.status_for("activation_date") == "FAIL"


@pytest.mark.parametrize("unsafe_date", ["2026-02-30", "2026-9-1", "2026-13-01", "20261001"])
def test_invalid_activation_date_fails_closed(
    host: SyntheticHost, unsafe_date: str
) -> None:
    host.env_lines = [
        line
        for line in host.env_lines
        if not line.startswith("STATISTICS_ACTIVATION_DATE=")
    ] + [f"STATISTICS_ACTIVATION_DATE={unsafe_date}"]
    result = host.run(TAG)

    assert_failed(result, "env_date_invalid")


def test_undeclared_or_empty_activation_date_fails_closed(host: SyntheticHost) -> None:
    host.env_lines = [
        line
        for line in host.env_lines
        if not line.startswith("STATISTICS_ACTIVATION_DATE=")
    ]
    result = host.run(TAG)
    assert_failed(result, "env_value_missing")

    host.env_lines = host.env_lines + ["STATISTICS_ACTIVATION_DATE="]
    result = host.run(TAG)
    assert_failed(result, "env_value_missing")


def test_activation_boundary_is_evaluated_in_america_bahia(host: SyntheticHost) -> None:
    host.env_lines = [
        line
        for line in host.env_lines
        if not line.startswith("STATISTICS_ACTIVATION_DATE=")
    ] + [f"STATISTICS_ACTIVATION_DATE={FAKE_TODAY}"]
    result = host.run(TAG)

    assert result.returncode == 0, result.combined
    date_calls = result.call_lines("date")
    assert any(line == "America/Bahia +%F" for line in date_calls), date_calls
    assert any(line == "America/Bahia +%H" for line in date_calls), date_calls


def test_duplicate_env_declaration_fails_closed(host: SyntheticHost) -> None:
    host.env_lines = host.env_lines + [f"SIRHOSP_VERSION={TAG}"]
    result = host.run(TAG)

    assert_failed(result, "env_value_duplicate")
    assert result.status_for("image_version") == "FAIL"


@pytest.mark.parametrize(
    "declaration",
    [
        'SIRHOSP_VERSION="v1.0.0-rc.32"',
        " SIRHOSP_VERSION=v1.0.0-rc.32",
        "SIRHOSP_VERSION = v1.0.0-rc.32",
        "SIRHOSP_VERSION=v1.0.0-rc.32 # latest",
        "export SIRHOSP_VERSION=v1.0.0-rc.32",
        "SIRHOSP_VERSION=${RELEASE_TAG}",
    ],
)
def test_ambiguous_env_declaration_fails_closed(
    host: SyntheticHost, declaration: str
) -> None:
    host.env_lines = [
        line for line in host.env_lines if not line.startswith("SIRHOSP_VERSION")
    ] + [declaration]
    result = host.run(TAG)

    assert_failed(result, "env_value_ambiguous")
    assert result.status_for("image_version") == "FAIL"


def test_missing_env_file_fails_closed(host: SyntheticHost) -> None:
    host.suppress_env_file = True
    result = host.run(TAG)

    assert_failed(result, "env_file_unreadable")
    assert result.status_for("image_version") == "FAIL"
    assert result.status_for("activation_date") == "FAIL"


def test_script_reads_only_the_two_allowlisted_env_keys() -> None:
    text = script_text()
    keys = set(re.findall(r"read_env_value\s+([A-Z][A-Z0-9_]*)", text))
    assert keys == {"SIRHOSP_VERSION", "STATISTICS_ACTIVATION_DATE"}

    for line in code_lines(text):
        assert not re.match(r"\s*(?:\.|source)\s+\S", line), line
        assert "set -a" not in line, line
        if line.startswith("export "):
            assert line.split()[1].split("=")[0] == "LC_ALL", line


# ---------------------------------------------------------------------------
# R3 — hourly, D-1 and statistics timers stay disabled/inactive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("timer", LEGACY_TIMERS)
def test_legacy_timer_must_be_disabled(host: SyntheticHost, timer: str) -> None:
    host.unit_states[timer] = ("enabled", "inactive")
    result = host.run(TAG)

    assert_failed(result, "timer_not_disabled")
    assert result.status_for("legacy_timer_state", timer) == "FAIL"


@pytest.mark.parametrize("timer", LEGACY_TIMERS)
def test_legacy_timer_must_be_inactive(host: SyntheticHost, timer: str) -> None:
    host.unit_states[timer] = ("disabled", "active")
    result = host.run(TAG)

    assert_failed(result, "timer_not_inactive")
    assert result.status_for("legacy_timer_state", timer) == "FAIL"


def test_missing_timer_state_fails_closed(host: SyntheticHost) -> None:
    host.unit_states.pop(D1_TIMER)
    result = host.run(TAG)

    assert_failed(result, "unit_state_unavailable")
    assert result.status_for("legacy_timer_state", D1_TIMER) == "FAIL"
    assert result.status_for("legacy_timer_state", HOURLY_TIMER) == "PASS"


# ---------------------------------------------------------------------------
# R4 — canonical aggregated markers from the orchestrator container logs
# ---------------------------------------------------------------------------


def test_canonical_markers_prove_both_cadences(host: SyntheticHost) -> None:
    result = host.run(TAG)

    assert result.returncode == 0, result.combined
    assert result.detail("cadence_hourly_discharges", "source") == CANONICAL_SOURCE
    assert result.detail("cadence_hourly_discharges", "window") == "2h"
    assert result.detail("cadence_d1_recovery", "source") == CANONICAL_SOURCE
    assert result.detail("cadence_d1_recovery", "window") == "30h"


def test_orchestrator_logs_are_queried_through_read_only_compose_windows(
    host: SyntheticHost,
) -> None:
    result = host.run(TAG)

    calls = result.call_lines("docker")
    ps_calls = [line for line in calls if " ps" in line]
    log_calls = [line for line in calls if " logs" in line]
    assert len(ps_calls) == 1, calls
    assert len(log_calls) == 2, calls
    windows = sorted(line.split("--since")[1].split()[0] for line in log_calls)
    assert windows == ["2h", "30h"], calls
    for line in calls:
        assert "-f" in line and "compose.hospital.yml" in line, line
        assert line.split()[0] == "compose", line
    for line in log_calls:
        assert "--no-color" in line
        assert ORCHESTRATOR_SERVICE in line


def test_canonical_marker_must_come_from_the_orchestrator_service(
    host: SyntheticHost,
) -> None:
    host.compose_services.remove(ORCHESTRATOR_SERVICE)
    result = host.run(TAG)

    assert_failed(result, "orchestrator_service_missing")
    assert result.status_for("orchestrator_service") == "FAIL"


def test_unavailable_compose_queries_fail_closed(host: SyntheticHost) -> None:
    host.docker_fail_windows.update({"2h", "30h"})
    result = host.run(TAG)

    assert_failed(result, "compose_logs_unavailable")
    assert result.status_for("cadence_hourly_discharges") == "FAIL"
    assert result.status_for("cadence_d1_recovery") == "FAIL"


def test_empty_orchestrator_logs_fail_closed(host: SyntheticHost) -> None:
    host.orchestrator_logs = {"2h": [], "30h": []}
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_hourly_discharges") == "FAIL"
    assert result.status_for("cadence_d1_recovery") == "FAIL"


def test_manual_service_journal_is_never_accepted_nor_consulted(
    host: SyntheticHost,
) -> None:
    host.orchestrator_logs = {"2h": [], "30h": []}
    host.journal_lines = {
        HOURLY_SERVICE: [f"[exit-reconciliation] {CANONICAL_HOURLY}"],
        D1_SERVICE: [f"[exit-reconciliation] {CANONICAL_D1}"],
    }
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.call_lines("journalctl") == [], (
        "the manual services journal must never be used as cadence evidence"
    )


def test_hourly_window_only_accepts_hourly_evidence(host: SyntheticHost) -> None:
    host.orchestrator_logs["2h"] = [D1_CANONICAL_MESSAGE]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_hourly_discharges") == "FAIL"
    assert result.status_for("cadence_d1_recovery") == "PASS"


# ---------------------------------------------------------------------------
# R5 — isolated, ordered RC31 transition blocks
# ---------------------------------------------------------------------------


def rc31_hourly() -> list[str]:
    return [
        HOURLY_START_MESSAGE,
        HOURLY_DISPATCH_MESSAGE,
        HOURLY_SUMMARY_MESSAGE,
        HOURLY_FINISH_MESSAGE,
    ]


def rc31_d1() -> list[str]:
    return [
        D1_START_MESSAGE,
        D1_DISPATCH_MESSAGE,
        D1_SUMMARY_MESSAGE,
        D1_FINISH_MESSAGE,
    ]


def test_rc31_ordered_blocks_prove_both_cadences_without_canonical_markers(
    host: SyntheticHost,
) -> None:
    host.orchestrator_logs = {"2h": rc31_hourly(), "30h": rc31_d1()}
    result = host.run(TAG)

    assert result.returncode == 0, result.combined
    assert result.detail("cadence_hourly_discharges", "source") == RC31_SOURCE
    assert result.detail("cadence_d1_recovery", "source") == RC31_SOURCE


def test_rc31_blocks_are_tolerant_to_container_log_prefix(host: SyntheticHost) -> None:
    host.compose_log_prefix = "sirhosp-census-orchestrator-1  | "
    host.orchestrator_logs = {"2h": rc31_hourly(), "30h": rc31_d1()}
    result = host.run(TAG)

    assert result.returncode == 0, result.combined
    assert result.detail("cadence_hourly_discharges", "source") == RC31_SOURCE
    assert result.detail("cadence_d1_recovery", "source") == RC31_SOURCE


def test_rc31_mixed_blocks_can_satisfy_each_cadence_independently(
    host: SyntheticHost,
) -> None:
    # The 30h window naturally also carries hourly blocks; an extra hourly
    # block must not invalidate the isolated D-1 block placed before it.
    host.orchestrator_logs = {"2h": rc31_hourly(), "30h": rc31_d1() + rc31_hourly()}
    result = host.run(TAG)

    assert result.returncode == 0, result.combined
    assert result.status_for("cadence_hourly_discharges") == "PASS"
    assert result.status_for("cadence_d1_recovery") == "PASS"


# ---------------------------------------------------------------------------
# R6 — adversarial RC31 variants all fail closed
# ---------------------------------------------------------------------------


def test_isolated_finish_does_not_prove_hourly(host: SyntheticHost) -> None:
    host.orchestrator_logs["2h"] = [HOURLY_FINISH_MESSAGE]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_hourly_discharges") == "FAIL"


def test_isolated_dispatch_and_summary_do_not_prove_d1(host: SyntheticHost) -> None:
    host.orchestrator_logs["30h"] = [D1_DISPATCH_MESSAGE, D1_SUMMARY_MESSAGE]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_d1_recovery") == "FAIL"


def test_broken_rc31_order_fails_closed(host: SyntheticHost) -> None:
    host.orchestrator_logs["2h"] = [
        HOURLY_START_MESSAGE,
        HOURLY_SUMMARY_MESSAGE,
        HOURLY_DISPATCH_MESSAGE,
        HOURLY_FINISH_MESSAGE,
    ]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_hourly_discharges") == "FAIL"


def test_rc31_blocks_cannot_combine_pieces_from_different_modes(
    host: SyntheticHost,
) -> None:
    host.orchestrator_logs["2h"] = [
        HOURLY_START_MESSAGE,
        D1_DISPATCH_MESSAGE,
        D1_SUMMARY_MESSAGE,
        HOURLY_FINISH_MESSAGE,
    ]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_hourly_discharges") == "FAIL"


def test_rc31_blocks_cannot_combine_pieces_from_different_runs(
    host: SyntheticHost,
) -> None:
    host.orchestrator_logs["2h"] = [
        HOURLY_START_MESSAGE,
        HOURLY_DISPATCH_MESSAGE,
        HOURLY_START_MESSAGE,
        HOURLY_SUMMARY_MESSAGE,
        HOURLY_FINISH_MESSAGE,
    ]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_hourly_discharges") == "FAIL"


def test_rc31_summary_with_failures_fails_closed(host: SyntheticHost) -> None:
    host.orchestrator_logs["2h"] = [
        HOURLY_START_MESSAGE,
        HOURLY_DISPATCH_MESSAGE,
        "Days: 1 | Steps: 1 | Succeeded: 0 | Failed: 1 | Skipped: 0",
        HOURLY_FINISH_MESSAGE,
    ]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_hourly_discharges") == "FAIL"


def test_rc31_d1_summary_of_three_of_four_fails_closed(host: SyntheticHost) -> None:
    host.orchestrator_logs["30h"] = [
        D1_START_MESSAGE,
        D1_DISPATCH_MESSAGE,
        "Days: 1 | Steps: 4 | Succeeded: 3 | Failed: 1 | Skipped: 0",
        D1_FINISH_MESSAGE,
    ]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_d1_recovery") == "FAIL"


def test_rc31_d1_summary_with_skip_fails_closed(host: SyntheticHost) -> None:
    host.orchestrator_logs["30h"] = [
        D1_START_MESSAGE,
        D1_DISPATCH_MESSAGE,
        "Days: 1 | Steps: 4 | Succeeded: 3 | Failed: 0 | Skipped: 1",
        D1_FINISH_MESSAGE,
    ]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_d1_recovery") == "FAIL"


def test_rc31_d1_without_deaths_fails_closed(host: SyntheticHost) -> None:
    host.orchestrator_logs["30h"] = [
        D1_START_MESSAGE,
        "exit_reconciliation_runtime: mode=d1 date=24/09/2026 "
        "extractors=discharges,admissions,official_census",
        D1_SUMMARY_MESSAGE,
        D1_FINISH_MESSAGE,
    ]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_d1_recovery") == "FAIL"


def test_rc31_hourly_dispatch_directory_with_extra_extractor_fails_closed(
    host: SyntheticHost,
) -> None:
    host.orchestrator_logs["2h"] = [
        HOURLY_START_MESSAGE,
        "exit_reconciliation_runtime: mode=hourly date=25/09/2026 "
        "extractors=discharges,admissions",
        HOURLY_SUMMARY_MESSAGE,
        HOURLY_FINISH_MESSAGE,
    ]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_hourly_discharges") == "FAIL"


def test_interleaved_blocks_fail_closed(host: SyntheticHost) -> None:
    host.orchestrator_logs["2h"] = rc31_hourly()
    host.orchestrator_logs["30h"] = [
        D1_START_MESSAGE,
        D1_DISPATCH_MESSAGE,
        HOURLY_START_MESSAGE,
        HOURLY_DISPATCH_MESSAGE,
        HOURLY_SUMMARY_MESSAGE,
        HOURLY_FINISH_MESSAGE,
        D1_SUMMARY_MESSAGE,
        D1_FINISH_MESSAGE,
    ]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_d1_recovery") == "FAIL"
    assert result.status_for("cadence_hourly_discharges") == "PASS"


# ---------------------------------------------------------------------------
# R7 — read-only Docker interface and no mutating verbs
# ---------------------------------------------------------------------------


def test_script_uses_only_the_closed_read_only_docker_helper() -> None:
    text = script_text()
    docker_lines = [line for line in non_comment_lines(text) if line.startswith("docker ")]
    assert len(docker_lines) == 1, docker_lines
    assert docker_lines[0].startswith("docker compose"), docker_lines[0]
    assert "${subcommand}" in docker_lines[0], docker_lines[0]

    calls = docker_query_calls(text)
    assert calls, "the closed docker_query helper must be used"
    assert set(calls) <= ALLOWED_DOCKER_SUBCOMMANDS, calls
    assert "ps|logs)" in text, "the Docker helper must gate its subcommands"

    for line in non_comment_lines(text):
        match = re.match(r"docker_query\s+(\S+)", line)
        if match:
            assert match.group(1) in ALLOWED_DOCKER_SUBCOMMANDS, line


def test_script_contains_no_mutating_docker_or_django_command() -> None:
    text = script_text()
    for line in code_lines(text):
        for pattern in FORBIDDEN_CODE_PATTERNS:
            assert not re.search(pattern, line), f"forbidden command in: {line!r}"
    lowered = "\n".join(non_comment_lines(text))
    for verb in FORBIDDEN_DOCKER_SUBCOMMANDS:
        assert not re.search(rf"\bcompose\s+{verb}\b", lowered), verb


def test_docker_shim_cannot_reach_a_real_daemon(host: SyntheticHost) -> None:
    assert "docker.sock" not in DOCKER_SHIM
    assert "subprocess" not in DOCKER_SHIM
    assert "socket" not in DOCKER_SHIM

    for verb in ("exec", "run", "up", "start", "restart", "stop", "inspect"):
        completed = host.run_raw_docker("compose", verb, ORCHESTRATOR_SERVICE)
        assert completed.returncode != 0, verb
        assert "refused subcommand" in completed.stderr, verb


def test_successful_run_only_ever_issues_read_only_docker_queries(
    host: SyntheticHost,
) -> None:
    result = host.run(TAG)

    assert result.returncode == 0, result.combined
    calls = result.call_lines("docker")
    assert calls, "the orchestrator logs must be queried"
    seen: set[str] = set()
    for line in calls:
        tokens = line.split()
        assert tokens[0] == "compose", line
        for token in tokens:
            if token in FORBIDDEN_DOCKER_SUBCOMMANDS:
                raise AssertionError(f"mutating docker verb: {line}")
            if token in ALLOWED_DOCKER_SUBCOMMANDS:
                seen.add(token)
    assert seen == ALLOWED_DOCKER_SUBCOMMANDS


def test_script_uses_only_read_only_systemd_verbs_and_safe_curl() -> None:
    text = script_text()
    calls = re.findall(r"systemctl_state\s+([a-z][a-z-]*)", text)
    assert calls, "the read-only systemctl helper must be used"
    assert set(calls) <= READ_ONLY_SYSTEMCTL_VERBS

    for line in code_lines(text):
        for verb in MUTATING_SYSTEMD_VERBS:
            assert not re.search(rf"(?<![\w-]){re.escape(verb)}(?![\w-])", line), (
                f"mutating systemd verb {verb!r} in: {line!r}"
            )
        for pattern in FORBIDDEN_CURL_PATTERNS:
            assert not re.search(pattern, line), f"mutating curl flag in: {line!r}"
        assert "--vacuum" not in line
        assert "--rotate" not in line


# ---------------------------------------------------------------------------
# R8 — aggregated, allowlisted evidence without raw log content
# ---------------------------------------------------------------------------


def test_records_use_only_allowlisted_keys(host: SyntheticHost) -> None:
    scenarios = []

    scenarios.append(host.run(TAG))

    host.corrupt_local_asset(HOURLY_TIMER)
    scenarios.append(host.run(TAG))

    host.orchestrator_logs = {"2h": [], "30h": []}
    scenarios.append(host.run(TAG))

    for result in scenarios:
        assert_allowlisted_output(result)
        assert_no_secret_or_clinical_content(result)
        assert_no_raw_marker(result)
        assert result.stdout.strip(), "every scenario must emit records"


def test_orchestrator_log_content_is_never_reproduced(host: SyntheticHost) -> None:
    result = host.run(TAG)

    assert result.returncode == 0
    assert "prontuario" not in result.combined
    assert "NOME SOBRENOME" not in result.combined
    assert "queue drained and batch closed" not in result.combined
    assert "exit_reconciliation_runtime" not in result.combined
    assert "Succeeded:" not in result.combined


def test_env_secrets_never_reach_the_output(host: SyntheticHost) -> None:
    host.corrupt_local_asset(HOURLY_TIMER)
    result = host.run(TAG)

    assert result.returncode != 0
    assert_no_secret_or_clinical_content(result)
    assert f"tag={TAG}" in result.combined


# ---------------------------------------------------------------------------
# R9 — read-only execution leaves the fixtures untouched
# ---------------------------------------------------------------------------


def test_successful_run_leaves_the_host_untouched(host: SyntheticHost) -> None:
    host.materialize()
    before = host_state(host)

    result = host.run(TAG)

    assert result.returncode == 0, result.combined
    assert host_state(host) == before
    verbs = {
        line.split()[0]
        for line in result.call_lines("systemctl")
        if line.split()
    }
    assert verbs <= READ_ONLY_SYSTEMCTL_VERBS
    assert result.call_lines("docker"), "the Compose log predicates must be queried"


def test_failed_run_reports_no_remediation_attempt(host: SyntheticHost) -> None:
    host.orchestrator_logs = {"2h": [], "30h": []}
    result = host.run(TAG)

    assert result.returncode == 1
    assert result.status_for("cadence_hourly_discharges") == "FAIL"
    verbs = {
        line.split()[0]
        for line in result.call_lines("systemctl")
        if line.split()
    }
    assert verbs <= READ_ONLY_SYSTEMCTL_VERBS


def test_failed_run_leaves_the_host_untouched(host: SyntheticHost) -> None:
    host.orchestrator_logs = {"2h": [], "30h": []}
    host.materialize()
    before = host_state(host)

    result = host.run(TAG)

    assert result.returncode == 1
    assert host_state(host) == before


def test_temporary_workspace_is_removed_by_the_trap(host: SyntheticHost) -> None:
    result = host.run(TAG)

    assert result.returncode == 0, result.combined
    assert list(host.tmp_work_dir.iterdir()) == []


def test_failure_exit_code_is_nonzero_and_reasons_are_enumerated(
    host: SyntheticHost,
) -> None:
    host.env_lines = [f"SIRHOSP_VERSION={TAG}"]
    host.orchestrator_logs = {"2h": [], "30h": []}
    result = host.run(TAG)

    assert result.returncode == 1
    assert result.reasons() >= {
        "env_value_missing",
        "cadence_stale",
    }
    assert re.search(r"failures=\d+", result.records[-1])


# ---------------------------------------------------------------------------
# Harness contract
# ---------------------------------------------------------------------------


def test_harness_overrides_every_production_input() -> None:
    text = script_text()
    for variable in (
        "HOSPITAL_DIR",
        "SYSTEMD_UNIT_DIR",
        "RELEASE_BASE_URL",
        "RELEASE_API_URL",
    ):
        assert re.search(rf'^{variable}="\$\{{{variable}:-[^"}}]+\}}"$', text, re.M), (
            f"{variable} must keep an overridable production default"
        )

    harness = Path(__file__).read_text(encoding="utf-8")
    for variable in (
        "HOSPITAL_DIR",
        "SYSTEMD_UNIT_DIR",
        "RELEASE_BASE_URL",
        "RELEASE_API_URL",
    ):
        assert f'"{variable}":' in harness, f"harness must override {variable}"


def test_release_endpoints_target_the_hospital_image_repository() -> None:
    compose = COMPOSE_SOURCE.read_text(encoding="utf-8")
    match = re.search(r"image: ghcr\.io/([^:]+):", compose)
    assert match, "hospital Compose must pin the release image repository"
    slug = match.group(1)
    text = script_text()

    assert f"/{slug}/releases/download" in text
    assert f"/repos/{slug}/releases/tags" in text


def test_preflight_reuses_the_same_compose_asset_name() -> None:
    compose = COMPOSE_SOURCE
    assert compose.is_file()
    text = script_text()
    assert f'COMPOSE_ASSET="{compose.name}"' in text


def test_test_module_never_references_a_production_path() -> None:
    text = Path(__file__).read_text(encoding="utf-8")

    # Split so the needles are never contiguous literals in this file.
    for forbidden in ("/srv" + "/apps", "/etc" + "/systemd", "git" + "hub"):
        assert forbidden not in text, f"tests must stay synthetic: {forbidden!r}"
