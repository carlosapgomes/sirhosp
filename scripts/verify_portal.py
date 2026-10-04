#!/usr/bin/env python3
"""Dev verification controller for ephemeral portal accounts."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import math
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

STATE_ROOT = Path.home() / ".local" / "state" / "sirhosp-verification"

DEV_SOCKET = "unix:///run/user/1003/docker.sock"
FORBIDDEN_SOCKETS = frozenset({"unix:///run/user/1002/docker.sock"})
DEV_PROJECT = "sirhosp"
DEV_CHECKOUT = Path("/projects/dev/sirhosp")
DEV_VOLUME = "sirhosp_sirhosp_db_data"
DEV_DB_CONTAINER = "sirhosp-db"
DEV_WEB_CONTAINER = "sirhosp-web"
DEV_PG_DATA = "/var/lib/postgresql/data"
DEV_NETWORK = "sirhosp_default"
DEV_DB_PORT = 5432
PYTHON_BIN = "/opt/venv/bin/python"
ALLOWED_ACTIONS = frozenset({"preflight", "owned-status", "prepare", "open", "close", "recover"})
RUN_RE = re.compile(r"[0-9a-f]{32}\Z")
SNAPSHOT_RE = re.compile(r"[0-9a-f]{64}\Z")
FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}\Z")
# Mirrors the owned domain stamp format (TOKEN_PATTERN in
# apps/accounts/verification.py): the run id embedded in the stamp is the
# generation identity the database itself attests.
TOKEN_STAMP_RE = re.compile(r"vfy[PAR]:([0-9a-f]{32}):[0-9a-f]{32}\Z")


class Blocked(Exception):
    pass


class Failure(Exception):
    pass


@dataclass(frozen=True)
class ClosedRecord:
    state: str
    target: str
    last_run_id: str | None


@dataclass(frozen=True)
class OpeningRecord:
    state: str
    target: str
    run_id: str
    deadline_iso: str
    timer_unit: str
    expect_state: str


@dataclass(frozen=True)
class ActiveRecord:
    state: str
    target: str
    run_id: str
    deadline_iso: str
    timer_unit: str
    pair_ids: tuple[int, int]


@dataclass(frozen=True)
class ClosingRecord:
    state: str
    target: str
    run_id: str
    diagnostic: str | None


@dataclass(frozen=True)
class DoctorReport:
    status: str
    diagnostic: str | None = None


@dataclass(frozen=True)
class OpenCredentials:
    run_id: str
    passwords: dict[str, str] = field(repr=False)
    target: str = "dev"


@dataclass(frozen=True)
class Verdict:
    status: str
    revoked: bool = False
    diagnostic: str | None = None


@dataclass(frozen=True)
class StatusReport:
    state: str
    target: str
    run_id: str | None = None


@dataclass(frozen=True)
class Target:
    slug: str
    fingerprint: str
    web_running: bool
    compose: list[str]
    docker_host: str = DEV_SOCKET
    checkout: str = str(DEV_CHECKOUT)
    volume: str = DEV_VOLUME
    db_address: str | None = None
    db_port: int | None = None


def _state_dir(slug: str) -> Path:
    return STATE_ROOT / slug


def _state_path(slug: str) -> Path:
    return _state_dir(slug) / "session.json"


def _lock_path(slug: str) -> Path:
    return _state_dir(slug) / ".lock"


def _timer_base(run_id: str) -> str:
    if not RUN_RE.fullmatch(run_id):
        raise Blocked("run-id required for timer ownership")
    return f"sirhosp-verify-{run_id}"


def _owned_timer_name(timer_unit: str, run_id: str) -> str:
    base = _timer_base(run_id)
    if timer_unit != base and timer_unit != base + ".timer" and timer_unit != base + ".service":
        raise Blocked(f"foreign timer unit {timer_unit}")
    return base


def _unit_object_path(unit: str) -> str:
    escaped = []
    for byte in unit.encode():
        ch = chr(byte)
        if ch.isascii() and (ch.isalnum() or ch == "_"):
            escaped.append(ch)
        else:
            escaped.append(f"_{byte:02x}")
    return "/org/freedesktop/systemd1/unit/" + "".join(escaped)


def _callback_argv(checkout: str, run_id: str) -> list[str]:
    import sys

    exe = sys.executable
    if not os.path.isabs(exe) or not os.path.isfile(exe):
        raise Blocked("callback interpreter unverified")
    if not RUN_RE.fullmatch(run_id):
        raise Blocked("run-id required for timer ownership")
    script = str(Path(checkout) / "scripts" / "verify_portal.py")
    return [exe, script, "callback", "--target", "dev", "--run-id", run_id]


def _require_revoked(result: object) -> dict:
    if not isinstance(result, dict) or result.get("revoked") is not True:
        raise Failure("revocation unverified")
    return result


def _now() -> float:
    return time.time()


def _deadline_lease(timeout_min: int) -> tuple[int, str]:
    deadline_ts = math.ceil(_now() + timeout_min * 60)
    deadline_iso = datetime.fromtimestamp(deadline_ts, tz=timezone.utc).isoformat()
    return deadline_ts, deadline_iso


def _show_value(target: Target, unit: str, prop: str) -> str:
    output = _command(["systemctl", "--user", "show", unit, "-p", prop, "--value"])
    return output.strip()


def _validate_target(name: str) -> None:
    if name != "dev":
        raise Blocked(f"unexpected target {name}")


def _expected_config_files(checkout: Path) -> list[str]:
    return [str(checkout / "compose.yml"), str(checkout / "compose.dev.yml")]


def _parse_config_files(value: object) -> list[str] | None:
    if not isinstance(value, str):
        return None
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(not part for part in parts):
        return None
    return parts


def _has_exact_port(net_ports: object, wanted: str = "5432/tcp") -> bool:
    if not isinstance(net_ports, str):
        return False
    tokens = [token.strip() for token in net_ports.replace(",", " ").split()]
    return wanted in tokens


def _as_port(value: object) -> int:
    if isinstance(value, bool):
        raise Blocked("database port invalid")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise Blocked("database port invalid")
        number = int(text)
    else:
        raise Blocked("database port invalid")
    if number < 1 or number > 65535:
        raise Blocked("database port invalid")
    return number


def _docker_host() -> str:
    host = os.environ.get("DOCKER_HOST", DEV_SOCKET)
    if host in FORBIDDEN_SOCKETS or host != DEV_SOCKET:
        raise Blocked(f"unexpected docker engine {host}")
    return host


def _parse_ps_table(output: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in output.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 6:
            continue
        name, service, project, state, working_dir, config_files = parts
        if not name:
            continue
        rows[name] = {
            "service": service,
            "project": project,
            "state": state,
            "working_dir": working_dir,
            "config_files": config_files,
        }
    return rows


def _verified_checkout() -> Path:
    candidate = DEV_CHECKOUT
    compose = candidate / "compose.yml"
    override = candidate / "compose.dev.yml"
    if not compose.is_file() or not override.is_file():
        raise Blocked("dev checkout not verified")
    try:
        base = compose.read_text()
        dev = override.read_text()
    except OSError:
        raise Blocked("dev checkout not verified") from None
    if "sirhosp_db_data" not in base:
        raise Blocked("dev checkout not verified")
    if "sirhosp-web" not in dev:
        raise Blocked("dev checkout not verified")
    return candidate


def _resolve_target(name: str) -> Target:
    _validate_target(name)
    docker_host = _docker_host()
    checkout = _verified_checkout()
    try:
        _command(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            docker_host=docker_host,
        )
    except (Blocked, Failure):
        raise Blocked("dev engine unreachable") from None
    try:
        ps_output = _command(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={DEV_PROJECT}",
                "--format",
                '{{.Names}}|{{.Label "com.docker.compose.service"}}|'
                '{{.Label "com.docker.compose.project"}}|{{.State}}|'
                '{{.Label "com.docker.compose.project.working_dir"}}|'
                '{{.Label "com.docker.compose.project.config_files"}}',
            ],
            docker_host=docker_host,
        )
        volume_name = _command(
            ["docker", "volume", "inspect", DEV_VOLUME, "--format", "{{.Name}}"],
            docker_host=docker_host,
        ).strip()
        mounts = _command(
            [
                "docker",
                "inspect",
                DEV_DB_CONTAINER,
                "--format",
                "{{range .Mounts}}{{.Name}}|{{.Destination}} {{end}}",
            ],
            docker_host=docker_host,
        ).strip()
        net_address = _command(
            [
                "docker",
                "inspect",
                DEV_DB_CONTAINER,
                "--format",
                f'{{{{(index .NetworkSettings.Networks "{DEV_NETWORK}").IPAddress}}}}',
            ],
            docker_host=docker_host,
        ).strip()
        net_ports = _command(
            [
                "docker",
                "inspect",
                DEV_DB_CONTAINER,
                "--format",
                "{{range $p, $_ := .NetworkSettings.Ports}}{{$p}} {{end}}",
            ],
            docker_host=docker_host,
        ).strip()
    except (Blocked, Failure):
        raise Blocked("dev identity metadata unavailable") from None
    if volume_name != DEV_VOLUME:
        raise Blocked("unexpected dev database volume")
    attached = any(
        part.strip() == f"{DEV_VOLUME}|{DEV_PG_DATA}" for part in mounts.split() if part.strip()
    )
    if not attached:
        raise Blocked("dev database volume not mounted")
    rows = _parse_ps_table(ps_output)
    db = rows.get(DEV_DB_CONTAINER)
    web = rows.get(DEV_WEB_CONTAINER)
    if db is None or web is None:
        raise Blocked("dev containers not found")
    if db.get("service") != "db" or db.get("project") != DEV_PROJECT:
        raise Blocked("dev db identity mismatch")
    if web.get("service") != "web" or web.get("project") != DEV_PROJECT:
        raise Blocked("dev web identity mismatch")
    expected_configs = _expected_config_files(checkout)
    for entry in (db, web):
        if str(entry.get("working_dir", "")) != str(checkout):
            raise Blocked("dev checkout provenance mismatch")
        configs = _parse_config_files(entry.get("config_files"))
        if configs != expected_configs:
            raise Blocked("dev checkout provenance mismatch")
    address = net_address.strip() or None
    if not address:
        raise Blocked("dev database route unavailable")
    if not _has_exact_port(net_ports):
        raise Blocked("dev database port unavailable")
    port = DEV_DB_PORT
    web_running = web.get("state") == "running"
    compose = [
        "docker",
        "compose",
        "-p",
        DEV_PROJECT,
        "-f",
        "compose.yml",
        "-f",
        "compose.dev.yml",
    ]
    return Target(
        slug=name,
        fingerprint="",
        web_running=web_running,
        compose=compose,
        docker_host=docker_host,
        checkout=str(checkout),
        volume=DEV_VOLUME,
        db_address=address,
        db_port=port,
    )


def _validate_runtime(target: Target) -> None:
    if getattr(target, "slug", None) != "dev":
        raise Blocked("unexpected runtime target")
    docker_host = getattr(target, "docker_host", None)
    if docker_host != DEV_SOCKET or docker_host in FORBIDDEN_SOCKETS:
        raise Blocked("unverified docker engine")
    checkout = str(getattr(target, "checkout", ""))
    candidate = Path(checkout)
    if checkout != str(DEV_CHECKOUT):
        raise Blocked("unverified checkout")
    try:
        base = (candidate / "compose.yml").read_text()
        dev = (candidate / "compose.dev.yml").read_text()
    except OSError:
        raise Blocked("unverified checkout") from None
    if "sirhosp_db_data" not in base or "sirhosp-web" not in dev:
        raise Blocked("unverified checkout")
    if getattr(target, "volume", None) != DEV_VOLUME:
        raise Blocked("unverified database volume")
    if not getattr(target, "db_address", None):
        raise Blocked("unverified database route")


def _command(
    argv: list[str], *, docker_host: str | None = None, cwd: str | Path | None = None
) -> str:
    env: dict[str, str] | None = None
    if docker_host is not None:
        env = dict(os.environ)
        env.pop("DOCKER_CONTEXT", None)
        env.pop("DOCKER_TLS_VERIFY", None)
        env.pop("DOCKER_CERT_PATH", None)
        env["DOCKER_HOST"] = docker_host
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise Failure("command timed out") from exc
    except OSError as exc:
        raise Failure("command unavailable") from exc
    if completed.returncode != 0:
        raise Failure("command failed")
    return completed.stdout


_STATE_FIELDS: dict[str, frozenset[str]] = {
    "CLOSED": frozenset({"state", "target", "last_run_id"}),
    "OPENING": frozenset(
        {"state", "target", "run_id", "deadline_iso", "timer_unit", "expect_state"}
    ),
    "ACTIVE": frozenset(
        {"state", "target", "run_id", "deadline_iso", "timer_unit", "pair_ids"}
    ),
    "CLOSING": frozenset({"state", "target", "run_id", "diagnostic"}),
}


def _state_invalid() -> Blocked:
    return Blocked("state record invalid, recovery required")


def _require_state_field(raw: dict, key: str) -> object:
    if key not in raw:
        raise _state_invalid()
    return raw[key]


def _require_state_text(raw: dict, key: str, pattern: re.Pattern[str] | None = None) -> str:
    value = _require_state_field(raw, key)
    if not isinstance(value, str):
        raise _state_invalid()
    if pattern is not None and not pattern.fullmatch(value):
        raise _state_invalid()
    return value


def _require_state_deadline(raw: dict) -> str:
    value = _require_state_text(raw, "deadline_iso")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise _state_invalid() from None
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise _state_invalid()
    return value


def _require_state_pair_ids(raw: dict) -> tuple[int, int]:
    value = _require_state_field(raw, "pair_ids")
    if not isinstance(value, list) or len(value) != 2:
        raise _state_invalid()
    ids = [item for item in value if type(item) is int and item > 0]
    if len(ids) != 2 or ids[0] == ids[1]:
        raise _state_invalid()
    return (ids[0], ids[1])


def _read_state(slug: str) -> ClosedRecord | OpeningRecord | ActiveRecord | ClosingRecord:
    path = _state_path(slug)
    if not path.exists():
        return ClosedRecord(state="CLOSED", target=slug, last_run_id=None)
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Blocked("state unreadable, recovery required") from exc
    if not isinstance(raw, dict):
        raise Blocked("state unreadable, recovery required")
    state = raw.get("state")
    if not isinstance(state, str) or state not in _STATE_FIELDS:
        raise Blocked("unknown state, recovery required")
    if set(raw) != _STATE_FIELDS[state]:
        raise _state_invalid()
    target = raw.get("target")
    if not isinstance(target, str) or target != slug:
        raise _state_invalid()
    if state == "CLOSED":
        last_run_id = raw["last_run_id"]
        if last_run_id is not None and (
            not isinstance(last_run_id, str) or not RUN_RE.fullmatch(last_run_id)
        ):
            raise _state_invalid()
        return ClosedRecord(state="CLOSED", target=target, last_run_id=last_run_id)
    run_id = _require_state_text(raw, "run_id", RUN_RE)
    if state == "CLOSING":
        diagnostic = raw["diagnostic"]
        if diagnostic is not None and not isinstance(diagnostic, str):
            raise _state_invalid()
        return ClosingRecord(
            state="CLOSING", target=target, run_id=run_id, diagnostic=diagnostic
        )
    deadline_iso = _require_state_deadline(raw)
    timer_unit = _require_state_text(raw, "timer_unit")
    if timer_unit != _timer_base(run_id) + ".timer":
        raise _state_invalid()
    if state == "OPENING":
        return OpeningRecord(
            state="OPENING",
            target=target,
            run_id=run_id,
            deadline_iso=deadline_iso,
            timer_unit=timer_unit,
            expect_state=_require_state_text(raw, "expect_state", SNAPSHOT_RE),
        )
    return ActiveRecord(
        state="ACTIVE",
        target=target,
        run_id=run_id,
        deadline_iso=deadline_iso,
        timer_unit=timer_unit,
        pair_ids=_require_state_pair_ids(raw),
    )


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _namespace_ancestors(directory: Path) -> list[Path]:
    """Root-to-leaf ancestor chain of the state directory.

    Only direct parent links are followed; siblings and unrelated trees
    are never enumerated. The filesystem root is the documented boundary.
    """
    chain: list[Path] = []
    probe = directory
    while True:
        chain.append(probe)
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    chain.reverse()
    return chain


def _durable_makedirs(directory: Path) -> None:
    """Create ``directory`` and affirm ancestry sync on every attempt.

    Existence is never treated as a durability acknowledgement: a previous
    failed attempt or a concurrently created namespace may leave entries
    that were never synced, and a module-global record would not survive a
    new process retry. Every call therefore syncs the actual root-to-leaf
    ancestor chain before any mutation or durability claim. Only ancestor
    paths of this namespace are synced.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for ancestor in _namespace_ancestors(directory):
        _sync_dir(ancestor)


