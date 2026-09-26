"""Synthetic host-level contract tests for the daily-statistics preflight.

The preflight is the read-only, fail-closed checkpoint executed on the hospital
host before the human activation checkpoint of
``sirhosp-daily-statistics.timer``. This suite pins, without touching any real
production surface:

- R1: the preflight requires one exact release tag, refuses tags that are not
  published and immutable, and compares every required release asset byte by
  byte with the installed copy (the preflight itself and the scheduler under
  the hospital ``deploy/`` directory, plus the finalization and exit-cadence
  systemd units); the configured image tag is proven by ``SIRHOSP_VERSION``
  equality because the image is never downloaded or inspected here;
- R2: only ``SIRHOSP_VERSION`` and ``STATISTICS_ACTIVATION_DATE`` are read from
  the hospital ``.env`` (never sourced), duplicate or ambiguous declarations
  are refused and the activation date must be valid and strictly future in
  ``America/Bahia``;
- R3: the finalization timer must still be disabled and inactive, the upstream
  timers enabled and active, and the aggregated scheduler markers
  ``mode=hourly-discharges result=success`` (2 hours) and
  ``mode=d1-recovery result=success`` (30 hours) must exist in the journal of
  the release-identical runtime that dispatches the canonical four-extractor
  D-1 execution;
- R4: the journal is queried silently and only allowlisted technical records
  are printed — never raw journal messages, ``.env`` secrets or clinical
  identity;
- R5: the script executes no mutating command and leaves the host state
  untouched;
- R6: every scenario runs against fixtures, temporary directories and command
  doubles (``curl``, ``systemctl``, ``journalctl``, ``date``) on ``PATH``; no
  network, Docker, systemd, journal or production path is used.
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
SYSTEMD_SOURCE = ROOT / "deploy" / "systemd"

TAG = "v1.0.0-rc.1"
OTHER_TAG = "v1.0.0-rc.2"
FAKE_TODAY = "2026-09-25"
FUTURE_ACTIVATION_DATE = "2026-10-01"
PAST_ACTIVATION_DATE = "2026-09-24"

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
REQUIRED_ASSETS = (SCHEDULER_ASSET, PREFLIGHT_ASSET, *UNIT_ASSETS)
SCHEDULER_DEPLOYED_ASSETS = (SCHEDULER_ASSET, PREFLIGHT_ASSET)

HOURLY_MARKER = "mode=hourly-discharges result=success"
D1_MARKER = "mode=d1-recovery result=success"
HOURLY_WINDOW = "-2 hours"
D1_WINDOW = "-30 hours"

SECRET_VALUE = "cli-secret-value-must-not-leak"
CLINICAL_MESSAGE = "paciente NOME SOBRENOME prontuario 123456 leito 12A"

RECORD_RE = re.compile(
    r"^\[preflight\] check=[a-z0-9_]+ status=(?:PASS|FAIL)(?: [a-z_]+=\S+)*$"
)
RESULT_RE = re.compile(
    r"^\[preflight\] result=(?:PASS|FAIL) tag=\S+(?: (?:checks|failures)=\d+)?$"
)

# R5: no mutating, extractive or database command may be executed by the
# preflight. Quoted literals are stripped before this scan because the script
# legitimately keeps the canonical runtime dispatch string as a ``grep -F``
# predicate; only executable code positions are checked.
FORBIDDEN_CODE_PATTERNS = (
    r"\bsystemctl\s+(?:enable|disable|start|stop|restart|reload|daemon-reload|mask|unmask|link)\b",
    r"\bdocker\b",
    r"\bcompose\b",
    r"manage\.py",
    r"\bpsql\b",
    r"\bpg_dump\b",
    r"\bbackfill\b",
    r"materialize_daily_statistics",
    r"\bextract_[a-z_]+",
    r"\brecover_historical_data\b",
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
"""Command double for ``journalctl``: replays synthetic per-unit journals."""
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
    failed = os.environ.get("FAKE_JOURNAL_FAIL_UNITS", "")
    if unit and unit in failed.split(","):
        sys.stderr.write("journalctl: synthetic journal unavailable\\n")
        return 1
    source = pathlib.Path(os.environ["FAKE_JOURNAL_DIR"]) / (unit + ".log")
    if source.is_file():
        sys.stdout.write(source.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

DATE_SHIM = '''#!/usr/bin/env python3
"""Command double for ``date``: pins "today" and defers everything else.