def _ensure_state_dir(slug: str) -> Path:
    directory = _state_dir(slug)
    _durable_makedirs(directory)
    return directory


def _write_state(
    record: ClosedRecord | OpeningRecord | ActiveRecord | ClosingRecord,
) -> None:
    slug = record.target
    directory = _ensure_state_dir(slug)
    path = _state_path(slug)
    tmp = path.with_suffix(".tmp")
    data = json.dumps(asdict(record), separators=(",", ":"))
    with open(tmp, "w") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.rename(path)
    _sync_dir(directory)


@contextlib.contextmanager
def _lock(slug: str, wait_seconds: float | None = 900) -> Iterator[None]:
    # Namespace availability only: create missing directories without any
    # durability claim. Durable publication is affirmed by _write_state
    # before publish, so a directory-sync failure must never block lock
    # acquisition or a revocation attempt against readable state.
    _state_dir(slug).mkdir(parents=True, exist_ok=True)
    path = _lock_path(slug)
    try:
        handle = open(path, "r")
    except FileNotFoundError:
        handle = open(path, "a+")
    with handle:
        if wait_seconds is None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        else:
            deadline = time.monotonic() + wait_seconds
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise Blocked("lock wait timed out") from None
                    time.sleep(0.05)
        try:
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def _arm_timer(target: Target, run_id: str, timer_unit: str, deadline_iso: str) -> None:
    _validate_runtime(target)
    base = _owned_timer_name(timer_unit, run_id)
    try:
        moment = datetime.fromisoformat(deadline_iso)
    except ValueError as exc:
        raise Blocked(f"deadline invalid: {exc}") from exc
    if moment.microsecond != 0:
        raise Blocked("deadline precision unverified")
    calendar = moment.strftime("%Y-%m-%d %H:%M:%S UTC")
    checkout = str(getattr(target, "checkout", ""))
    _command(
        [
            "systemd-run",
            "--user",
            f"--unit={base}",
            f"--on-calendar={calendar}",
            "--timer-property=AccuracySec=1s",
            "--property=TimeoutStartSec=infinity",
            "--property=Type=oneshot",
            "--property=Description=SIRHOSP verification auto-close",
            f"--setenv=DOCKER_HOST={target.docker_host}",
            *_callback_argv(checkout, run_id),
        ]
    )