Only the ``+%F`` "today" query is fixed; calendar-date validation queries
(``-d``) are delegated to the real binary so the script's own round-trip check
keeps being exercised.
"""
import os
import sys

REAL_CANDIDATES = ("/usr/bin/date", "/bin/date")


def main() -> int:
    args = sys.argv[1:]
    log = os.environ.get("FAKE_DATE_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(" ".join(args) + "\\n")
    if list(args) == ["+%F"]:
        print(os.environ.get("FAKE_TODAY", "2026-09-25"))
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
    """Synthetic hospital host: release, installed assets, units and journal."""

    def __init__(self, root: Path) -> None:
        assert PREFLIGHT.exists(), "daily-statistics activation preflight must exist"
        self.root = root
        self.hospital = root / "srv" / "apps" / "prisma"
        self.deploy_dir = self.hospital / "deploy"
        self.systemd_dir = root / "etc-systemd"
        self.release_dir = root / "release"
        self.release_assets_dir = self.release_dir / "assets"
        self.journal_dir = root / "journal"
        self.logs_dir = root / "logs"
        self.shims_dir = root / "shims"
        self.state_file = root / "systemd-state.txt"
        for directory in (
            self.deploy_dir,
            self.systemd_dir,
            self.release_assets_dir,
            self.journal_dir,
            self.logs_dir,
            self.shims_dir,
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
            HOURLY_TIMER: ("enabled", "active"),
            D1_TIMER: ("enabled", "active"),
        }
        self.journal_lines: dict[str, list[str]] = {
            HOURLY_SERVICE: [
                f"[exit-reconciliation] 2026-09-25 12:13:01 -0300 {HOURLY_MARKER}",
                f"MESSAGE={CLINICAL_MESSAGE}",
            ],
            D1_SERVICE: [
                f"[exit-reconciliation] 2026-09-25 05:00:03 -0300 {D1_MARKER}",
            ],
        }
        self.journal_unavailable_units: set[str] = set()
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
        if asset == SCHEDULER_ASSET:
            return SCHEDULER_SOURCE.read_bytes()
        if asset == PREFLIGHT_ASSET:
            return PREFLIGHT.read_bytes()
        return (SYSTEMD_SOURCE / asset).read_bytes()

    def local_path(self, asset: str) -> Path:
        if asset in SCHEDULER_DEPLOYED_ASSETS:
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

    def corrupt_release_and_local_asset(self, asset: str) -> None:
        suffix = b"# tampered release asset\n"
        release_path = self.release_assets_dir / asset
        release_path.write_bytes(release_path.read_bytes() + suffix)
        local_path = self.local_path(asset)
        local_path.write_bytes(local_path.read_bytes() + suffix)

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
        release = dict(self.release_meta)
        release["assets"] = [{"name": name} for name in self.release_asset_names]
        if not self.suppress_release_json:
            (self.release_dir / "release.json").write_text(
                json.dumps(release), encoding="utf-8"
            )

    def _reset_logs(self) -> None:
        for path in self.logs_dir.glob("*.log"):
            path.unlink()

    def run(
        self, *args: str, extra_env: dict[str, str] | None = None
    ) -> PreflightRun:
        self.materialize()
        self._reset_logs()
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.shims_dir}{os.pathsep}{env.get('PATH', '')}",
                "HOSPITAL_DIR": str(self.hospital),
                "SYSTEMD_UNIT_DIR": str(self.systemd_dir),
                "RELEASE_BASE_URL": self.release_base_url,
                "RELEASE_API_URL": self.release_api_url,
                "FAKE_RELEASE_DIR": str(self.release_dir),
                "FAKE_JOURNAL_DIR": str(self.journal_dir),
                "FAKE_JOURNAL_FAIL_UNITS": ",".join(
                    sorted(self.journal_unavailable_units)
                ),
                "FAKE_SYSTEMD_STATE": str(self.state_file),
                "FAKE_TODAY": FAKE_TODAY,
                "FAKE_CURL_LOG": str(self.logs_dir / "curl.log"),
                "FAKE_SYSTEMCTL_LOG": str(self.logs_dir / "systemctl.log"),
                "FAKE_JOURNALCTL_LOG": str(self.logs_dir / "journalctl.log"),
                "FAKE_DATE_LOG": str(self.logs_dir / "date.log"),
            }
        )
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


def host_state(host: SyntheticHost) -> dict[str, bytes]:
    state: dict[str, bytes] = {}
    for base in (
        host.hospital,
        host.systemd_dir,
        host.journal_dir,
        host.release_dir,
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
    assert result.status_for("daily_timer_state") == "PASS"
    assert result.status_for("upstream_timer_state", HOURLY_TIMER) == "PASS"
    assert result.status_for("upstream_timer_state", D1_TIMER) == "PASS"
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
    for args in ((), (TAG, "extra"), ("../evil",), ("v1/evil",), ("-v1.0.0-rc.1",), ("..",)):
        result = host.run(*args)
        assert result.returncode == 2, f"args {args!r} must be refused: {result.combined}"
        assert result.records == []
        assert result.call_lines("curl") == []
        assert result.call_lines("systemctl") == []
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


# ---------------------------------------------------------------------------
# R2 — allowlisted .env keys and strictly future activation date
# ---------------------------------------------------------------------------


def test_activation_date_must_be_strictly_future(host: SyntheticHost) -> None:
    for unsafe_date in (FAKE_TODAY, PAST_ACTIVATION_DATE):
        host.env_lines = [
            line
            for line in host.env_lines
            if not line.startswith("STATISTICS_ACTIVATION_DATE=")
        ] + [f"STATISTICS_ACTIVATION_DATE={unsafe_date}"]
        result = host.run(TAG)
        assert_failed(result, "activation_date_not_future")
        assert result.status_for("activation_date") == "FAIL"
        # The remaining read-only checks still run, so the artifact carries the
        # complete diagnostic set; only read-only verbs are ever used.
        assert result.status_for("daily_timer_state") == "PASS"
        verbs = {line.split()[0] for line in result.call_lines("systemctl") if line.split()}
        assert verbs <= READ_ONLY_SYSTEMCTL_VERBS


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


def test_duplicate_env_declaration_fails_closed(host: SyntheticHost) -> None:
    host.env_lines = host.env_lines + [f"SIRHOSP_VERSION={TAG}"]
    result = host.run(TAG)

    assert_failed(result, "env_value_duplicate")
    assert result.status_for("image_version") == "FAIL"


@pytest.mark.parametrize(
    "declaration",
    [
        'SIRHOSP_VERSION="v1.0.0-rc.1"',
        " SIRHOSP_VERSION=v1.0.0-rc.1",
        "SIRHOSP_VERSION = v1.0.0-rc.1",
        "SIRHOSP_VERSION=v1.0.0-rc.1 # latest",
        "export SIRHOSP_VERSION=v1.0.0-rc.1",
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
# R3 — disabled baseline, upstream timers and recent cadence evidence
# ---------------------------------------------------------------------------


def test_journal_windows_match_the_documented_freshness_bounds(
    host: SyntheticHost,
) -> None:
    result = host.run(TAG)

    hourly_calls = [
        line for line in result.call_lines("journalctl") if f"-u {HOURLY_SERVICE}" in line
    ]
    d1_calls = [
        line for line in result.call_lines("journalctl") if f"-u {D1_SERVICE}" in line
    ]
    assert len(hourly_calls) == 1
    assert len(d1_calls) == 1
    assert f"--since {HOURLY_WINDOW}" in hourly_calls[0]
    assert f"--since {D1_WINDOW}" in d1_calls[0]
    for line in hourly_calls + d1_calls:
        assert "--no-pager" in line


def test_stale_hourly_cadence_fails_closed(host: SyntheticHost) -> None:
    host.journal_lines[HOURLY_SERVICE] = [
        "[exit-reconciliation] 2026-09-20 12:13:01 -0300 mode=hourly-discharges result=failed"
    ]
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_hourly_discharges") == "FAIL"
    assert result.status_for("upstream_timer_state", HOURLY_TIMER) == "PASS"


def test_stale_d1_cadence_fails_closed(host: SyntheticHost) -> None:
    host.journal_lines[D1_SERVICE] = []
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("cadence_d1_recovery") == "FAIL"
    assert result.detail("cadence_d1_recovery", "window") == "30h"


def test_enabled_active_timers_do_not_substitute_recent_success(
    host: SyntheticHost,
) -> None:
    host.journal_lines = {}
    result = host.run(TAG)

    assert_failed(result, "cadence_stale")
    assert result.status_for("upstream_timer_state", HOURLY_TIMER) == "PASS"
    assert result.status_for("upstream_timer_state", D1_TIMER) == "PASS"


def test_unavailable_journal_fails_closed(host: SyntheticHost) -> None:
    host.journal_unavailable_units.add(HOURLY_SERVICE)
    result = host.run(TAG)

    assert_failed(result, "journal_unavailable")
    assert result.status_for("cadence_hourly_discharges") == "FAIL"
    assert result.status_for("cadence_d1_recovery") == "PASS"


def test_enabled_finalization_timer_fails_closed(host: SyntheticHost) -> None:
    host.unit_states[DAILY_TIMER] = ("enabled", "inactive")
    result = host.run(TAG)

    assert_failed(result, "timer_not_disabled")
    assert result.status_for("daily_timer_state") == "FAIL"


def test_active_finalization_timer_fails_closed(host: SyntheticHost) -> None:
    host.unit_states[DAILY_TIMER] = ("disabled", "active")
    result = host.run(TAG)

    assert_failed(result, "timer_not_inactive")


@pytest.mark.parametrize(("enabled", "active"), [("disabled", "active"), ("enabled", "inactive")])
def test_upstream_timer_must_be_enabled_and_active(
    host: SyntheticHost, enabled: str, active: str
) -> None:
    host.unit_states[HOURLY_TIMER] = (enabled, active)
    result = host.run(TAG)

    if enabled != "enabled":
        assert_failed(result, "upstream_timer_not_enabled")
    else:
        assert_failed(result, "upstream_timer_not_active")
    assert result.status_for("upstream_timer_state", HOURLY_TIMER) == "FAIL"
    assert result.status_for("upstream_timer_state", D1_TIMER) == "PASS"


def test_unloaded_unit_state_fails_closed(host: SyntheticHost) -> None:
    host.unit_states.pop(HOURLY_TIMER)
    result = host.run(TAG)

    assert_failed(result, "unit_state_unavailable")
    assert result.status_for("upstream_timer_state", HOURLY_TIMER) == "FAIL"


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
# R4 — aggregated, allowlisted evidence without journal content
# ---------------------------------------------------------------------------


def test_records_use_only_allowlisted_keys(host: SyntheticHost) -> None:
    scenarios = []

    scenarios.append(host.run(TAG))

    host.corrupt_local_asset(HOURLY_TIMER)
    scenarios.append(host.run(TAG))

    host.journal_lines = {}
    scenarios.append(host.run(TAG))

    for result in scenarios:
        assert_allowlisted_output(result)
        assert_no_secret_or_clinical_content(result)
        assert result.stdout.strip(), "every scenario must emit records"


def test_journal_content_is_never_reproduced(host: SyntheticHost) -> None:
    result = host.run(TAG)

    assert result.returncode == 0
    assert "prontuario" not in result.combined
    assert "NOME SOBRENOME" not in result.combined
    assert HOURLY_MARKER not in result.combined, (
        "even the aggregated marker is only a predicate, never echoed"
    )


def test_env_secrets_never_reach_the_output(host: SyntheticHost) -> None:
    host.corrupt_local_asset(HOURLY_TIMER)
    result = host.run(TAG)

    assert result.returncode != 0
    assert_no_secret_or_clinical_content(result)
    assert f"tag={TAG}" in result.combined


# ---------------------------------------------------------------------------
# R5 — read-only, no remediation
# ---------------------------------------------------------------------------


def test_script_executes_no_mutating_or_extractive_command() -> None:
    for line in code_lines(script_text()):
        for pattern in FORBIDDEN_CODE_PATTERNS:
            assert not re.search(pattern, line), f"forbidden command in: {line!r}"


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
    assert result.call_lines("journalctl"), "the journal predicates must be queried"


def test_failed_run_reports_no_remediation_attempt(host: SyntheticHost) -> None:
    host.journal_lines = {}
    result = host.run(TAG)

    assert result.returncode == 1
    assert result.status_for("cadence_hourly_discharges") == "FAIL"
    verbs = {
        line.split()[0]
        for line in result.call_lines("systemctl")
        if line.split()
    }
    assert verbs <= READ_ONLY_SYSTEMCTL_VERBS


def test_failure_exit_code_is_nonzero_and_reasons_are_enumerated(
    host: SyntheticHost,
) -> None:
    host.env_lines = [f"SIRHOSP_VERSION={TAG}"]
    host.journal_lines = {}
    result = host.run(TAG)

    assert result.returncode == 1
    assert result.reasons() >= {
        "env_value_missing",
        "cadence_stale",
    }
    assert re.search(r"failures=\d+", result.records[-1])


# ---------------------------------------------------------------------------
# R6 — synthetic fixtures and command doubles only
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
    compose = (ROOT / "compose.hospital.yml").read_text(encoding="utf-8")
    match = re.search(r"image: ghcr\.io/([^:]+):", compose)
    assert match, "hospital Compose must pin the release image repository"
    slug = match.group(1)
    text = script_text()

    assert f"/{slug}/releases/download" in text
    assert f"/repos/{slug}/releases/tags" in text


def test_test_module_never_references_a_production_path() -> None:
    text = Path(__file__).read_text(encoding="utf-8")

    # Split so the needles are never contiguous literals in this file.
    for forbidden in ("/srv" + "/apps", "/etc" + "/systemd", "git" + "hub"):
        assert forbidden not in text, f"tests must stay synthetic: {forbidden!r}"