def _parse_exec_start(output: str, argv: list[str]) -> None:
    text = output.strip()
    if text.count("{") != 1 or text.count("}") != 1:
        raise Blocked("callback service shape unverified")
    if not text.startswith("{") or not text.endswith("}"):
        raise Blocked("callback service shape unverified")
    inner = text[1:-1]
    segments = [segment.strip() for segment in inner.split(";")]
    if any(not segment for segment in segments):
        raise Blocked("callback service shape unverified")
    paths = []
    commands = []
    for segment in segments:
        if "=" not in segment:
            raise Blocked("callback service shape unverified")
        key, _, value = segment.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "path":
            paths.append(value)
        elif key == "argv[]":
            commands.append(value)
        elif key in {"ignore_errors", "start_time", "stop_time", "pid", "code", "status"}:
            continue
        else:
            raise Blocked("callback service shape unverified")
    if len(paths) != 1 or len(commands) != 1:
        raise Blocked("callback service shape unverified")
    words = commands[0].split()
    if paths[0] != argv[0] or words != argv:
        raise Blocked("callback service argv mismatch")


def _confirm_timer(target: Target, timer_unit: str, run_id: str, deadline_iso: str) -> None:
    _validate_runtime(target)
    base = _owned_timer_name(timer_unit, run_id)
    timer = base + ".timer"
    service = base + ".service"
    if _show_value(target, timer, "LoadState") != "loaded":
        raise Blocked(f"timer {timer} not loaded")
    if _show_value(target, timer, "ActiveState") != "active":
        raise Blocked(f"timer {timer} not armed")
    if _show_value(target, timer, "Transient") != "yes":
        raise Blocked(f"timer {timer} not transient")
    unit_raw = _command(
        [
            "busctl",
            "--user",
            "get-property",
            "org.freedesktop.systemd1",
            _unit_object_path(timer),
            "org.freedesktop.systemd1.Timer",
            "Unit",
        ]
    ).strip()
    unit_parts = unit_raw.split(None, 1)
    if len(unit_parts) != 2 or unit_parts[0] != "s" or unit_parts[1] != f'"{service}"':
        raise Blocked(f"timer {timer} service mismatch")
    checkout = str(getattr(target, "checkout", ""))
    expected = _callback_argv(checkout, run_id)
    _parse_exec_start(_show_value(target, service, "ExecStart"), expected)
    if _show_value(target, service, "LoadState") != "loaded":
        raise Blocked(f"callback {service} not loaded")
    if _show_value(target, service, "Transient") != "yes":
        raise Blocked(f"callback {service} not transient")
    service_type = _command(
        [
            "busctl",
            "--user",
            "get-property",
            "org.freedesktop.systemd1",
            _unit_object_path(service),
            "org.freedesktop.systemd1.Service",
            "Type",
        ]
    ).strip()
    if service_type != 's "oneshot"':
        raise Blocked(f"callback {service} type unverified")
    start_timeout = _command(
        [
            "busctl",
            "--user",
            "get-property",
            "org.freedesktop.systemd1",
            _unit_object_path(service),
            "org.freedesktop.systemd1.Service",
            "TimeoutStartUSec",
        ]
    ).strip()
    if start_timeout != "t 18446744073709551615":
        raise Blocked(f"callback {service} start timeout unverified")
    try:
        moment = datetime.fromisoformat(deadline_iso)
    except ValueError as exc:
        raise Blocked(f"deadline invalid: {exc}") from exc
    expected_us = int(moment.timestamp()) * 1000000
    raw = _command(
        [
            "busctl",
            "--user",
            "get-property",
            "org.freedesktop.systemd1",
            _unit_object_path(timer),
            "org.freedesktop.systemd1.Timer",
            "NextElapseUSecRealtime",
        ]
    ).strip()
    parts = raw.split()
    if len(parts) != 2 or parts[0] != "t":
        raise Blocked(f"timer {timer} schedule unverified")
    try:
        elapse_us = int(parts[1])
    except ValueError:
        raise Blocked(f"timer {timer} schedule unverified") from None
    if elapse_us <= 0 or elapse_us != expected_us or elapse_us <= int(_now() * 1000000):
        raise Blocked(f"timer {timer} schedule mismatch")


def _cancel_timer(target: Target, timer_unit: str, run_id: str, *, include_service: bool) -> None:
    _validate_runtime(target)
    base = _owned_timer_name(timer_unit, run_id)
    units = [base + ".timer"]
    if include_service:
        units.append(base + ".service")
    try:
        _command(["systemctl", "--user", "stop", *units])
    except Failure as stop_failure:
        # The joint stop of a transient pair whose service never fired exits
        # nonzero even after systemd unloaded both units, and stopping
        # already-unloaded transient units is never idempotent, so the stop
        # exit code alone cannot decide cleanup. Prove it strictly instead:
        # only proven absence and inactivity of every requested unit may
        # swallow the stop failure; any other outcome keeps it, leaving the
        # cleanup unknown rather than falsely failed or completed.
        try:
            proven = all(
                _show_value(target, unit, "LoadState") == "not-found"
                and _show_value(target, unit, "ActiveState") == "inactive"
                for unit in units
            )
        except Failure:
            raise stop_failure from None
        if not proven:
            raise stop_failure from None


def _collect_db_identity(target: Target) -> tuple[str, str, int]:
    _validate_runtime(target)
    try:
        output = _command(
            [
                *target.compose,
                "exec",
                "-T",
                "web",
                PYTHON_BIN,
                "manage.py",
                "shell",
                "--verbosity",
                "0",
                "-c",
                "import json;"
                "from apps.accounts.management.commands.verification_session import "
                "database_identity;"
                "print(json.dumps(database_identity()))",
            ],
            docker_host=getattr(target, "docker_host", None),
            cwd=getattr(target, "checkout", None),
        ).strip()
    except subprocess.TimeoutExpired as exc:
        raise Failure("database identity timed out") from exc
    except (Blocked, Failure):
        raise
    except Exception as exc:
        raise Failure(f"database identity failed: {exc}") from exc
    try:
        fingerprint, address, port = json.loads(output)
    except (ValueError, TypeError) as exc:
        raise Failure("database identity response invalid") from exc
    if not FINGERPRINT_RE.fullmatch(str(fingerprint or "")):
        raise Blocked("database fingerprint invalid")
    port_number = _as_port(port)
    if str(address or "") != str(getattr(target, "db_address", address)):
        raise Blocked("database route mismatch")
    if port_number != int(getattr(target, "db_port", port_number) or 0):
        raise Blocked("database port mismatch")
    return str(fingerprint), str(address), port_number


def _workers_running(target: Target) -> bool:
    output = _command(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={DEV_PROJECT}",
            "--format",
            '{{.Names}}|{{.Label "com.docker.compose.service"}}',
        ],
        docker_host=getattr(target, "docker_host", None),
    )
    for line in output.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) == 6:
            _, service, _, _, _, _ = parts
        elif len(parts) == 4:
            _, service, _, _ = parts
        elif len(parts) == 2:
            _, service = parts
        else:
            continue
        if service in {"worker", "summary_worker"}:
            return True
        if "worker" in service:
            return True
    return False


def _gate_open(target: Target, *, preflight: dict | None = None) -> None:
    _validate_runtime(target)
    if getattr(target, "slug", None) != "dev":
        raise Blocked("unexpected open target")
    if not isinstance(preflight, dict):
        raise Blocked("preflight proof required")
    if preflight.get("debug") is not False:
        raise Blocked("opening requires DEBUG false")
    if preflight.get("migrations_clean") is not True:
        raise Blocked("pending migrations block opening")
    fingerprint = str(preflight.get("fingerprint", ""))
    if not FINGERPRINT_RE.fullmatch(fingerprint):
        raise Blocked("database fingerprint unverified")
    address = preflight.get("server_address")
    port = preflight.get("server_port")
    expected_address = getattr(target, "db_address", None)
    expected_port = getattr(target, "db_port", None)
    if not isinstance(address, str) or not address:
        raise Blocked("database endpoint unverified")
    number = _as_port(port)
    if expected_address is not None and address != str(expected_address):
        raise Blocked("database route mismatch")
    if expected_port is not None and number != int(expected_port):
        raise Blocked("database port mismatch")
    try:
        workers = _workers_running(target)
    except (Blocked, Failure):
        raise
    except Exception as exc:
        raise Blocked(f"worker state unavailable: {exc}") from exc
    if workers:
        raise Blocked("workers must be stopped for opening")


def _gate_start(target: Target) -> None:
    _validate_runtime(target)
    _command(
        target.compose + ["up", "-d", "--no-deps", "--no-build", "--pull", "never", "db", "web"],
        docker_host=getattr(target, "docker_host", None),
        cwd=getattr(target, "checkout", None),
    )


def _gate_stop(target: Target) -> None:
    _validate_runtime(target)
    _command(
        target.compose + ["stop", "web"],
        docker_host=getattr(target, "docker_host", None),
        cwd=getattr(target, "checkout", None),
    )
    _command(
        target.compose + ["stop", "db"],
        docker_host=getattr(target, "docker_host", None),
        cwd=getattr(target, "checkout", None),
    )


def _probe_one_shot(target: Target, action: str, **kwargs: str) -> None:
    _validate_runtime(target)
    raise Blocked("aliases or database route unproved")


def _django_argv(target: Target, action: str, **kwargs: str) -> list[str]:
    if action not in ALLOWED_ACTIONS:
        raise Blocked(f"unapproved action {action}")
    for key in kwargs:
        if "password" in key.lower():
            raise Blocked("secrets never cross the adapter")
        if key not in {"run_id", "expect_state", "expect_db_fingerprint"}:
            raise Blocked(f"unapproved argument {key}")
    fingerprint = str(kwargs.get("expect_db_fingerprint", ""))
    if not FINGERPRINT_RE.fullmatch(fingerprint):
        raise Blocked("expected database fingerprint required")
    argv: list[str] = [
        *getattr(target, "compose", ["docker", "compose"]),
        "exec",
        "-T",
        "web",
        PYTHON_BIN,
        "manage.py",
        "verification_session",
        action,
        "--dev-context-confirm",
        "--target",
        "dev",
        "--expect-db-fingerprint",
        fingerprint,
    ]
    if action in {"prepare", "open", "close", "recover"}:
        run_id = str(kwargs.get("run_id", ""))
        if not RUN_RE.fullmatch(run_id):
            raise Blocked("run-id required")
        argv += ["--run-id", run_id]
    if action in {"prepare", "open", "recover"}:
        snapshot = str(kwargs.get("expect_state", ""))
        if not SNAPSHOT_RE.fullmatch(snapshot):
            raise Blocked("expected snapshot required")
        argv += ["--expect-state", snapshot]
    if action in {"preflight", "owned-status", "close"} and "expect_state" in kwargs:
        raise Blocked("unexpected snapshot for this action")
    return argv


def _check_django_response(target: Target, action: str, expected: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise Failure("django response invalid")
    if action in {"preflight", "owned-status"}:
        fingerprint = str(payload.get("fingerprint", ""))
        if fingerprint != expected:
            raise Blocked("database fingerprint mismatch")
        address = payload.get("server_address")
        port = payload.get("server_port")
        expected_address = getattr(target, "db_address", None)
        expected_port = getattr(target, "db_port", None)
        if not isinstance(address, str) or not address:
            raise Blocked("database endpoint unverified")
        number = _as_port(port)
        if expected_address is not None and address != str(expected_address):
            raise Blocked("database route mismatch")
        if expected_port is not None and number != int(expected_port):
            raise Blocked("database port mismatch")
    return payload


def _run_django(target: Target, action: str, **kwargs: str) -> dict:
    _validate_runtime(target)
    if action not in ALLOWED_ACTIONS:
        raise Blocked(f"unapproved action {action}")
    web_running = bool(getattr(target, "web_running", True))
    if not web_running:
        _probe_one_shot(target, action, **kwargs)
        raise Blocked("aliases or database route unproved")
    argv = _django_argv(target, action, **kwargs)
    expected = str(kwargs.get("expect_db_fingerprint", ""))
    try:
        output = _command(
            argv,
            docker_host=getattr(target, "docker_host", None),
            cwd=getattr(target, "checkout", None),
        )
    except subprocess.TimeoutExpired as exc:
        raise Failure(f"django adapter timed out: {action}") from exc
    except (Blocked, Failure):
        raise
    except Exception as exc:
        raise Failure(f"django adapter failed: {exc}") from exc
    if not output.strip():
        raise Failure("django response empty")
    try:
        payload = json.loads(output)
    except ValueError as exc:
        raise Failure("django response invalid") from exc
    try:
        return _check_django_response(target, action, expected, payload)
    except (Blocked, Failure):
        raise
    except Exception as exc:
        raise Failure("django response invalid") from exc


def _pair_snapshot(status: dict) -> dict:
    pair = status.get("pair", status)
    if not isinstance(pair, dict) or "snapshot" not in pair:
        raise Failure("owned-status response missing snapshot")
    return pair


def _is_orphan(pair: dict) -> bool:
    for name in ("user", "admin"):
        entry = pair.get(name, {})
        if not isinstance(entry, dict):
            continue
        token = str(entry.get("token", ""))
        if entry.get("is_active") or entry.get("has_usable_password"):
            return True
        if token.startswith("vfyA:") or token.startswith("vfyP:"):
            return True
    return False


_REQUIRED_ENTRY_FIELDS = frozenset(
    {
        "username",
        "user_id",
        "token",
        "exists",
        "owned",
        "is_active",
        "has_usable_password",
        "is_staff",
        "is_superuser",
        "must_change_password",
    }
)


def _require_verified_pair(pair: dict) -> dict:
    if not isinstance(pair, dict):
        raise Failure("owned-status response invalid")
    snapshot = pair.get("snapshot")
    if not isinstance(snapshot, str) or not SNAPSHOT_RE.fullmatch(snapshot):
        raise Failure("owned-status snapshot invalid")
    seen_ids: list[int] = []
    for slot, expected in (("user", "verify_user"), ("admin", "verify_admin")):
        if slot not in pair:
            raise Failure("owned-status pair incomplete")
        entry = pair[slot]
        if not isinstance(entry, dict):
            raise Failure("owned-status entry invalid")
        for required in _REQUIRED_ENTRY_FIELDS:
            if required not in entry:
                raise Failure("owned-status entry incomplete")
        if entry.get("username") != expected:
            raise Failure("owned-status identity mismatch")
        exists = entry.get("exists")
        owned = entry.get("owned")
        if type(exists) is not bool:
            raise Failure("owned-status entry invalid")
        if type(owned) is not bool:
            raise Failure("owned-status entry invalid")
        if owned is not True:
            raise Blocked("foreign owned row requires recovery")
        for key in ("is_active", "has_usable_password", "is_staff", "is_superuser"):
            if type(entry.get(key)) is not bool:
                raise Failure("owned-status entry invalid")
        profile = entry.get("must_change_password")
        if not (profile is None or type(profile) is bool):
            raise Failure("owned-status entry invalid")
        token = entry.get("token")
        if not isinstance(token, str):
            raise Failure("owned-status entry invalid")
        user_id = entry.get("user_id")
        if exists is False:
            if user_id is not None:
                raise Failure("owned-status absence unverified")
            if token != "":
                raise Failure("owned-status absence unverified")
            if entry.get("is_active") is not False:
                raise Failure("owned-status absence unverified")
            if entry.get("has_usable_password") is not False:
                raise Failure("owned-status absence unverified")
            if entry.get("is_staff") is not False:
                raise Failure("owned-status absence unverified")
            if entry.get("is_superuser") is not False:
                raise Failure("owned-status absence unverified")
            if profile is not None:
                raise Failure("owned-status absence unverified")
        else:
            if type(user_id) is not int:
                raise Failure("owned-status identity invalid")
            seen_ids.append(user_id)
    if len(seen_ids) == 2 and seen_ids[0] == seen_ids[1]:
        raise Failure("owned-status identity collision")
    return pair


def _stamped_run_id(pair: dict) -> str:
    """Run id stamped into both owned rows of a verified pair.

    When the persisted record cannot be trusted, the non-secret stamp the
    owned domain flow keeps in the database is the only authoritative
    cleanup identity: it identifies exactly which owned timer generation
    may still be armed. Both present rows must carry the same well-formed
    stamp; anything else proves no generation at all and must not be
    guessed from the corrupt record or a supplied run id.
    """
    stamped: str | None = None
    for slot in ("user", "admin"):
        entry = pair.get(slot)
        if not isinstance(entry, dict) or entry.get("exists") is not True:
            raise Blocked("owned stamp missing")
        token = entry.get("token")
        if not isinstance(token, str):
            raise Blocked("owned stamp malformed")
        match = TOKEN_STAMP_RE.fullmatch(token)
        if match is None:
            raise Blocked("owned stamp malformed")
        run = match.group(1)
        if stamped is None:
            stamped = run
        elif run != stamped:
            raise Blocked("owned stamps disagree")
    if stamped is None:
        raise Blocked("owned stamp missing")
    return stamped


def _compensate_open_failure(
    resolved: Target,
    slug: str,
    run_id: str,
    timer_unit: str,
    original: BaseException,
    *,
    fingerprint: str,
) -> None:
    def _checkpoint(record: ClosedRecord | ClosingRecord, *, timer_cleanup: str) -> None:
        category = type(original).__name__
        stage = record.state
        if timer_cleanup == "retained":
            outcome = "timer retained, run manual close/recovery"
        elif timer_cleanup == "unknown":
            outcome = "timer cleanup outcome unknown, run manual close/recovery"
        else:
            outcome = (
                "revocation confirmed, timer cleanup completed, manual recovery required"
            )
        try:
            _write_state(record)
        except OSError:
            raise Failure(
                f"open {stage} checkpoint undurable after {category}; {outcome}"
            ) from original

    try:
        _require_revoked(
            _run_django(resolved, "close", run_id=run_id, expect_db_fingerprint=fingerprint)
        )
    except Exception as cleanup_exc:
        _checkpoint(
            ClosingRecord(
                state="CLOSING",
                target=slug,
                run_id=run_id,
                diagnostic=f"open cleanup revocation failed: {cleanup_exc}",
            ),
            timer_cleanup="retained",
        )
        raise original from None
    _checkpoint(
        ClosingRecord(
            state="CLOSING",
            target=slug,
            run_id=run_id,
            diagnostic="revocation confirmed, cleanup pending",
        ),
        timer_cleanup="retained",
    )
    try:
        _cancel_timer(resolved, timer_unit, run_id, include_service=True)
    except Exception as cancel_exc:
        _checkpoint(
            ClosingRecord(
                state="CLOSING",
                target=slug,
                run_id=run_id,
                diagnostic=f"open cleanup cancel failed: {cancel_exc}",
            ),
            timer_cleanup="unknown",
        )
        raise original from None
    _checkpoint(
        ClosedRecord(state="CLOSED", target=slug, last_run_id=None),
        timer_cleanup="completed",
    )
    raise original from None


def cmd_doctor(target: str, *, confirm_fictitious: bool) -> DoctorReport:
    resolved = _resolve_target(target)
    if not confirm_fictitious:
        raise Blocked("fictitious dataset confirmation required")
    fingerprint, _, _ = _collect_db_identity(resolved)
    preflight = _run_django(resolved, "preflight", expect_db_fingerprint=fingerprint)
    _gate_open(resolved, preflight=preflight)
    _run_django(resolved, "owned-status", expect_db_fingerprint=fingerprint)
    return DoctorReport(status="PASS")


def cmd_status(target: str) -> StatusReport:
    resolved = _resolve_target(target)
    record = _read_state(resolved.slug)
    run_id: str | None = getattr(record, "run_id", None)
    if record.state == "CLOSED":
        run_id = getattr(record, "last_run_id", None)
    return StatusReport(state=record.state, target=resolved.slug, run_id=run_id)


def cmd_open(
    target: str,
    *,
    confirm_fictitious: bool,
    start: bool = False,
    timeout_min: int = 60,
) -> OpenCredentials:
    resolved = _resolve_target(target)
    if not confirm_fictitious:
        raise Blocked("fictitious dataset confirmation required")
    slug = str(getattr(resolved, "slug", target))
    with _lock(slug):
        record = _read_state(slug)
        if record.state != "CLOSED":
            raise Blocked(f"session {record.state} requires close before open")
        if not bool(getattr(resolved, "web_running", False)):
            raise Blocked("web stopped, identity unproved, no start attempted")
        fingerprint, _, _ = _collect_db_identity(resolved)
        if start:
            _gate_start(resolved)
            resolved = _resolve_target(target)
            fingerprint, _, _ = _collect_db_identity(resolved)
            slug = str(getattr(resolved, "slug", target))
            record = _read_state(slug)
            if record.state != "CLOSED":
                raise Blocked(f"session {record.state} requires close before open")
        preflight = _run_django(resolved, "preflight", expect_db_fingerprint=fingerprint)
        _gate_open(resolved, preflight=preflight)
        status = _run_django(resolved, "owned-status", expect_db_fingerprint=fingerprint)
        pair = _require_verified_pair(_pair_snapshot(status))
        if _is_orphan(pair):
            raise Blocked("orphaned owned rows require recovery before open")
        run_id = secrets.token_hex(16)
        deadline_ts, deadline_iso = _deadline_lease(timeout_min)
        timer_unit = _timer_base(run_id) + ".timer"
        expect = str(pair["snapshot"])
        _write_state(
            OpeningRecord(
                state="OPENING",
                target=slug,
                run_id=run_id,
                deadline_iso=deadline_iso,
                timer_unit=timer_unit,
                expect_state=expect,
            )
        )
        try:
            _arm_timer(resolved, run_id, timer_unit, deadline_iso)
            _confirm_timer(resolved, timer_unit, run_id, deadline_iso)
        except (Blocked, Failure):
            try:
                _cancel_timer(resolved, timer_unit, run_id, include_service=True)
            except Exception as cancel_exc:
                _write_state(
                    ClosingRecord(
                        state="CLOSING",
                        target=slug,
                        run_id=run_id,
                        diagnostic=f"arm cleanup failed: {cancel_exc}",
                    )
                )
                raise
            _write_state(ClosedRecord(state="CLOSED", target=slug, last_run_id=None))
            raise
        try:
            prepared = _run_django(
                resolved,
                "prepare",
                run_id=run_id,
                expect_state=expect,
                expect_db_fingerprint=fingerprint,
            )
            if not isinstance(prepared, dict):
                raise Failure("prepare response invalid")
            snapshot_after = prepared.get("snapshot_after")
            if not isinstance(snapshot_after, str) or not SNAPSHOT_RE.fullmatch(snapshot_after):
                raise Failure("prepare response invalid")
            new_expect = snapshot_after
        except (Blocked, Failure) as exc:
            _compensate_open_failure(
                resolved, slug, run_id, timer_unit, exc, fingerprint=fingerprint
            )
            raise exc from None
        except Exception as exc:
            failure = Failure(str(exc))
            _compensate_open_failure(
                resolved, slug, run_id, timer_unit, failure, fingerprint=fingerprint
            )
            raise failure from None
        try:
            _write_state(
                OpeningRecord(
                    state="OPENING",
                    target=slug,
                    run_id=run_id,
                    deadline_iso=deadline_iso,
                    timer_unit=timer_unit,
                    expect_state=new_expect,
                )
            )
        except OSError as exc:
            _compensate_open_failure(
                resolved, slug, run_id, timer_unit, exc, fingerprint=fingerprint
            )
        current = _read_state(slug)
        if getattr(current, "run_id", None) != run_id:
            _compensate_open_failure(
                resolved,
                slug,
                run_id,
                timer_unit,
                Blocked("run changed during prepare"),
                fingerprint=fingerprint,
            )
        try:
            _confirm_timer(resolved, timer_unit, run_id, deadline_iso)
            if _now() > deadline_ts:
                raise Blocked("deadline expired before activation")
        except (Blocked, Failure) as exc:
            _compensate_open_failure(
                resolved, slug, run_id, timer_unit, exc, fingerprint=fingerprint
            )
        try:
            opened = _run_django(
                resolved,
                "open",
                run_id=run_id,
                expect_state=new_expect,
                expect_db_fingerprint=fingerprint,
            )
        except (Blocked, Failure) as exc:
            _compensate_open_failure(
                resolved, slug, run_id, timer_unit, exc, fingerprint=fingerprint
            )
        except Exception as exc:
            failure = Failure(str(exc))
            _compensate_open_failure(
                resolved, slug, run_id, timer_unit, failure, fingerprint=fingerprint
            )
        try:
            pair_ids = (int(opened["pair_ids"][0]), int(opened["pair_ids"][1]))
            _write_state(
                ActiveRecord(
                    state="ACTIVE",
                    target=slug,
                    run_id=run_id,
                    deadline_iso=deadline_iso,
                    timer_unit=timer_unit,
                    pair_ids=pair_ids,
                )
            )
        except OSError as exc:
            failure = Failure(f"active record failed: {exc}")
            _compensate_open_failure(
                resolved, slug, run_id, timer_unit, failure, fingerprint=fingerprint
            )
        try:
            _confirm_timer(resolved, timer_unit, run_id, deadline_iso)
            if _now() > deadline_ts:
                raise Blocked("deadline expired before emission")
        except (Blocked, Failure) as exc:
            _compensate_open_failure(
                resolved, slug, run_id, timer_unit, exc, fingerprint=fingerprint
            )
        passwords = dict(opened["passwords"])
        return OpenCredentials(run_id=run_id, passwords=passwords, target=slug)


def cmd_close(
    target: str,
    *,
    run_id: str | None = None,
    recover: bool = False,
    stop: bool = False,
) -> Verdict:
    resolved = _resolve_target(target)
    slug = str(getattr(resolved, "slug", target))
    with _lock(slug):
        try:
            record = _read_state(slug)
        except Blocked:
            if not recover:
                raise
            record = None
        if isinstance(record, (OpeningRecord, ActiveRecord, ClosingRecord)):
            current_run = str(record.run_id)
            if run_id is not None and run_id != current_run:
                return Verdict(status="SKIPPED", revoked=False, diagnostic="stale run ignored")
            effective = current_run
            try:
                fingerprint, _, _ = _collect_db_identity(resolved)
            except (Blocked, Failure) as exc:
                return Verdict(status="FAIL", revoked=False, diagnostic=str(exc))
            if isinstance(record, (OpeningRecord, ActiveRecord)):
                timer_unit = str(record.timer_unit)
                _owned_timer_name(timer_unit, effective)
            else:
                timer_unit = _timer_base(effective) + ".timer"
            if recover:
                try:
                    status = _run_django(
                        resolved, "owned-status", expect_db_fingerprint=fingerprint
                    )
                    pair = _require_verified_pair(_pair_snapshot(status))
                    snapshot = str(pair["snapshot"])
                    _require_revoked(
                        _run_django(
                            resolved,
                            "recover",
                            run_id=effective,
                            expect_state=snapshot,
                            expect_db_fingerprint=fingerprint,
                        )
                    )
                except (Blocked, Failure) as exc:
                    _write_state(
                        ClosingRecord(
                            state="CLOSING",
                            target=slug,
                            run_id=effective,
                            diagnostic=f"recovery failed: {exc}",
                        )
                    )
                    return Verdict(
                        status="FAIL",
                        revoked=False,
                        diagnostic=f"recovery failed, contain web: {exc}",
                    )
                _write_state(
                    ClosingRecord(
                        state="CLOSING",
                        target=slug,
                        run_id=effective,
                        diagnostic="revocation confirmed, cleanup pending",
                    )
                )
                try:
                    _cancel_timer(resolved, timer_unit, effective, include_service=True)
                except (Blocked, Failure) as exc:
                    _write_state(
                        ClosingRecord(
                            state="CLOSING", target=slug, run_id=effective, diagnostic=str(exc)
                        )
                    )
                    return Verdict(status="FAIL", revoked=True, diagnostic=str(exc))
                if stop:
                    try:
                        _gate_stop(resolved)
                    except (Blocked, Failure, OSError) as exc:
                        _write_state(
                            ClosingRecord(
                                state="CLOSING",
                                target=slug,
                                run_id=effective,
                                diagnostic=f"stop failed, contain services: {exc}",
                            )
                        )
                        return Verdict(
                            status="FAIL",
                            revoked=True,
                            diagnostic=f"stop failed, contain services: {exc}",
                        )
                _write_state(ClosedRecord(state="CLOSED", target=slug, last_run_id=effective))
                return Verdict(status="PASS", revoked=True)
            try:
                _require_revoked(
                    _run_django(
                        resolved, "close", run_id=effective, expect_db_fingerprint=fingerprint
                    )
                )
            except (Blocked, Failure, OSError) as exc:
                _write_state(
                    ClosingRecord(
                        state="CLOSING",
                        target=slug,
                        run_id=effective,
                        diagnostic=f"revocation failed, contain web before stopping db: {exc}",
                    )
                )
                return Verdict(
                    status="FAIL",
                    revoked=False,
                    diagnostic=f"revocation failed, contain web before stopping db: {exc}",
                )
            _write_state(
                ClosingRecord(
                    state="CLOSING",
                    target=slug,
                    run_id=effective,
                    diagnostic="revocation confirmed, cleanup pending",
                )
            )
            try:
                _cancel_timer(resolved, timer_unit, effective, include_service=True)
            except (Blocked, Failure, OSError) as exc:
                _write_state(
                    ClosingRecord(
                        state="CLOSING", target=slug, run_id=effective, diagnostic=str(exc)
                    )
                )
                return Verdict(status="FAIL", revoked=True, diagnostic=str(exc))
            if stop:
                try:
                    _gate_stop(resolved)
                except (Blocked, Failure, OSError) as exc:
                    _write_state(
                        ClosingRecord(
                            state="CLOSING",
                            target=slug,
                            run_id=effective,
                            diagnostic=f"stop failed, contain services: {exc}",
                        )
                    )
                    return Verdict(
                        status="FAIL",
                        revoked=True,
                        diagnostic=f"stop failed, contain services: {exc}",
                    )
            _write_state(ClosedRecord(state="CLOSED", target=slug, last_run_id=effective))
            return Verdict(status="PASS", revoked=True)
        if record is None or record.state == "CLOSED":
            try:
                fingerprint, _, _ = _collect_db_identity(resolved)
            except (Blocked, Failure) as exc:
                if not recover:
                    return Verdict(status="FAIL", revoked=False, diagnostic=str(exc))
                return Verdict(status="FAIL", revoked=False, diagnostic=str(exc))
            if not recover:
                try:
                    status = _run_django(
                        resolved, "owned-status", expect_db_fingerprint=fingerprint
                    )
                    pair = _require_verified_pair(_pair_snapshot(status))
                except (Blocked, Failure) as exc:
                    return Verdict(status="FAIL", revoked=False, diagnostic=str(exc))
                if _is_orphan(pair):
                    raise Blocked("orphaned owned rows require recovery")
                if stop:
                    try:
                        _gate_stop(resolved)
                    except (Blocked, Failure, OSError) as exc:
                        return Verdict(
                            status="FAIL",
                            revoked=True,
                            diagnostic=f"stop failed, contain services: {exc}",
                        )
                return Verdict(status="PASS", revoked=True)
            try:
                status = _run_django(resolved, "owned-status", expect_db_fingerprint=fingerprint)
                pair = _require_verified_pair(_pair_snapshot(status))
                snapshot = str(pair["snapshot"])
            except (Blocked, Failure) as exc:
                return Verdict(status="FAIL", revoked=False, diagnostic=str(exc))
            if record is None:
                # The persisted record exists but cannot be trusted, so the
                # only trustworthy owned generation is the one stamped in
                # the verified database pair. Never mint a random run id and
                # never act on a supplied run id that disagrees with the
                # stamp: either would claim a cleanup identity that was
                # never proved and could leave the owned timer pending.
                try:
                    stamped = _stamped_run_id(pair)
                except Blocked as exc:
                    return Verdict(
                        status="FAIL",
                        revoked=False,
                        diagnostic=(
                            f"recovery cleanup identity unverified: {exc}, "
                            "run manual close/recovery"
                        ),
                    )
                if run_id is not None and run_id != stamped:
                    return Verdict(
                        status="FAIL",
                        revoked=False,
                        diagnostic=(
                            "recovery run id does not match the owned generation, "
                            "run manual close/recovery"
                        ),
                    )
                effective = stamped
            else:
                effective = run_id if run_id is not None else secrets.token_hex(16)
            try:
                _require_revoked(
                    _run_django(
                        resolved,
                        "recover",
                        run_id=effective,
                        expect_state=snapshot,
                        expect_db_fingerprint=fingerprint,
                    )
                )
            except (Blocked, Failure) as exc:
                return Verdict(status="FAIL", revoked=False, diagnostic=str(exc))
            if record is None:
                # Revocation is affirmed: publish the durable cleanup-pending
                # checkpoint, then retire exactly the stamped owned
                # generation before any CLOSED claim, in the same fixed
                # order as every other close path.
                _write_state(
                    ClosingRecord(
                        state="CLOSING",
                        target=slug,
                        run_id=effective,
                        diagnostic="revocation confirmed, cleanup pending",
                    )
                )
                try:
                    _cancel_timer(
                        resolved,
                        _timer_base(effective) + ".timer",
                        effective,
                        include_service=True,
                    )
                except (Blocked, Failure, OSError) as exc:
                    _write_state(
                        ClosingRecord(
                            state="CLOSING", target=slug, run_id=effective, diagnostic=str(exc)
                        )
                    )
                    return Verdict(status="FAIL", revoked=True, diagnostic=str(exc))
            if stop:
                try:
                    _gate_stop(resolved)
                except (Blocked, Failure, OSError) as exc:
                    _write_state(
                        ClosingRecord(
                            state="CLOSING",
                            target=slug,
                            run_id=effective,
                            diagnostic=f"recovery stop failed, contain services: {exc}",
                        )
                    )
                    return Verdict(
                        status="FAIL",
                        revoked=True,
                        diagnostic=f"stop failed, contain services: {exc}",
                    )
            _write_state(ClosedRecord(state="CLOSED", target=slug, last_run_id=effective))
            return Verdict(status="PASS", revoked=True)
        raise Blocked(f"unexpected state {getattr(record, 'state', record)}")


def cmd_callback(target: str, *, run_id: str) -> Verdict:
    _validate_target(target)
    if not RUN_RE.fullmatch(run_id):
        raise Blocked("callback run-id required")
    slug = target
    with _lock(slug, wait_seconds=None):
        try:
            record = _read_state(slug)
        except Blocked as exc:
            return Verdict(
                status="FAIL",
                revoked=False,
                diagnostic=f"callback state unreadable, run manual close/recovery: {exc}",
            )
        if not isinstance(record, (OpeningRecord, ActiveRecord, ClosingRecord)):
            return Verdict(status="SKIPPED", revoked=False, diagnostic="stale run ignored")
        if str(record.run_id) != run_id:
            return Verdict(status="SKIPPED", revoked=False, diagnostic="stale run ignored")
        effective = run_id
        resolved = _resolve_target(target)
        try:
            fingerprint, _, _ = _collect_db_identity(resolved)
        except (Blocked, Failure) as exc:
            return Verdict(status="FAIL", revoked=False, diagnostic=str(exc))
        if isinstance(record, (OpeningRecord, ActiveRecord)):
            timer_unit = str(record.timer_unit)
            _owned_timer_name(timer_unit, effective)
        else:
            timer_unit = _timer_base(effective) + ".timer"
        try:
            _require_revoked(
                _run_django(resolved, "close", run_id=effective, expect_db_fingerprint=fingerprint)
            )
        except (Blocked, Failure, OSError) as exc:
            _write_state(
                ClosingRecord(
                    state="CLOSING",
                    target=slug,
                    run_id=effective,
                    diagnostic=f"callback revocation failed, contain web: {exc}",
                )
            )
            return Verdict(
                status="FAIL",
                revoked=False,
                diagnostic=f"callback revocation failed, contain web: {exc}",
            )
        _write_state(
            ClosingRecord(
                state="CLOSING",
                target=slug,
                run_id=effective,
                diagnostic="revocation confirmed, cleanup pending",
            )
        )
        try:
            _cancel_timer(resolved, timer_unit, effective, include_service=False)
        except (Blocked, Failure, OSError) as exc:
            _write_state(
                ClosingRecord(state="CLOSING", target=slug, run_id=effective, diagnostic=str(exc))
            )
            return Verdict(status="FAIL", revoked=True, diagnostic=str(exc))
        _write_state(ClosedRecord(state="CLOSED", target=slug, last_run_id=effective))
        return Verdict(status="PASS", revoked=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dev verification controller")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="read-only dev target validation")
    doctor.add_argument("--target", required=True)
    doctor.add_argument("--confirm-fictitious", action="store_true")
    opener = sub.add_parser("open", help="open one verification session")
    opener.add_argument("--target", required=True)
    opener.add_argument("--confirm-fictitious", action="store_true")
    opener.add_argument("--start", action="store_true")
    opener.add_argument("--timeout-min", type=int, default=60)
    status = sub.add_parser("status", help="show non-secret session record")
    status.add_argument("--target", required=True)
    closer = sub.add_parser("close", help="revoke verification accounts")
    closer.add_argument("--target", required=True)
    closer.add_argument("--run-id", default=None)
    closer.add_argument("--recover", action="store_true")
    closer.add_argument("--stop", action="store_true")
    callback = sub.add_parser("callback", help="deadline callback for one owned run")
    callback.add_argument("--target", required=True)
    callback.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            report = cmd_doctor(args.target, confirm_fictitious=args.confirm_fictitious)
            print(json.dumps(asdict(report), separators=(",", ":")))
            return 0
        if args.command == "open":
            credentials = cmd_open(
                args.target,
                confirm_fictitious=args.confirm_fictitious,
                start=args.start,
                timeout_min=args.timeout_min,
            )
            # Assisted emission only: cmd_open returns after every guard,
            # activation, durable checkpoint and the final timer recheck, so
            # this is the single place the credentials are ever printed.
            # Explicit construction, no generic serializer; no other command
            # or failure path touches this payload.
            print(
                json.dumps(
                    {
                        "run_id": credentials.run_id,
                        "target": credentials.target,
                        "passwords": dict(credentials.passwords),
                    },
                    separators=(",", ":"),
                )
            )
            return 0
        if args.command == "status":
            status_report = cmd_status(args.target)
            print(json.dumps(asdict(status_report), separators=(",", ":")))
            return 0
        if args.command == "close":
            verdict = cmd_close(
                args.target, run_id=args.run_id, recover=args.recover, stop=args.stop
            )
            print(json.dumps(asdict(verdict), separators=(",", ":")))
            if verdict.status == "PASS":
                return 0
            if verdict.status == "SKIPPED":
                return 3
            if verdict.status == "FAIL":
                return 1
            return 2
        if args.command == "callback":
            verdict = cmd_callback(args.target, run_id=args.run_id)
            print(json.dumps(asdict(verdict), separators=(",", ":")))
            if verdict.status == "PASS":
                return 0
            if verdict.status == "SKIPPED":
                return 3
            if verdict.status == "FAIL":
                return 1
            return 2
    except Blocked as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    except Failure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("FAIL: state storage error, run manual close/recovery", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
