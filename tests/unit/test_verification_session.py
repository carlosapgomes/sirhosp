"""Controller lease regressions. Docker and systemd never run in these tests."""

from __future__ import annotations

import importlib
import json
import multiprocessing
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

RUN = "a" * 32
NEXT = "b" * 32
SNAPSHOT = "c" * 64

# Synthetic verification origins (ORIG-001): no operational FQDN may appear
# in tracked or candidate files. The controller under test resolves its dev
# origin from the private profile under $HOME; every test below provisions
# that profile from these values unless it overrides $HOME itself.
SYN_DEV_ORIGIN = "https://portal-dev.verification.invalid"
SYN_PROD_ORIGIN = "https://portal-prod.verification.invalid"


@pytest.fixture(autouse=True)
def _synthetic_origin_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    profile = home / ".config" / "sirhosp" / "verification.env"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        f"SIRHOSP_VERIFY_DEV_ORIGIN={SYN_DEV_ORIGIN}\n"
        f"SIRHOSP_VERIFY_PROD_ORIGIN={SYN_PROD_ORIGIN}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def controller():
    return importlib.import_module("scripts.verify_portal")


@pytest.fixture
def host(controller, tmp_path, monkeypatch):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    target = SimpleNamespace(slug="dev", fingerprint="d" * 64, web_running=True)
    calls: list[str] = []
    pair = {
        "snapshot": SNAPSHOT,
        "user": {
            "username": "verify_user",
            "exists": False,
            "owned": True,
            "is_active": False,
            "has_usable_password": False,
            "token": "",
            "user_id": None,
            "is_staff": False,
            "is_superuser": False,
            "must_change_password": None,
        },
        "admin": {
            "username": "verify_admin",
            "exists": False,
            "owned": True,
            "is_active": False,
            "has_usable_password": False,
            "token": "",
            "user_id": None,
            "is_staff": False,
            "is_superuser": False,
            "must_change_password": None,
        },
    }

    def django(target, action, **kwargs):
        calls.append(action)
        if action == "prepare":
            for index, name in enumerate(("user", "admin"), 1):
                pair[name].update(
                    exists=True, token="vfyP:" + kwargs["run_id"] + ":revision", user_id=index
                )
            pair["snapshot"] = "e" * 64
            return {"snapshot_after": pair["snapshot"]}
        if action == "open":
            assert "prepare" in calls
            assert kwargs["expect_state"] == pair["snapshot"]
            assert controller._read_state("dev").expect_state == pair["snapshot"]
            assert controller._read_state("dev").state == "OPENING"
            assert "arm" in calls and "confirm" in calls
            for index, name in enumerate(("user", "admin"), 1):
                pair[name].update(
                    exists=True,
                    is_active=True,
                    has_usable_password=True,
                    token="vfyA:" + kwargs["run_id"] + ":revision",
                    user_id=index,
                )
            return {
                "pair_ids": [1, 2],
                "passwords": {
                    "verify_user": "ephemeral-user-output",
                    "verify_admin": "ephemeral-admin-output",
                },
                "snapshot_after": NEXT * 2,
            }
        if action in {"close", "recover"}:
            for name in ("user", "admin"):
                if pair[name].get("exists"):
                    pair[name].update(
                        is_active=False,
                        has_usable_password=False,
                        token="vfyR:" + kwargs["run_id"] + ":revision",
                    )
                else:
                    pair[name].update(
                        is_active=False, has_usable_password=False, token="", user_id=None
                    )
            return {"revoked": True, "already_revoked": False, "snapshot_after": NEXT * 2}
        return {"pair": pair, "debug": False, "migrations_clean": True}

    monkeypatch.setattr(controller, "_resolve_target", lambda target: target_obj(target))

    def target_obj(name):
        controller._validate_target(name)
        return target

    monkeypatch.setattr(
        controller,
        "_collect_db_identity",
        lambda *a, **k: ("d" * 64, "172.18.0.2", 5432),
    )

    monkeypatch.setattr(controller, "_gate_open", lambda *a, **k: calls.append("gate"))
    monkeypatch.setattr(controller, "_run_django", django)
    monkeypatch.setattr(controller, "_arm_timer", lambda *a, **k: calls.append("arm"))
    monkeypatch.setattr(controller, "_confirm_timer", lambda *a, **k: calls.append("confirm"))
    monkeypatch.setattr(controller, "_cancel_timer", lambda *a, **k: calls.append("cancel"))
    monkeypatch.setattr(controller, "_gate_start", lambda *a: calls.append("start"))
    monkeypatch.setattr(controller, "_gate_stop", lambda *a: calls.append("stop"))
    return SimpleNamespace(target=target, calls=calls, pair=pair, django=django)


def test_r1_doctor_is_read_only(controller, host, tmp_path):
    assert controller.cmd_doctor("dev", confirm_fictitious=True).status == "PASS"
    assert set(host.calls) <= {"preflight", "owned-status", "gate"}
    assert not (tmp_path / "dev").exists()


@pytest.mark.parametrize(
    "target", ["prod", "staging", "https://portal-other.verification.invalid"]
)
def test_r1_wrong_target_precedes_start(controller, host, target):
    with pytest.raises(controller.Blocked):
        controller.cmd_open(target, confirm_fictitious=True, start=True)
    assert host.calls == []


def test_r1_attestation_required(controller, host):
    with pytest.raises(controller.Blocked):
        controller.cmd_open("dev", confirm_fictitious=False)
    assert "open" not in host.calls


@pytest.mark.parametrize("reason", ["DEBUG", "migration", "workers", "fingerprint"])
def test_r1_open_readiness_blocks_writes(controller, host, monkeypatch, reason):
    monkeypatch.setattr(controller, "_gate_open", Mock(side_effect=controller.Blocked(reason)))
    with pytest.raises(controller.Blocked):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert "open" not in host.calls


def test_r3_open_emits_only_in_memory_and_never_retransmits(controller, host, tmp_path):
    result = controller.cmd_open("dev", confirm_fictitious=True)
    assert result.run_id
    assert set(result.passwords) == {"verify_user", "verify_admin"}
    persisted = (tmp_path / "dev" / "session.json").read_text()
    for password in result.passwords.values():
        assert password not in persisted
        assert password not in repr(result)
    with pytest.raises(controller.Blocked):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert host.calls.count("open") == 1


def test_r5_orphan_requires_explicit_recovery(controller, host):
    host.pair["user"].update(
        exists=True,
        is_active=True,
        has_usable_password=True,
        token="vfyA:" + RUN + ":revision",
        user_id=41,
    )
    with pytest.raises(controller.Blocked):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert "open" not in host.calls
    assert controller.cmd_close("dev", recover=True).status == "PASS"
    controller.cmd_open("dev", confirm_fictitious=True)
    assert host.calls.count("open") == 1


def test_r4_closed_missing_record_never_implies_revocation(controller, host):
    host.pair["user"].update(
        exists=True,
        is_active=True,
        has_usable_password=True,
        token="vfyA:" + RUN + ":revision",
        user_id=42,
    )
    try:
        verdict = controller.cmd_close("dev")
    except controller.Blocked:
        return
    assert not (verdict.status == "PASS" and verdict.revoked)


def test_r6_open_compensation_failed_revocation_never_reports_closed(controller, host, monkeypatch):
    original = host.django

    def failing(target, action, **kwargs):
        if action == "close":
            raise controller.Failure("revocation unreachable")
        result = original(target, action, **kwargs)
        if action == "open":
            raise controller.Failure("activation lost")
        return result

    monkeypatch.setattr(controller, "_run_django", failing)
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller.cmd_open("dev", confirm_fictitious=True, timeout_min=1)
    assert controller._read_state("dev").state != "CLOSED"


def test_r5_malformed_record_requires_recovery(controller, host, tmp_path):
    directory = tmp_path / "dev"
    directory.mkdir()
    (directory / "session.json").write_text('{"state":"unknown"}')
    with pytest.raises(controller.Blocked):
        controller.cmd_open("dev", confirm_fictitious=True)
    stamp = "vfyR:" + RUN + ":" + "f" * 32
    host.pair["user"].update(exists=True, token=stamp, user_id=41)
    host.pair["admin"].update(exists=True, token=stamp, user_id=42)
    assert controller.cmd_close("dev", recover=True).status == "PASS"


def test_r5_stale_callback_never_stops_new_session(controller, host):
    current = controller.cmd_open("dev", confirm_fictitious=True)
    result = controller.cmd_close("dev", run_id=RUN, stop=True)
    assert result.status == "SKIPPED"
    assert "close" not in host.calls and "stop" not in host.calls
    assert controller._read_state("dev").run_id == current.run_id


@pytest.mark.parametrize("uncertain", [False, True])
def test_r6_timer_failure_before_activation_writes_no_accounts(
    controller, host, monkeypatch, uncertain
):
    seam = "_confirm_timer" if uncertain else "_arm_timer"
    monkeypatch.setattr(controller, seam, Mock(side_effect=controller.Blocked("timer")))
    with pytest.raises(controller.Blocked):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert "prepare" not in host.calls and "open" not in host.calls
    assert controller._read_state("dev").state == "CLOSED"
    assert "cancel" in host.calls


@pytest.mark.parametrize("boundary", ["activation", "active-record", "expired", "timer-recheck"])
def test_r6_post_activation_failure_revokes_without_credentials(
    controller, host, monkeypatch, boundary
):
    if boundary == "activation":

        def django(target, action, **kwargs):
            result = host.django(target, action, **kwargs)
            if action == "open":
                raise controller.Failure("acknowledgment lost")
            return result

        monkeypatch.setattr(controller, "_run_django", django)
    elif boundary == "active-record":
        original = controller._write_state

        def write(record):
            if record.state == "ACTIVE":
                raise OSError("state acknowledgment lost")
            return original(record)

        monkeypatch.setattr(controller, "_write_state", write)
    elif boundary == "expired":
        monkeypatch.setattr(controller, "_now", Mock(side_effect=[1000, 1001, 5000]))
    else:
        monkeypatch.setattr(
            controller,
            "_confirm_timer",
            Mock(side_effect=[None, None, controller.Blocked("timer disappeared")]),
        )
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller.cmd_open("dev", confirm_fictitious=True, timeout_min=1)
    assert "close" in host.calls
    assert controller._read_state("dev").state == "CLOSED"
    assert not host.pair["user"]["is_active"]


def test_r6_revocation_failure_is_never_closed(controller, host, monkeypatch):
    result = controller.cmd_open("dev", confirm_fictitious=True)

    def django(target, action, **kwargs):
        if action == "close":
            raise controller.Failure("database unreachable")
        return host.django(target, action, **kwargs)

    monkeypatch.setattr(controller, "_run_django", django)
    verdict = controller.cmd_close("dev", run_id=result.run_id, stop=True)
    assert verdict.status == "FAIL"
    assert controller._read_state("dev").state == "CLOSING"
    assert "cancel" not in host.calls and "stop" not in host.calls
    assert "contain" in verdict.diagnostic.lower()


def test_r6_timer_cancel_failure_is_separate_and_retriable(controller, host, monkeypatch):
    result = controller.cmd_open("dev", confirm_fictitious=True)
    monkeypatch.setattr(
        controller, "_cancel_timer", Mock(side_effect=controller.Blocked("cancel failed"))
    )
    verdict = controller.cmd_close("dev", run_id=result.run_id)
    assert verdict.status != "PASS" and verdict.revoked
    assert controller._read_state("dev").state == "CLOSING"
    assert not host.pair["user"]["is_active"]
    monkeypatch.setattr(controller, "_cancel_timer", lambda *a, **k: None)
    assert controller.cmd_close("dev").status == "PASS"


def test_r4_close_does_not_use_open_readiness(controller, host, monkeypatch):
    controller.cmd_open("dev", confirm_fictitious=True)
    monkeypatch.setattr(
        controller, "_gate_open", Mock(side_effect=AssertionError("opening gate used"))
    )
    assert controller.cmd_close("dev").status == "PASS"


def test_r7_stop_occurs_only_after_verified_revocation(controller, host):
    controller.cmd_open("dev", confirm_fictitious=True)
    assert controller.cmd_close("dev", stop=True).status == "PASS"
    assert host.calls.index("close") < host.calls.index("cancel") < host.calls.index("stop")


def _callback_waiter(root, output):
    module = importlib.import_module("scripts.verify_portal")
    module.STATE_ROOT = Path(root)
    with module._lock("dev", wait_seconds=5):
        Path(output).write_text(module._read_state("dev").state)


def test_r5_deadline_callback_waits_for_failed_holder(controller, host, tmp_path):
    controller.cmd_open("dev", confirm_fictitious=True)
    output = tmp_path / "callback-observed"
    with controller._lock("dev", wait_seconds=1):
        inode = (tmp_path / "dev" / ".lock").stat().st_ino
        process = multiprocessing.get_context("fork").Process(
            target=_callback_waiter, args=(str(tmp_path), str(output))
        )
        process.start()
        time.sleep(0.1)
        assert not output.exists()
    process.join(6)
    assert process.exitcode == 0
    assert output.read_text() == "ACTIVE"
    assert (tmp_path / "dev" / ".lock").stat().st_ino == inode
    assert controller.cmd_close("dev").status == "PASS"


def test_r6_atomic_record_has_only_non_secret_fields(controller, host, tmp_path):
    controller.cmd_open("dev", confirm_fictitious=True)
    record = controller._read_state("dev")
    assert json.loads((tmp_path / "dev" / "session.json").read_text()) == json.loads(
        json.dumps(asdict(record))
    )
    assert set(asdict(record)) == {
        "state",
        "target",
        "run_id",
        "deadline_iso",
        "timer_unit",
        "pair_ids",
    }


def test_r7_service_commands_preserve_other_resources(controller, monkeypatch):
    target = SimpleNamespace(
        compose=["docker", "compose", "-p", "sirhosp", "-f", "compose.yml", "-f", "compose.dev.yml"]
    )
    execute = Mock(return_value="")
    monkeypatch.setattr(controller, "_command", execute)
    monkeypatch.setattr(controller, "_validate_runtime", lambda *a, **k: None)
    controller._gate_start(target)
    controller._gate_stop(target)
    commands = [call.args[0] for call in execute.call_args_list]
    assert commands == [
        target.compose + ["up", "-d", "--no-deps", "--no-build", "--pull", "never", "db", "web"],
        target.compose + ["stop", "web"],
        target.compose + ["stop", "db"],
    ]


def test_r7_stopped_web_fallback_requires_pre_effect_probe(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = SimpleNamespace(
        web_running=False,
        slug="dev",
        fingerprint="d" * 64,
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
        compose=["docker", "compose"],
    )
    probe = Mock(side_effect=controller.Blocked("aliases or database route unproved"))
    monkeypatch.setattr(controller, "_probe_one_shot", probe)
    mutate = Mock()
    monkeypatch.setattr(controller, "_command", mutate)
    with pytest.raises(controller.Blocked):
        controller._run_django(target, "close", run_id=RUN)
    probe.assert_called_once()
    mutate.assert_not_called()


def _fake_docker(
    monkeypatch,
    controller,
    *,
    ps_lines,
    volume="sirhosp_sirhosp_db_data",
    mounts="sirhosp_sirhosp_db_data|/var/lib/postgresql/data",
    networks_ip="172.18.0.2",
    ports="5432/tcp",
):
    seen: list[list[str]] = []

    def fake(argv, **kwargs):
        seen.append(list(argv))
        text = " ".join(argv)
        if "version" in argv:
            return "28.0.0"
        if "volume" in argv:
            return volume
        if "Mounts" in text:
            return mounts
        if "sirhosp_default" in text or "Networks" in text:
            return networks_ip
        if "Ports" in text:
            return ports
        if "IPAddress" in text:
            return ""
        if "ps" in argv:
            return "\n".join(ps_lines)
        return ""

    monkeypatch.setattr(controller, "_command", fake)
    return seen


def _checkout_tmp(monkeypatch, controller, tmp_path):
    monkeypatch.setattr(controller, "DEV_CHECKOUT", tmp_path)
    (tmp_path / "compose.yml").write_text("sirhosp_db_data")
    (tmp_path / "compose.dev.yml").write_text("sirhosp-web")
    return str(tmp_path)


def _good_preflight():
    return {
        "debug": False,
        "migrations_clean": True,
        "fingerprint": "d" * 64,
        "server_address": "172.18.0.2",
        "server_port": 5432,
    }


def _dev_ps(*, web_state="running", checkout="/projects/dev/sirhosp"):
    files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
    return [
        f"sirhosp-db|db|sirhosp|running|{checkout}|{files}",
        f"sirhosp-web|web|sirhosp|{web_state}|{checkout}|{files}",
    ]


def test_f1_forbidden_socket_blocks_resolve(controller, monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1002/docker.sock")
    _fake_docker(monkeypatch, controller, ps_lines=_dev_ps())
    with pytest.raises(controller.Blocked):
        controller._resolve_target("dev")


def test_f1_unexpected_engine_blocks_resolve(controller, monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/9999/docker.sock")
    _fake_docker(monkeypatch, controller, ps_lines=_dev_ps())
    with pytest.raises(controller.Blocked):
        controller._resolve_target("dev")


def test_f1_volume_mismatch_blocks_resolve(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    _fake_docker(monkeypatch, controller, ps_lines=_dev_ps(checkout=checkout), volume="other_data")
    with pytest.raises(controller.Blocked):
        controller._resolve_target("dev")


def test_f1_label_mismatch_blocks_resolve(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    _fake_docker(
        monkeypatch,
        controller,
        ps_lines=[f"sirhosp-db|db|other|running|{checkout}|compose.yml,compose.dev.yml"],
    )
    with pytest.raises(controller.Blocked):
        controller._resolve_target("dev")


def test_f1_web_running_discovery(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    _fake_docker(monkeypatch, controller, ps_lines=_dev_ps(web_state="running", checkout=checkout))
    assert controller._resolve_target("dev").web_running is True
    _fake_docker(monkeypatch, controller, ps_lines=_dev_ps(web_state="exited", checkout=checkout))
    assert controller._resolve_target("dev").web_running is False


def test_f1_open_readiness_blocks_but_close_unaffected(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    _fake_docker(monkeypatch, controller, ps_lines=_dev_ps(checkout=checkout))
    target = controller._resolve_target("dev")
    bad = dict(_good_preflight(), debug=True)
    with pytest.raises(controller.Blocked):
        controller._gate_open(target, preflight=bad)


def test_f1_migration_and_workers_block_open(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    _fake_docker(monkeypatch, controller, ps_lines=_dev_ps(checkout=checkout))
    target = controller._resolve_target("dev")
    drift = dict(_good_preflight(), migrations_clean=False)
    with pytest.raises(controller.Blocked):
        controller._gate_open(target, preflight=drift)
    busy = _dev_ps(checkout=checkout) + [
        f"sirhosp-worker-1|worker|sirhosp|running|{checkout}|"
        f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
    ]
    _fake_docker(monkeypatch, controller, ps_lines=busy)
    target = controller._resolve_target("dev")
    with pytest.raises(controller.Blocked):
        controller._gate_open(target, preflight=_good_preflight())


def test_f2_argv_close_includes_python_and_flags(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    seen: list[list[str]] = []

    def fake(argv, **kwargs):
        seen.append(list(argv))
        return json.dumps({"revoked": True})

    monkeypatch.setattr(controller, "_command", fake)
    target = SimpleNamespace(
        slug="dev",
        web_running=True,
        compose=["docker", "compose"],
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
    )
    controller._run_django(target, "close", run_id=RUN, expect_db_fingerprint="d" * 64)
    argv = seen[0]
    assert "/opt/venv/bin/python" in argv
    assert "--dev-context-confirm" in argv
    assert "--target" in argv and "dev" in argv
    assert "--expect-db-fingerprint" in argv
    assert RUN in argv
    assert not any("password" in part.lower() for part in argv)


def _verified_target(checkout):
    return SimpleNamespace(
        slug="dev",
        web_running=True,
        compose=["docker", "compose"],
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
    )


def test_f2_rejects_password_and_unknown_action(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    mutate = Mock(return_value="{}")
    monkeypatch.setattr(controller, "_command", mutate)
    target = _verified_target(checkout)
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller._run_django(target, "reset", run_id=RUN)
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller._run_django(target, "close", run_id=RUN, password="secret")
    mutate.assert_not_called()


def test_f2_malformed_and_timeout_become_controlled(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    monkeypatch.setattr(controller, "_command", Mock(return_value="not-json"))
    target = _verified_target(checkout)
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller._run_django(target, "close", run_id=RUN, expect_db_fingerprint="d" * 64)
    import subprocess

    monkeypatch.setattr(
        controller, "_command", Mock(side_effect=subprocess.TimeoutExpired("docker", 1))
    )
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller._run_django(target, "close", run_id=RUN, expect_db_fingerprint="d" * 64)


def test_f2_open_forwards_snapshot_and_checks_endpoint(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    seen: list[list[str]] = []

    def fake(argv, **kwargs):
        seen.append(list(argv))
        return json.dumps(
            {
                "fingerprint": "d" * 64,
                "server_address": "172.18.0.2",
                "server_port": 5432,
                "snapshot_after": "e" * 64,
            }
        )

    monkeypatch.setattr(controller, "_command", fake)
    target = SimpleNamespace(
        slug="dev",
        web_running=True,
        compose=["docker", "compose"],
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
    )
    result = controller._run_django(
        target, "open", run_id=RUN, expect_state="c" * 64, expect_db_fingerprint="d" * 64
    )
    assert result["snapshot_after"] == "e" * 64
    argv = seen[0]
    assert "--expect-state" in argv and "c" * 64 in argv
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller._run_django(target, "open", run_id=RUN, expect_state="c" * 64)


def _realistic_docker(monkeypatch, controller, *, mounts, networks_ip, ports, ps_lines):
    def fake(argv, **kwargs):
        text = " ".join(argv)
        if "version" in argv:
            return "28.0.0"
        if "volume" in argv:
            return "sirhosp_sirhosp_db_data"
        if "Mounts" in text:
            return mounts
        if 'Networks "sirhosp_default"' in text or "Networks" in text:
            return networks_ip
        if "Ports" in text:
            return ports
        if "IPAddress" in text and "Networks" not in text:
            return ""
        if "ps" in argv:
            return "\n".join(ps_lines)
        return ""

    monkeypatch.setattr(controller, "_command", fake)


def _checked_ps(*, checkout="/projects/dev/sirhosp"):
    files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
    return [
        f"sirhosp-db|db|sirhosp|running|{checkout}|{files}",
        f"sirhosp-web|web|sirhosp|running|{checkout}|{files}",
    ]


def test_recheck_volume_present_but_not_mounted_blocks(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    monkeypatch.setattr(controller, "DEV_CHECKOUT", tmp_path)
    (tmp_path / "compose.yml").write_text("sirhosp_db_data")
    (tmp_path / "compose.dev.yml").write_text("sirhosp-web")
    _realistic_docker(
        monkeypatch,
        controller,
        mounts="other_data|/var/lib/postgresql/data",
        networks_ip="172.18.0.2",
        ports="5432/tcp",
        ps_lines=_checked_ps(checkout=str(tmp_path)),
    )
    with pytest.raises(controller.Blocked):
        controller._resolve_target("dev")


def test_recheck_foreign_checkout_with_matching_labels_blocks(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    monkeypatch.setattr(controller, "DEV_CHECKOUT", tmp_path)
    (tmp_path / "compose.yml").write_text("sirhosp_db_data")
    (tmp_path / "compose.dev.yml").write_text("sirhosp-web")
    _realistic_docker(
        monkeypatch,
        controller,
        mounts="sirhosp_sirhosp_db_data|/var/lib/postgresql/data",
        networks_ip="172.18.0.2",
        ports="5432/tcp",
        ps_lines=_checked_ps(checkout="/other/checkout"),
    )
    with pytest.raises(controller.Blocked):
        controller._resolve_target("dev")


def test_recheck_named_network_resolves_without_legacy_field(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    monkeypatch.setattr(controller, "DEV_CHECKOUT", tmp_path)
    (tmp_path / "compose.yml").write_text("sirhosp_db_data")
    (tmp_path / "compose.dev.yml").write_text("sirhosp-web")
    _realistic_docker(
        monkeypatch,
        controller,
        mounts="sirhosp_sirhosp_db_data|/var/lib/postgresql/data",
        networks_ip="172.18.0.2",
        ports="5432/tcp",
        ps_lines=_checked_ps(checkout=str(tmp_path)),
    )
    target = controller._resolve_target("dev")
    assert target.db_address == "172.18.0.2"
    assert target.db_port == 5432


def test_recheck_unproved_port_fails_closed(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    monkeypatch.setattr(controller, "DEV_CHECKOUT", tmp_path)
    (tmp_path / "compose.yml").write_text("sirhosp_db_data")
    (tmp_path / "compose.dev.yml").write_text("sirhosp-web")
    _realistic_docker(
        monkeypatch,
        controller,
        mounts="sirhosp_sirhosp_db_data|/var/lib/postgresql/data",
        networks_ip="172.18.0.2",
        ports="",
        ps_lines=_checked_ps(checkout=str(tmp_path)),
    )
    with pytest.raises(controller.Blocked):
        controller._resolve_target("dev")


def test_recheck_collector_uses_shell_bootstrap(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    seen: list[list[str]] = []

    def fake(argv, **kwargs):
        seen.append(list(argv))
        return json.dumps(["d" * 64, "172.18.0.2", 5432])

    monkeypatch.setattr(controller, "_command", fake)
    target = SimpleNamespace(
        slug="dev",
        web_running=True,
        compose=["docker", "compose"],
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
    )
    controller._collect_db_identity(target)
    argv = seen[0]
    assert "shell" in argv and "-c" in argv
    assert any("database_identity" in part for part in argv)
    assert not any(part == "-c" and "import" not in " ".join(argv) for part in argv)


def test_recheck_command_sanitizes_context_at_subprocess_boundary(controller, monkeypatch):
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["env"] = dict(kwargs.get("env") or {})
        return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    monkeypatch.setenv("DOCKER_CONTEXT", "prod-context")
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    controller._command(["docker", "version"], docker_host="unix:///run/user/1003/docker.sock")
    assert captured["env"].get("DOCKER_HOST") == "unix:///run/user/1003/docker.sock"
    assert "DOCKER_CONTEXT" not in captured["env"]


def test_recheck_runner_refuses_unverified_target(controller, monkeypatch):
    monkeypatch.setattr(controller, "_command", Mock(return_value="{}"))
    target = SimpleNamespace(slug="dev", web_running=True, compose=["docker", "compose"])
    with pytest.raises(controller.Blocked):
        controller._run_django(target, "close", run_id=RUN, expect_db_fingerprint="d" * 64)


def test_recheck_doctor_applies_readiness(controller, monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    _realistic_docker(
        monkeypatch,
        controller,
        mounts="sirhosp_sirhosp_db_data|/var/lib/postgresql/data",
        networks_ip="172.18.0.2",
        ports="5432/tcp",
        ps_lines=_checked_ps(checkout=checkout),
    )
    monkeypatch.setattr(
        controller,
        "_collect_db_identity",
        lambda *a, **k: ("d" * 64, "172.18.0.2", 5432),
    )

    def bad_preflight(target, action, **kwargs):
        assert action == "preflight"
        return {
            "fingerprint": "d" * 64,
            "server_address": "172.18.0.2",
            "server_port": 5432,
            "debug": True,
            "migrations_clean": True,
        }

    monkeypatch.setattr(controller, "_run_django", bad_preflight)
    with pytest.raises(controller.Blocked):
        controller.cmd_doctor("dev", confirm_fictitious=True)


def test_recheck_missing_endpoint_is_not_proof(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = SimpleNamespace(
        slug="dev",
        web_running=True,
        compose=["docker", "compose"],
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
    )
    with pytest.raises(controller.Blocked):
        controller._gate_open(
            target,
            preflight={"debug": False, "migrations_clean": True, "fingerprint": "d" * 64},
        )
    with pytest.raises(controller.Blocked):
        controller._check_django_response(target, "preflight", "d" * 64, {"fingerprint": "d" * 64})


def _quiet_collector_fake(monkeypatch, controller):
    seen: list[list[str]] = []
    banner = (
        "Django version 5.2.13\nPython 3.12\n"
        ">>> from apps.accounts.management.commands.verification_session import database_identity\n"
    )

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        if "shell" in argv and "-c" in argv and "--verbosity" in argv:
            idx = argv.index("--verbosity")
            if argv[idx + 1 : idx + 2] == ["0"]:
                return SimpleNamespace(
                    returncode=0, stdout=json.dumps(["d" * 64, "172.18.0.2", 5432]), stderr=""
                )
        if "shell" in argv and "-c" in argv:
            return SimpleNamespace(
                returncode=0, stdout=banner + json.dumps(["d" * 64, "172.18.0.2", 5432]), stderr=""
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    return seen


def test_r1_collector_requires_quiet_shell_output(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = SimpleNamespace(
        slug="dev",
        web_running=True,
        compose=["docker", "compose"],
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
    )
    _quiet_collector_fake(monkeypatch, controller)
    fingerprint, address, port = controller._collect_db_identity(target)
    assert (fingerprint, address, port) == ("d" * 64, "172.18.0.2", 5432)


def test_r1_collector_malformed_and_empty_are_controlled(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = SimpleNamespace(
        slug="dev",
        web_running=True,
        compose=["docker", "compose"],
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
    )
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
    )
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller._collect_db_identity(target)
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller._collect_db_identity(target)


@pytest.mark.parametrize("bad_port", [5432.9, 5432.0, True, False, [5432], "invalid", "  "])
def test_portfix_collector_rejects_noninteger_port(controller, monkeypatch, tmp_path, bad_port):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = SimpleNamespace(
        slug="dev",
        web_running=True,
        compose=["docker", "compose"],
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
    )
    payload = json.dumps(["d" * 64, "172.18.0.2", bad_port])
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=payload, stderr=""),
    )
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller._collect_db_identity(target)


def test_portfix_collector_rejects_huge_port(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = SimpleNamespace(
        slug="dev",
        web_running=True,
        compose=["docker", "compose"],
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
    )
    payload = json.dumps(["d" * 64, "172.18.0.2", 5432])
    payload = payload.replace("5432", "1e400")
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=payload, stderr=""),
    )
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller._collect_db_identity(target)


def _resolve_fake(monkeypatch, controller, *, config_files, ports="5432/tcp"):
    def fake(argv, **kwargs):
        text = " ".join(argv)
        if "version" in argv:
            return "28.0.0"
        if "volume" in argv:
            return "sirhosp_sirhosp_db_data"
        if "Mounts" in text:
            return "sirhosp_sirhosp_db_data|/var/lib/postgresql/data"
        if "sirhosp_default" in text:
            return "172.18.0.2"
        if "Ports" in text:
            return ports
        if "ps" in argv:
            return "\n".join(config_files)
        return ""

    monkeypatch.setattr(controller, "_command", fake)


def _both_ps(checkout, db_configs, web_configs):
    return [
        f"sirhosp-db|db|sirhosp|running|{checkout}|{db_configs}",
        f"sirhosp-web|web|sirhosp|running|{checkout}|{web_configs}",
    ]


def test_r2_config_extra_override_blocks(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    extra = f"{checkout}/compose.yml,{checkout}/compose.dev.yml,{checkout}/extra.yml"
    _resolve_fake(
        monkeypatch,
        controller,
        config_files=_both_ps(checkout, extra, extra),
    )
    with pytest.raises(controller.Blocked) as excinfo:
        controller._resolve_target("dev")
    assert "provenance" in str(excinfo.value)


def test_r2_config_outside_path_blocks(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    outside = "/other/checkout/compose.yml,/other/checkout/compose.dev.yml"
    _resolve_fake(
        monkeypatch,
        controller,
        config_files=_both_ps(checkout, outside, outside),
    )
    with pytest.raises(controller.Blocked) as excinfo:
        controller._resolve_target("dev")
    assert "provenance" in str(excinfo.value)


def test_r2_config_duplicate_blocks(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    dup = f"{checkout}/compose.yml,{checkout}/compose.yml"
    _resolve_fake(
        monkeypatch,
        controller,
        config_files=_both_ps(checkout, dup, dup),
    )
    with pytest.raises(controller.Blocked) as excinfo:
        controller._resolve_target("dev")
    assert "provenance" in str(excinfo.value)


def test_r2_config_wrong_order_blocks(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    swapped = f"{checkout}/compose.dev.yml,{checkout}/compose.yml"
    _resolve_fake(
        monkeypatch,
        controller,
        config_files=_both_ps(checkout, swapped, swapped),
    )
    with pytest.raises(controller.Blocked) as excinfo:
        controller._resolve_target("dev")
    assert "provenance" in str(excinfo.value)


def test_r2_config_lookalike_blocks(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    look = f"{checkout}/notcompose.yml,{checkout}/compose.dev.yml"
    _resolve_fake(
        monkeypatch,
        controller,
        config_files=_both_ps(checkout, look, look),
    )
    with pytest.raises(controller.Blocked) as excinfo:
        controller._resolve_target("dev")
    assert "provenance" in str(excinfo.value)


def test_r2_port_token_is_exact(controller, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    good = [
        f"sirhosp-db|db|sirhosp|running|{checkout}|{checkout}/compose.yml,{checkout}/compose.dev.yml",
        f"sirhosp-web|web|sirhosp|running|{checkout}|{checkout}/compose.yml,{checkout}/compose.dev.yml",
    ]
    _resolve_fake(monkeypatch, controller, config_files=good, ports="15432/tcp")
    with pytest.raises(controller.Blocked):
        controller._resolve_target("dev")


def test_r3_divergent_endpoint_blocks_before_up(controller, monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        text = " ".join(argv)
        if "version" in argv:
            return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")
        if "volume" in argv:
            return SimpleNamespace(returncode=0, stdout="sirhosp_sirhosp_db_data", stderr="")
        if "Mounts" in text:
            return SimpleNamespace(
                returncode=0, stdout="sirhosp_sirhosp_db_data|/var/lib/postgresql/data", stderr=""
            )
        if "sirhosp_default" in text:
            return SimpleNamespace(returncode=0, stdout="172.18.0.2", stderr="")
        if "Ports" in text:
            return SimpleNamespace(returncode=0, stdout="5432/tcp", stderr="")
        if "database_identity" in text:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(["d" * 64, "10.0.0.9", 5432]), stderr=""
            )
        if "ps" in argv:
            files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
            line = f"sirhosp-db|db|sirhosp|running|{checkout}|{files}"
            web = f"sirhosp-web|web|sirhosp|running|{checkout}|{files}"
            return SimpleNamespace(returncode=0, stdout=f"{line}\n{web}", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    with pytest.raises(controller.Blocked):
        controller.cmd_open("dev", confirm_fictitious=True, start=True)
    assert not any("up" in argv for argv in calls)
    assert not any("prepare" in argv for argv in calls)
    assert not any("open" in argv and "verification_session" in argv for argv in calls)


def test_r3_unproved_stopped_path_has_no_start_effect(controller, monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        text = " ".join(argv)
        if "version" in argv:
            return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")
        if "volume" in argv:
            return SimpleNamespace(returncode=0, stdout="sirhosp_sirhosp_db_data", stderr="")
        if "Mounts" in text:
            return SimpleNamespace(
                returncode=0, stdout="sirhosp_sirhosp_db_data|/var/lib/postgresql/data", stderr=""
            )
        if "sirhosp_default" in text:
            return SimpleNamespace(returncode=0, stdout="172.18.0.2", stderr="")
        if "Ports" in text:
            return SimpleNamespace(returncode=0, stdout="5432/tcp", stderr="")
        if "ps" in argv:
            files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
            db = f"sirhosp-db|db|sirhosp|exited|{checkout}|{files}"
            web = f"sirhosp-web|web|sirhosp|exited|{checkout}|{files}"
            return SimpleNamespace(returncode=0, stdout=f"{db}\n{web}", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="nope")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    with pytest.raises(controller.Blocked):
        controller.cmd_open("dev", confirm_fictitious=True, start=True)
    assert not any("up" in argv for argv in calls)


def test_r4_invalid_port_types_are_rejected(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = SimpleNamespace(
        slug="dev",
        web_running=True,
        compose=["docker", "compose"],
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
    )
    for bad in (True, False, 5432.0, [5432], "invalid"):
        with pytest.raises(controller.Blocked):
            controller._gate_open(
                target,
                preflight={
                    "debug": False,
                    "migrations_clean": True,
                    "fingerprint": "d" * 64,
                    "server_address": "172.18.0.2",
                    "server_port": bad,
                },
            )


def test_r4_subprocess_errors_are_controlled(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = SimpleNamespace(
        slug="dev",
        web_running=True,
        compose=["docker", "compose"],
        docker_host="unix:///run/user/1003/docker.sock",
        checkout=checkout,
        volume="sirhosp_sirhosp_db_data",
        db_address="172.18.0.2",
        db_port=5432,
    )
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        Mock(side_effect=FileNotFoundError("docker")),
    )
    with pytest.raises((controller.Blocked, controller.Failure)) as excinfo:
        controller._run_django(target, "close", run_id=RUN, expect_db_fingerprint="d" * 64)
    assert "docker" not in str(excinfo.value).lower() or "command" in str(excinfo.value).lower()
    assert "traceback" not in str(excinfo.value).lower()


def test_r3_start_refreshes_discovery(controller, monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    calls: list[list[str]] = []
    pair = {
        "snapshot": "c" * 64,
        "user": {
            "username": "verify_user",
            "user_id": None,
            "token": "",
            "exists": False,
            "owned": True,
            "is_active": False,
            "has_usable_password": False,
            "is_staff": False,
            "is_superuser": False,
            "must_change_password": None,
        },
        "admin": {
            "username": "verify_admin",
            "user_id": None,
            "token": "",
            "exists": False,
            "owned": True,
            "is_active": False,
            "has_usable_password": False,
            "is_staff": False,
            "is_superuser": False,
            "must_change_password": None,
        },
    }

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        text = " ".join(argv)
        if "version" in argv:
            return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")
        if "volume" in argv:
            return SimpleNamespace(returncode=0, stdout="sirhosp_sirhosp_db_data", stderr="")
        if "Mounts" in text:
            out = "sirhosp_sirhosp_db_data|/var/lib/postgresql/data"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if "sirhosp_default" in text:
            return SimpleNamespace(returncode=0, stdout="172.18.0.2", stderr="")
        if "Ports" in text:
            return SimpleNamespace(returncode=0, stdout="5432/tcp", stderr="")
        if "database_identity" in text:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(["d" * 64, "172.18.0.2", 5432]), stderr=""
            )
        if "verification_session" in text:
            if " preflight " in f" {text} ":
                payload = {
                    "fingerprint": "d" * 64,
                    "server_address": "172.18.0.2",
                    "server_port": 5432,
                    "pair": pair,
                    "debug": False,
                    "migrations_clean": True,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            if " owned-status " in f" {text} ":
                payload = {
                    "fingerprint": "d" * 64,
                    "server_address": "172.18.0.2",
                    "server_port": 5432,
                    "pair": pair,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            if " prepare " in f" {text} ":
                return SimpleNamespace(
                    returncode=0, stdout=json.dumps({"snapshot_after": "e" * 64}), stderr=""
                )
            if " open " in f" {text} ":
                payload = {
                    "pair_ids": [1, 2],
                    "passwords": {"verify_user": "u" * 43, "verify_admin": "a" * 43},
                    "snapshot_after": "f" * 64,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")
        if "ps" in argv:
            files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
            db = f"sirhosp-db|db|sirhosp|running|{checkout}|{files}"
            web = f"sirhosp-web|web|sirhosp|running|{checkout}|{files}"
            return SimpleNamespace(returncode=0, stdout=f"{db}\n{web}", stderr="")
        if "systemctl" in argv:
            return SimpleNamespace(returncode=0, stdout="active", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    monkeypatch.setattr(controller, "_arm_timer", lambda *a, **k: None)
    monkeypatch.setattr(controller, "_confirm_timer", lambda *a, **k: None)
    monkeypatch.setattr(controller, "_cancel_timer", lambda *a, **k: None)
    result = controller.cmd_open("dev", confirm_fictitious=True, start=True)
    assert result.run_id
    ps_calls = [argv for argv in calls if "ps" in argv]
    up_calls = [argv for argv in calls if "up" in argv]
    assert up_calls, "expected compose up for authorized start"
    assert len(ps_calls) >= 3, "expected re-resolve after start, not stale discovery"


def test_portfix_poststart_drift_blocks_before_prepare(controller, monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    calls: list[list[str]] = []
    phase = {"started": False}

    def files():
        return f"{checkout}/compose.yml,{checkout}/compose.dev.yml"

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        text = " ".join(argv)
        if "version" in argv:
            return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")
        if "volume" in argv:
            return SimpleNamespace(returncode=0, stdout="sirhosp_sirhosp_db_data", stderr="")
        if "Mounts" in text:
            out = "sirhosp_sirhosp_db_data|/var/lib/postgresql/data"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if "sirhosp_default" in text:
            return SimpleNamespace(returncode=0, stdout="172.18.0.2", stderr="")
        if "Ports" in text:
            return SimpleNamespace(returncode=0, stdout="5432/tcp", stderr="")
        if "database_identity" in text:
            route = "10.0.0.9" if phase["started"] else "172.18.0.2"
            out = json.dumps(["d" * 64, route, 5432])
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if "verification_session" in text:
            return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")
        if "ps" in argv:
            db = f"sirhosp-db|db|sirhosp|running|{checkout}|{files()}"
            web = f"sirhosp-web|web|sirhosp|running|{checkout}|{files()}"
            return SimpleNamespace(returncode=0, stdout=f"{db}\n{web}", stderr="")
        if argv[:2] == ["docker", "compose"] and "up" in argv:
            phase["started"] = True
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "systemctl" in argv:
            return SimpleNamespace(returncode=0, stdout="active", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    with pytest.raises(controller.Blocked) as excinfo:
        controller.cmd_open("dev", confirm_fictitious=True, start=True)
    assert "route" in str(excinfo.value).lower()
    assert not any("prepare" in argv for argv in calls)
    assert not any(" open " in f" {' '.join(argv)} " for argv in calls)


def _timer_base(run_id=RUN):
    return f"sirhosp-verify-{run_id}"


def _callback_argv(checkout, run_id=RUN):
    import sys

    return [
        sys.executable,
        str(Path(checkout) / "scripts" / "verify_portal.py"),
        "callback",
        "--target",
        "dev",
        "--run-id",
        run_id,
    ]


def test_t3_arm_registers_transient_timer_with_callback(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = _verified_target(checkout)
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        out = f"Running as unit: {_timer_base()}.timer\n"
        out += f"Will run service as unit: {_timer_base()}.service"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    controller._arm_timer(target, RUN, _timer_base(), "2030-01-01T00:00:00+00:00")
    argv = seen[0]
    assert argv[:3] == ["systemd-run", "--user", f"--unit={_timer_base()}"]
    assert "--on-calendar=2030-01-01 00:00:00 UTC" in argv
    assert "--timer-property=AccuracySec=1s" in argv
    assert "--property=TimeoutStartSec=infinity" in argv
    assert not any(part.startswith("--on-active") for part in argv)
    plain = [part for part in argv if not part.startswith("--")]
    assert plain[0] == "systemd-run"
    assert argv[argv.index(_callback_argv(checkout)[0]) :] == _callback_argv(checkout)


def _good_exec_stanza(checkout, run_id=RUN):
    words = _callback_argv(checkout, run_id)
    return (
        "{ path=" + words[0] + " ; argv[]=" + " ".join(words) + " ; ignore_errors=no ; "
        "start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"
    )


def test_t3_arm_rejects_foreign_unit_name(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = _verified_target(checkout)
    mutate = Mock()
    monkeypatch.setattr(controller.subprocess, "run", mutate)
    with pytest.raises(controller.Blocked):
        controller._arm_timer(target, RUN, "other-unit", "2030-01-01T00:00:00+00:00")
    mutate.assert_not_called()


def test_t3_arm_treats_quiet_success_as_attempt(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = _verified_target(checkout)
    seen: list[list[str]] = []

    def quiet(argv, **kwargs):
        seen.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="some localized noise\n")

    monkeypatch.setattr(controller.subprocess, "run", quiet)
    controller._arm_timer(target, RUN, _timer_base(), "2030-01-01T00:00:00+00:00")
    argv = seen[0]
    assert "--setenv=DOCKER_HOST=unix:///run/user/1003/docker.sock" in argv
    assert "--property=Type=oneshot" in argv


def test_t3_confirm_requires_infinite_service_timeout(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = _verified_target(checkout)
    seen: list[list[str]] = []
    _confirm_fake(monkeypatch, controller, start_timeout="t 90000000", checkout=checkout)
    original = controller.subprocess.run

    def recording(argv, **kwargs):
        seen.append(list(argv))
        return original(argv, **kwargs)

    monkeypatch.setattr(controller.subprocess, "run", recording)
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, "2030-01-01T00:00:00+00:00")
    assert any("TimeoutStartUSec" in part for argv in seen for part in argv)


def _confirm_fake(
    monkeypatch,
    controller,
    *,
    active="active",
    load="loaded",
    transient="yes",
    timer_transient="yes",
    stanza=None,
    elapse="t 1893456000000000",
    start_timeout="t 18446744073709551615",
    service_type='s "oneshot"',
    unit=None,
    checkout=None,
    run_id=RUN,
):
    if stanza is None:
        assert checkout is not None
        stanza = _good_exec_stanza(checkout, run_id)
    if unit is None:
        unit = f's "sirhosp-verify-{run_id}.service"'

    def fake_run(argv, **kwargs):
        text = " ".join(argv)
        if "get-property" in argv:
            if argv[-1] == "TimeoutStartUSec":
                return SimpleNamespace(returncode=0, stdout=start_timeout, stderr="")
            if argv[-1] == "Unit":
                return SimpleNamespace(returncode=0, stdout=unit, stderr="")
            if argv[-1] == "Type":
                return SimpleNamespace(returncode=0, stdout=service_type, stderr="")
            return SimpleNamespace(returncode=0, stdout=elapse, stderr="")
        if "ActiveState" in text:
            return SimpleNamespace(returncode=0, stdout=active, stderr="")
        if "LoadState" in text:
            return SimpleNamespace(returncode=0, stdout=load, stderr="")
        if "Transient" in text:
            if ".service" in text:
                return SimpleNamespace(returncode=0, stdout=transient, stderr="")
            return SimpleNamespace(returncode=0, stdout=timer_transient, stderr="")
        if "ExecStart" in text:
            return SimpleNamespace(returncode=0, stdout=stanza, stderr="")
        if "Type" in text:
            return SimpleNamespace(returncode=0, stdout=service_type, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)


def test_t3_confirm_checks_timer_unit_points_to_service(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = _verified_target(checkout)
    deadline = "2030-01-01T00:00:00+00:00"
    _confirm_fake(monkeypatch, controller, unit='s "other.service"', checkout=checkout)
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, deadline)
    _confirm_fake(monkeypatch, controller, unit="", checkout=checkout)
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, deadline)
    _confirm_fake(
        monkeypatch,
        controller,
        unit='s "sirhosp-verify-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.service" extra',
        checkout=checkout,
    )
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, deadline)


def test_t3_confirm_requires_transient_timer(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = _verified_target(checkout)
    _confirm_fake(monkeypatch, controller, timer_transient="no", checkout=checkout)
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, "2030-01-01T00:00:00+00:00")


def test_t3_confirm_requires_oneshot_service(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = _verified_target(checkout)
    _confirm_fake(monkeypatch, controller, service_type='s "simple"', checkout=checkout)
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, "2030-01-01T00:00:00+00:00")


def test_t3_confirm_rejects_inactive_output(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = _verified_target(checkout)
    _confirm_fake(monkeypatch, controller, active="inactive", checkout=checkout)
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, "2030-01-01T00:00:00+00:00")


def test_t3_confirm_requires_schedule_and_service(controller, monkeypatch, tmp_path):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    target = _verified_target(checkout)
    deadline = "2030-01-01T00:00:00+00:00"
    _confirm_fake(monkeypatch, controller, elapse="", checkout=checkout)
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, deadline)
    _confirm_fake(monkeypatch, controller, elapse="Tue 2030-01-01 00:00:00 UTC", checkout=checkout)
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, deadline)
    _confirm_fake(monkeypatch, controller, transient="no", checkout=checkout)
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, deadline)
    _confirm_fake(
        monkeypatch,
        controller,
        stanza="{ path=/bin/false ; argv[]=/bin/false }",
        checkout=checkout,
    )
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, deadline)
    _confirm_fake(
        monkeypatch,
        controller,
        stanza=_good_exec_stanza(checkout) + "\n{ path=/bin/false ; argv[]=/bin/false }",
        checkout=checkout,
    )
    with pytest.raises(controller.Blocked):
        controller._confirm_timer(target, _timer_base(), RUN, deadline)
    _confirm_fake(monkeypatch, controller, checkout=checkout)
    assert controller._confirm_timer(target, _timer_base(), RUN, deadline) is None


def test_t3_disappearance_before_activate_blocks_open(controller, monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    monkeypatch.setattr(controller, "_now", lambda: 1000.0)
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    calls: list[str] = []
    shows = {"count": 0}
    armed: list[list[str]] = []
    pair = {
        "snapshot": "c" * 64,
        "user": {
            "username": "verify_user",
            "user_id": None,
            "token": "",
            "exists": False,
            "owned": True,
            "is_active": False,
            "has_usable_password": False,
            "is_staff": False,
            "is_superuser": False,
            "must_change_password": None,
        },
        "admin": {
            "username": "verify_admin",
            "user_id": None,
            "token": "",
            "exists": False,
            "owned": True,
            "is_active": False,
            "has_usable_password": False,
            "is_staff": False,
            "is_superuser": False,
            "must_change_password": None,
        },
    }

    def fake_run(argv, **kwargs):
        text = " ".join(argv)
        if "systemd-run" in argv:
            armed.append(list(argv))
            base = [part for part in argv if part.startswith("--unit=")][0].split("=", 1)[1]
            out = f"Running as unit: {base}.timer\nWill run service as unit: {base}.service"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if "show" in argv and "ActiveState" in text:
            shows["count"] += 1
            if shows["count"] > 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="not found")
            return SimpleNamespace(returncode=0, stdout="active", stderr="")
        if "show" in argv and "LoadState" in text:
            return SimpleNamespace(returncode=0, stdout="loaded", stderr="")
        if "show" in argv and "Transient" in text:
            return SimpleNamespace(returncode=0, stdout="yes", stderr="")
        if "show" in argv and "ExecStart" in text:
            import sys as _sys

            words = armed[0][armed[0].index(_sys.executable) :]
            stanza = "{ path=" + words[0] + " ; argv[]=" + " ".join(words) + " ; "
            stanza += "ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0"
            return SimpleNamespace(returncode=0, stdout=stanza + " }", stderr="")
        if "get-property" in argv:
            if "TimeoutStartUSec" in text:
                return SimpleNamespace(returncode=0, stdout="t 18446744073709551615", stderr="")
            if argv[-1] == "Unit":
                base = [part for part in armed[0] if part.startswith("--unit=")][0].split("=", 1)[1]
                return SimpleNamespace(returncode=0, stdout=f's "{base}.service"', stderr="")
            if argv[-1] == "Type":
                return SimpleNamespace(returncode=0, stdout='s "oneshot"', stderr="")
            return SimpleNamespace(returncode=0, stdout="t 4600000000", stderr="")
        if "database_identity" in text:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(["d" * 64, "172.18.0.2", 5432]), stderr=""
            )
        if "verification_session" in text:
            action = argv[argv.index("verification_session") + 1]
            calls.append(action)
            if action == "preflight":
                payload = {
                    "fingerprint": "d" * 64,
                    "server_address": "172.18.0.2",
                    "server_port": 5432,
                    "pair": pair,
                    "debug": False,
                    "migrations_clean": True,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            if action == "owned-status":
                payload = {
                    "fingerprint": "d" * 64,
                    "server_address": "172.18.0.2",
                    "server_port": 5432,
                    "pair": pair,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            if action == "prepare":
                return SimpleNamespace(
                    returncode=0, stdout=json.dumps({"snapshot_after": "e" * 64}), stderr=""
                )
            return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")
        if "ps" in argv:
            files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
            db = f"sirhosp-db|db|sirhosp|running|{checkout}|{files}"
            web = f"sirhosp-web|web|sirhosp|running|{checkout}|{files}"
            return SimpleNamespace(returncode=0, stdout=f"{db}\n{web}", stderr="")
        if "version" in argv:
            return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")
        if "volume" in argv:
            return SimpleNamespace(returncode=0, stdout="sirhosp_sirhosp_db_data", stderr="")
        if "Mounts" in text:
            return SimpleNamespace(
                returncode=0, stdout="sirhosp_sirhosp_db_data|/var/lib/postgresql/data", stderr=""
            )
        if "sirhosp_default" in text:
            return SimpleNamespace(returncode=0, stdout="172.18.0.2", stderr="")
        if "Ports" in text:
            return SimpleNamespace(returncode=0, stdout="5432/tcp", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert "open" not in calls
    assert "close" in calls
    assert controller._read_state("dev").state == "CLOSING"


def test_t3_callback_stale_run_skips_quietly(controller, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    controller._write_state(
        controller.ActiveRecord(
            state="ACTIVE",
            target="dev",
            run_id=NEXT,
            deadline_iso="2030-01-01T00:00:00+00:00",
            timer_unit=_timer_base(NEXT) + ".timer",
            pair_ids=(1, 2),
        )
    )
    mutate = Mock()
    monkeypatch.setattr(controller, "_run_django", mutate)
    resolve = Mock(side_effect=AssertionError("metadata resolution must not run for stale runs"))
    monkeypatch.setattr(controller, "_resolve_target", resolve)
    code = controller.main(["callback", "--target", "dev", "--run-id", RUN])
    assert code == 3
    mutate.assert_not_called()
    resolve.assert_not_called()
    assert controller._read_state("dev").run_id == NEXT
    capsys.readouterr()


def test_t3_callback_state_error_is_not_stale(controller, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    directory = tmp_path / "dev"
    directory.mkdir()
    (directory / "session.json").write_text('{"state":"unknown"}')
    mutate = Mock()
    monkeypatch.setattr(controller, "_run_django", mutate)
    code = controller.main(["callback", "--target", "dev", "--run-id", RUN])
    assert code == 1
    mutate.assert_not_called()
    assert (directory / "session.json").read_text() == '{"state":"unknown"}'
    capsys.readouterr()


def test_t3_callback_waits_on_busy_flock_then_closes(controller, monkeypatch, tmp_path, capsys):
    import threading

    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    controller._write_state(
        controller.ActiveRecord(
            state="ACTIVE",
            target="dev",
            run_id=RUN,
            deadline_iso="2030-01-01T00:00:00+00:00",
            timer_unit=_timer_base() + ".timer",
            pair_ids=(1, 2),
        )
    )
    monkeypatch.setattr(
        controller, "_resolve_target", lambda *a, **k: _verified_target(str(tmp_path))
    )
    monkeypatch.setattr(
        controller, "_collect_db_identity", lambda *a, **k: ("d" * 64, "172.18.0.2", 5432)
    )
    monkeypatch.setattr(
        controller,
        "_run_django",
        lambda *a, **k: {"revoked": True, "already_revoked": False, "snapshot_after": "e" * 64},
    )
    monkeypatch.setattr(controller, "_cancel_timer", lambda *a, **k: None)
    real_lock = controller._lock
    waits: list = []

    def spy(slug, wait_seconds=900):
        waits.append(wait_seconds)
        return real_lock(slug, wait_seconds=wait_seconds)

    monkeypatch.setattr(controller, "_lock", spy)
    done = threading.Event()
    outcome: dict = {}

    def invoke():
        outcome["code"] = controller.main(["callback", "--target", "dev", "--run-id", RUN])
        done.set()

    with controller._lock("dev", wait_seconds=30):
        worker = threading.Thread(target=invoke, daemon=True)
        worker.start()
        assert not done.wait(timeout=2)
    assert done.wait(timeout=10)
    worker.join(timeout=10)
    assert outcome["code"] == 0
    assert None in waits, "callback must wait on the lock with no timeout bound"
    assert controller._read_state("dev").state == "CLOSED"
    capsys.readouterr()


def test_t3_deadline_lease_uses_whole_seconds(controller, monkeypatch):
    monkeypatch.setattr(controller, "_now", lambda: 1000.5)
    deadline_ts, deadline_iso = controller._deadline_lease(60)
    assert deadline_ts == 4601
    assert deadline_iso == "1970-01-01T01:16:41+00:00"


def test_t3_callback_never_stops_own_service(controller, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    _checkout_tmp(monkeypatch, controller, tmp_path)
    controller._write_state(
        controller.ActiveRecord(
            state="ACTIVE",
            target="dev",
            run_id=RUN,
            deadline_iso="2030-01-01T00:00:00+00:00",
            timer_unit=_timer_base() + ".timer",
            pair_ids=(1, 2),
        )
    )
    monkeypatch.setattr(
        controller, "_resolve_target", lambda *a, **k: _verified_target(str(tmp_path))
    )
    monkeypatch.setattr(
        controller, "_collect_db_identity", lambda *a, **k: ("d" * 64, "172.18.0.2", 5432)
    )
    monkeypatch.setattr(
        controller,
        "_run_django",
        lambda *a, **k: {"revoked": True, "already_revoked": False, "snapshot_after": "e" * 64},
    )
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    assert controller.main(["callback", "--target", "dev", "--run-id", RUN]) == 0
    stops = [argv for argv in seen if "stop" in argv]
    assert stops
    assert not any(f"{_timer_base()}.service" in argv for argv in stops)
    capsys.readouterr()


def test_t3_callback_failed_revocation_stays_visible(controller, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    controller._write_state(
        controller.ActiveRecord(
            state="ACTIVE",
            target="dev",
            run_id=RUN,
            deadline_iso="2030-01-01T00:00:00+00:00",
            timer_unit=_timer_base() + ".timer",
            pair_ids=(1, 2),
        )
    )
    monkeypatch.setattr(
        controller, "_resolve_target", lambda *a, **k: _verified_target(str(tmp_path))
    )
    monkeypatch.setattr(
        controller, "_collect_db_identity", lambda *a, **k: ("d" * 64, "172.18.0.2", 5432)
    )

    def failing(target, action, **kwargs):
        raise controller.Failure("database unreachable")

    monkeypatch.setattr(controller, "_run_django", failing)
    assert controller.main(["callback", "--target", "dev", "--run-id", RUN]) == 1
    assert controller._read_state("dev").state == "CLOSING"
    capsys.readouterr()


def test_t3_close_orders_durable_checkpoint_before_cleanup(controller, monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    controller._write_state(
        controller.ActiveRecord(
            state="ACTIVE",
            target="dev",
            run_id=RUN,
            deadline_iso="2030-01-01T00:00:00+00:00",
            timer_unit=_timer_base() + ".timer",
            pair_ids=(1, 2),
        )
    )
    monkeypatch.setattr(
        controller, "_resolve_target", lambda *a, **k: _verified_target(str(tmp_path))
    )
    monkeypatch.setattr(
        controller, "_collect_db_identity", lambda *a, **k: ("d" * 64, "172.18.0.2", 5432)
    )
    monkeypatch.setattr(
        controller,
        "_run_django",
        lambda *a, **k: {"revoked": True, "already_revoked": False, "snapshot_after": "e" * 64},
    )
    order: list[str] = []
    original_write = controller._write_state

    def recording(record):
        order.append(record.state)
        return original_write(record)

    monkeypatch.setattr(controller, "_write_state", recording)
    monkeypatch.setattr(controller, "_cancel_timer", lambda *a, **k: order.append("cancel"))
    assert controller.cmd_close("dev").status == "PASS"
    assert order.index("CLOSING") < order.index("cancel") < order.index("CLOSED")


def test_t3_write_state_propagates_fsync_failure(controller, monkeypatch, tmp_path):
    import os

    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(os, "fsync", Mock(side_effect=OSError("disk gone")))
    with pytest.raises(OSError):
        controller._write_state(
            controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None)
        )


def test_t3_write_state_syncs_parent_directory(controller, monkeypatch, tmp_path):
    import os

    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    opened: list[int] = []
    dir_fds: list[int] = []
    real_open = os.open
    real_close = os.close
    real_fsync = os.fsync

    def fake_open(path, flags):
        fd = real_open(path, flags)
        if str(path) == str(tmp_path / "dev"):
            dir_fds.append(fd)
        return fd

    def fake_fsync(fd):
        opened.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "open", fake_open)
    monkeypatch.setattr(os, "fsync", fake_fsync)
    monkeypatch.setattr(os, "close", real_close)
    controller._write_state(controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None))
    assert dir_fds, "parent directory was never opened for sync"
    assert any(fd in opened for fd in dir_fds), "parent directory was never synced"


def _f4_checkout(monkeypatch, controller, tmp_path):
    monkeypatch.setattr(controller, "DEV_CHECKOUT", tmp_path)
    (tmp_path / "compose.yml").write_text("sirhosp_db_data")
    (tmp_path / "compose.dev.yml").write_text("sirhosp-web")
    return str(tmp_path)


def _f4_harness(monkeypatch, controller, tmp_path, *, prepare_mode, close_mode, cancel_mode):
    """Drive REAL cmd_open with only subprocess.run faked.

    Synthetic DB: prepare mutates to an owned inactive vfyP generation even
    when its response is then lost/invalid, modelling a committed PREPARE
    whose acknowledgement never arrived.
    """
    import subprocess as _subprocess
    import sys as _sys

    checkout = _f4_checkout(monkeypatch, controller, tmp_path)
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    monkeypatch.setattr(controller, "_now", lambda: 1000.0)
    ctx: dict = {
        "checkout": checkout,
        "django_actions": [],
        "prepare_run_id": None,
        "committed_run_id": None,
        "close_run_id": None,
        "stop_calls": [],
        "state_at_stop": [],
        "armed_run_id": None,
    }
    files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
    ps_full = (
        f"sirhosp-db|db|sirhosp|running|{checkout}|{files}\n"
        f"sirhosp-web|web|sirhosp|running|{checkout}|{files}"
    )
    initial_pair = {
        "snapshot": "c" * 64,
        "user": {
            "username": "verify_user",
            "user_id": None,
            "token": "",
            "exists": False,
            "owned": True,
            "is_active": False,
            "has_usable_password": False,
            "is_staff": False,
            "is_superuser": False,
            "must_change_password": None,
        },
        "admin": {
            "username": "verify_admin",
            "user_id": None,
            "token": "",
            "exists": False,
            "owned": True,
            "is_active": False,
            "has_usable_password": False,
            "is_staff": False,
            "is_superuser": False,
            "must_change_password": None,
        },
    }

    def _stanza(run_id):
        words = [
            _sys.executable,
            str(Path(checkout) / "scripts" / "verify_portal.py"),
            "callback",
            "--target",
            "dev",
            "--run-id",
            run_id,
        ]
        return (
            "{ path=" + words[0] + " ; argv[]=" + " ".join(words) + " ; "
            "ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; "
            "pid=0 ; code=(null) ; status=0/0 }"
        )

    def fake_run(argv, **kwargs):
        text = " ".join(argv)
        if argv[:1] == ["systemd-run"]:
            run_id = argv[argv.index("--run-id") + 1]
            ctx["armed_run_id"] = run_id
            return SimpleNamespace(returncode=0, stdout="Running as unit", stderr="")
        if any("database_identity" in part for part in argv):
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(["d" * 64, "172.18.0.2", 5432]), stderr=""
            )
        if "verification_session" in argv:
            action = argv[argv.index("verification_session") + 1]
            ctx["django_actions"].append(action)
            run_id = argv[argv.index("--run-id") + 1] if "--run-id" in argv else None
            if action == "preflight":
                payload = {
                    "fingerprint": "d" * 64,
                    "server_address": "172.18.0.2",
                    "server_port": 5432,
                    "pair": dict(initial_pair),
                    "debug": False,
                    "migrations_clean": True,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            if action == "owned-status":
                payload = {
                    "fingerprint": "d" * 64,
                    "server_address": "172.18.0.2",
                    "server_port": 5432,
                    "pair": dict(initial_pair),
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            if action == "prepare":
                ctx["prepare_run_id"] = run_id
                ctx["committed_run_id"] = run_id
                if prepare_mode == "ok":
                    return SimpleNamespace(
                        returncode=0,
                        stdout=json.dumps({"snapshot_after": "e" * 64}),
                        stderr="",
                    )
                if prepare_mode == "lost":
                    return SimpleNamespace(returncode=1, stdout="", stderr="boom")
                if prepare_mode == "invalid":
                    return SimpleNamespace(returncode=0, stdout="not-json", stderr="")
                if prepare_mode == "timeout":
                    raise _subprocess.TimeoutExpired(argv, 1)
                if prepare_mode == "malformed_missing":
                    return SimpleNamespace(
                        returncode=0, stdout=json.dumps({"unexpected": 1}), stderr=""
                    )
                if prepare_mode == "malformed_bad_snapshot":
                    return SimpleNamespace(
                        returncode=0,
                        stdout=json.dumps({"snapshot_after": "bad"}),
                        stderr="",
                    )
                raise AssertionError(f"unknown prepare_mode {prepare_mode}")
            if action == "close":
                ctx["close_run_id"] = run_id
                if close_mode == "ok":
                    payload = {
                        "revoked": True,
                        "already_revoked": False,
                        "snapshot_after": "e" * 64,
                    }
                    return SimpleNamespace(
                        returncode=0, stdout=json.dumps(payload), stderr=""
                    )
                if close_mode == "error":
                    return SimpleNamespace(returncode=1, stdout="", stderr="db down")
                if close_mode == "negative":
                    return SimpleNamespace(
                        returncode=0, stdout=json.dumps({"revoked": False}), stderr=""
                    )
                if close_mode == "malformed":
                    return SimpleNamespace(
                        returncode=0, stdout=json.dumps({"oops": 1}), stderr=""
                    )
                raise AssertionError(f"unknown close_mode {close_mode}")
            if action == "open":
                payload = {
                    "pair_ids": [1, 2],
                    "passwords": {"verify_user": "u" * 43, "verify_admin": "a" * 43},
                    "snapshot_after": "f" * 64,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")
        if argv[:1] == ["systemctl"] and "stop" in argv:
            ctx["stop_calls"].append(list(argv))
            try:
                raw = (tmp_path / "dev" / "session.json").read_text()
                ctx["state_at_stop"].append(json.loads(raw))
            except (OSError, ValueError):
                ctx["state_at_stop"].append(None)
            if cancel_mode == "ok":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="stop failed")
        if argv[:1] == ["systemctl"] and "show" in text:
            run_id = ctx.get("armed_run_id") or ctx.get("prepare_run_id") or RUN
            if "ActiveState" in text:
                return SimpleNamespace(returncode=0, stdout="active", stderr="")
            if "LoadState" in text:
                return SimpleNamespace(returncode=0, stdout="loaded", stderr="")
            if "Transient" in text:
                return SimpleNamespace(returncode=0, stdout="yes", stderr="")
            if "ExecStart" in text:
                return SimpleNamespace(returncode=0, stdout=_stanza(run_id), stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[:1] == ["busctl"]:
            if argv[-1] == "Unit":
                run_id = ctx.get("armed_run_id") or RUN
                return SimpleNamespace(
                    returncode=0,
                    stdout=f's "sirhosp-verify-{run_id}.service"',
                    stderr="",
                )
            if argv[-1] == "Type":
                return SimpleNamespace(returncode=0, stdout='s "oneshot"', stderr="")
            if argv[-1] == "TimeoutStartUSec":
                return SimpleNamespace(
                    returncode=0, stdout="t 18446744073709551615", stderr=""
                )
            return SimpleNamespace(returncode=0, stdout="t 4600000000", stderr="")
        if "database_identity" in text:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(["d" * 64, "172.18.0.2", 5432]), stderr=""
            )
        if "version" in argv:
            return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")
        if "volume" in argv:
            return SimpleNamespace(returncode=0, stdout="sirhosp_sirhosp_db_data", stderr="")
        if "Mounts" in text:
            return SimpleNamespace(
                returncode=0,
                stdout="sirhosp_sirhosp_db_data|/var/lib/postgresql/data",
                stderr="",
            )
        if "sirhosp_default" in text:
            return SimpleNamespace(returncode=0, stdout="172.18.0.2", stderr="")
        if "Ports" in text:
            return SimpleNamespace(returncode=0, stdout="5432/tcp", stderr="")
        if "ps" in argv:
            if "-a" in argv:
                return SimpleNamespace(returncode=0, stdout=ps_full, stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    return ctx


def test_f4_prepare_lost_response_revokes_same_run_before_cancel(controller, monkeypatch, tmp_path):
    ctx = _f4_harness(
        monkeypatch, controller, tmp_path, prepare_mode="lost", close_mode="ok", cancel_mode="ok"
    )
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert ctx["committed_run_id"] is not None, "prepare must model a committed generation"
    assert "close" in ctx["django_actions"], "uncertain PREPARE must attempt close"
    assert ctx["close_run_id"] == ctx["committed_run_id"], "close must target the SAME owned run"
    assert "open" not in ctx["django_actions"], "no activation after uncertain PREPARE"
    assert ctx["stop_calls"], "successful revoke must retire the timer"
    assert ctx["state_at_stop"], "cancellation must be observed against durable state"
    durable = ctx["state_at_stop"][0]
    assert durable is not None and durable.get("state") == "CLOSING", (
        f"durable state at cancellation must be CLOSING, got {durable}"
    )
    assert "revocation confirmed" in str(durable.get("diagnostic", "")).lower(), (
        f"CLOSING checkpoint must record revocation-confirmed cleanup-pending, got {durable}"
    )


def test_f4_prepare_timeout_close_error_never_cancels_nor_closes(controller, monkeypatch, tmp_path):
    ctx = _f4_harness(
        monkeypatch,
        controller,
        tmp_path,
        prepare_mode="timeout",
        close_mode="error",
        cancel_mode="ok",
    )
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert "close" in ctx["django_actions"]
    assert ctx["close_run_id"] == ctx["committed_run_id"]
    assert "open" not in ctx["django_actions"]
    assert ctx["stop_calls"] == [], "timer must stay alive when revocation is unknown"
    record = controller._read_state("dev")
    assert record.state == "CLOSING", f"revocation failure must stay CLOSING, got {record.state}"


def test_f4_prepare_invalid_close_negative_stays_recoverable(controller, monkeypatch, tmp_path):
    ctx = _f4_harness(
        monkeypatch,
        controller,
        tmp_path,
        prepare_mode="invalid",
        close_mode="negative",
        cancel_mode="ok",
    )
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert "close" in ctx["django_actions"]
    assert ctx["stop_calls"] == [], "negative revocation must not retire the timer"
    record = controller._read_state("dev")
    assert record.state == "CLOSING"
    assert "open" not in ctx["django_actions"]


def test_f4_cancel_failure_after_revoke_stays_closing(controller, monkeypatch, tmp_path):
    ctx = _f4_harness(
        monkeypatch,
        controller,
        tmp_path,
        prepare_mode="lost",
        close_mode="ok",
        cancel_mode="fail",
    )
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert "close" in ctx["django_actions"]
    assert ctx["stop_calls"], "cancel must have been attempted after revoke"
    record = controller._read_state("dev")
    assert record.state == "CLOSING", (
        f"cancel failure after affirmative revoke must stay CLOSING, got {record.state}"
    )
    assert "open" not in ctx["django_actions"], "original open must still fail without emission"


def test_f4_malformed_prepare_result_takes_guarded_path(controller, monkeypatch, tmp_path):
    ctx = _f4_harness(
        monkeypatch,
        controller,
        tmp_path,
        prepare_mode="malformed_missing",
        close_mode="ok",
        cancel_mode="ok",
    )
    with pytest.raises((controller.Blocked, controller.Failure)):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert "close" in ctx["django_actions"], (
        "malformed prepare result must enter the guarded uncertainty path"
    )
    assert ctx["close_run_id"] == ctx["committed_run_id"]
    assert "open" not in ctx["django_actions"]
    assert ctx["state_at_stop"], "guarded path must checkpoint CLOSING before cancel"
    assert ctx["state_at_stop"][0].get("state") == "CLOSING"


def _f5_absent(slot):
    username = "verify_user" if slot == "user" else "verify_admin"
    return {
        "username": username,
        "user_id": None,
        "token": "",
        "exists": False,
        "owned": True,
        "is_active": False,
        "has_usable_password": False,
        "is_staff": False,
        "is_superuser": False,
        "must_change_password": None,
    }


def _f5_revoked(slot, user_id, run=RUN):
    username = "verify_user" if slot == "user" else "verify_admin"
    return {
        "username": username,
        "user_id": user_id,
        "token": "vfyR:" + run + ":" + "e" * 32,
        "exists": True,
        "owned": True,
        "is_active": False,
        "has_usable_password": False,
        "is_staff": slot == "admin",
        "is_superuser": slot == "admin",
        "must_change_password": False,
    }


def _f5_human(slot, user_id=101):
    username = "verify_user" if slot == "user" else "verify_admin"
    return {
        "username": username,
        "user_id": user_id,
        "token": "",
        "exists": True,
        "owned": False,
        "is_active": False,
        "has_usable_password": False,
        "is_staff": False,
        "is_superuser": False,
        "must_change_password": None,
    }


def _f5_harness(monkeypatch, controller, tmp_path, *, pair, recover_mode="ok"):
    checkout = _checkout_tmp(monkeypatch, controller, tmp_path)
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    ctx = {"django_actions": [], "recover_run": None}
    files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
    ps_full = (
        f"sirhosp-db|db|sirhosp|running|{checkout}|{files}\n"
        f"sirhosp-web|web|sirhosp|running|{checkout}|{files}"
    )

    def fake_run(argv, **kwargs):
        text = " ".join(argv)
        if any("database_identity" in part for part in argv):
            payload = json.dumps(["d" * 64, "172.18.0.2", 5432])
            return SimpleNamespace(returncode=0, stdout=payload, stderr="")
        if "verification_session" in argv:
            action = argv[argv.index("verification_session") + 1]
            ctx["django_actions"].append(action)
            if action == "owned-status":
                payload = {
                    "fingerprint": "d" * 64,
                    "server_address": "172.18.0.2",
                    "server_port": 5432,
                    "pair": pair,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            if action == "recover":
                if "--run-id" in argv:
                    ctx["recover_run"] = argv[argv.index("--run-id") + 1]
                if recover_mode == "ok":
                    payload = {
                        "revoked": True,
                        "already_revoked": False,
                        "snapshot_after": "e" * 64,
                    }
                    return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
                if recover_mode == "negative":
                    payload = {"revoked": False, "snapshot_after": "e" * 64}
                    return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
                if recover_mode == "malformed":
                    return SimpleNamespace(returncode=0, stdout=json.dumps({"oops": 1}), stderr="")
                if recover_mode == "error":
                    return SimpleNamespace(returncode=1, stdout="", stderr="boom")
                raise AssertionError("unknown recover_mode")
            return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")
        if "version" in argv:
            return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")
        if "volume" in argv:
            return SimpleNamespace(returncode=0, stdout="sirhosp_sirhosp_db_data", stderr="")
        if "Mounts" in text:
            out = "sirhosp_sirhosp_db_data|/var/lib/postgresql/data"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if "sirhosp_default" in text:
            return SimpleNamespace(returncode=0, stdout="172.18.0.2", stderr="")
        if "Ports" in text:
            return SimpleNamespace(returncode=0, stdout="5432/tcp", stderr="")
        if "ps" in argv:
            return SimpleNamespace(returncode=0, stdout=ps_full, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    return ctx


def _f5_prepare_local(controller, local):
    if local == "closed":
        controller._write_state(
            controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None)
        )


@pytest.mark.parametrize("local", ["missing", "closed"])
def test_f5_human_inactive_unusable_never_proves_revocation(
    controller, monkeypatch, tmp_path, local
):
    pair = {"snapshot": "c" * 64, "user": _f5_human("user"), "admin": _f5_absent("admin")}
    _f5_harness(monkeypatch, controller, tmp_path, pair=pair)
    _f5_prepare_local(controller, local)
    try:
        verdict = controller.cmd_close("dev")
    except (controller.Blocked, controller.Failure):
        return
    assert not (verdict.status == "PASS" and verdict.revoked), "human row must not prove revocation"


@pytest.mark.parametrize("local", ["missing", "closed"])
def test_f5_human_recover_issues_no_mutation(controller, monkeypatch, tmp_path, local):
    pair = {"snapshot": "c" * 64, "user": _f5_human("user"), "admin": _f5_absent("admin")}
    ctx = _f5_harness(monkeypatch, controller, tmp_path, pair=pair, recover_mode="ok")
    _f5_prepare_local(controller, local)
    verdict = controller.cmd_close("dev", recover=True, run_id=RUN)
    assert not (verdict.status == "PASS" and verdict.revoked), "human must not pass via recover"
    assert "recover" not in ctx["django_actions"], "foreign ownership must block recover"
    assert "prepare" not in ctx["django_actions"]
    assert "open" not in ctx["django_actions"]
    if local == "missing":
        assert not (tmp_path / "dev" / "session.json").exists(), "no false CLOSED for human"


def _f5_pair_variants():
    base_user = _f5_absent("user")
    base_admin = _f5_absent("admin")
    variants = {}
    variants["missing-user"] = {"snapshot": "c" * 64, "admin": dict(base_admin)}
    variants["missing-admin"] = {"snapshot": "c" * 64, "user": dict(base_user)}
    variants["missing-snapshot"] = {"user": dict(base_user), "admin": dict(base_admin)}
    variants["bad-snapshot"] = {
        "snapshot": "bad",
        "user": dict(base_user),
        "admin": dict(base_admin),
    }
    variants["upper-snapshot"] = {
        "snapshot": "C" * 64,
        "user": dict(base_user),
        "admin": dict(base_admin),
    }
    variants["int-snapshot"] = {
        "snapshot": 123,
        "user": dict(base_user),
        "admin": dict(base_admin),
    }
    variants["none-entry"] = {"snapshot": "c" * 64, "user": None, "admin": dict(base_admin)}
    no_owned = dict(base_user)
    del no_owned["owned"]
    variants["missing-owned"] = {
        "snapshot": "c" * 64,
        "user": no_owned,
        "admin": dict(base_admin),
    }
    no_name = dict(base_user)
    del no_name["username"]
    variants["missing-username"] = {
        "snapshot": "c" * 64,
        "user": no_name,
        "admin": dict(base_admin),
    }
    return variants


@pytest.mark.parametrize("name", list(_f5_pair_variants().keys()))
@pytest.mark.parametrize("local", ["missing", "closed"])
def test_f5_incomplete_pair_never_proves_revocation(controller, monkeypatch, tmp_path, name, local):
    pair = _f5_pair_variants()[name]
    _f5_harness(monkeypatch, controller, tmp_path, pair=pair)
    _f5_prepare_local(controller, local)
    try:
        verdict = controller.cmd_close("dev")
    except (controller.Blocked, controller.Failure):
        return
    assert not (verdict.status == "PASS" and verdict.revoked), f"incomplete {name} must not pass"


def _f5_confused_pairs():
    cases = {}
    user = _f5_absent("user")
    admin = _f5_absent("admin")
    bad = dict(user, owned="true")
    cases["owned-str"] = {"snapshot": "c" * 64, "user": bad, "admin": dict(admin)}
    bad = dict(user, owned=1)
    cases["owned-int"] = {"snapshot": "c" * 64, "user": bad, "admin": dict(admin)}
    bad = dict(user, owned=None)
    cases["owned-none"] = {"snapshot": "c" * 64, "user": bad, "admin": dict(admin)}
    bad = dict(user, is_active=0)
    cases["active-int"] = {"snapshot": "c" * 64, "user": bad, "admin": dict(admin)}
    bad = dict(user, token=None)
    cases["token-none"] = {"snapshot": "c" * 64, "user": bad, "admin": dict(admin)}
    bad = dict(user, exists=1)
    cases["exists-int"] = {"snapshot": "c" * 64, "user": bad, "admin": dict(admin)}
    present = _f5_revoked("user", 11)
    bad = dict(present, user_id="11")
    cases["userid-str"] = {"snapshot": "c" * 64, "user": bad, "admin": _f5_revoked("admin", 12)}
    bad = dict(present, user_id=True)
    cases["userid-bool"] = {"snapshot": "c" * 64, "user": bad, "admin": _f5_revoked("admin", 12)}
    bad = dict(present, must_change_password="false")
    cases["profile-str"] = {"snapshot": "c" * 64, "user": bad, "admin": _f5_revoked("admin", 12)}
    bad = dict(present, is_staff=1)
    cases["staff-int"] = {"snapshot": "c" * 64, "user": bad, "admin": _f5_revoked("admin", 12)}
    return cases


@pytest.mark.parametrize("name", list(_f5_confused_pairs().keys()))
@pytest.mark.parametrize("local", ["missing", "closed"])
def test_f5_bool_confusion_never_proves_revocation(controller, monkeypatch, tmp_path, name, local):
    pair = _f5_confused_pairs()[name]
    _f5_harness(monkeypatch, controller, tmp_path, pair=pair)
    _f5_prepare_local(controller, local)
    try:
        verdict = controller.cmd_close("dev")
    except (controller.Blocked, controller.Failure):
        return
    assert not (verdict.status == "PASS" and verdict.revoked), f"confused {name} must not pass"


def _f5_inconsistent_pairs():
    cases = {}
    absent = _f5_absent("user")
    bad = dict(absent, user_id=7)
    cases["absent-id"] = {"snapshot": "c" * 64, "user": bad, "admin": _f5_absent("admin")}
    bad = dict(absent, token="vfyR:" + RUN + ":" + "e" * 32)
    cases["absent-token"] = {"snapshot": "c" * 64, "user": bad, "admin": _f5_absent("admin")}
    bad = dict(absent, owned=False)
    cases["absent-owned"] = {"snapshot": "c" * 64, "user": bad, "admin": _f5_absent("admin")}
    bad = dict(absent, must_change_password=True)
    cases["absent-profile"] = {"snapshot": "c" * 64, "user": bad, "admin": _f5_absent("admin")}
    swapped_user = dict(_f5_absent("user"), username="verify_admin")
    swapped_admin = dict(_f5_absent("admin"), username="verify_user")
    cases["swapped-name"] = {"snapshot": "c" * 64, "user": swapped_user, "admin": swapped_admin}
    first = _f5_revoked("user", 21)
    second = _f5_revoked("admin", 21)
    cases["aliased-id"] = {"snapshot": "c" * 64, "user": first, "admin": second}
    return cases


@pytest.mark.parametrize("name", list(_f5_inconsistent_pairs().keys()))
@pytest.mark.parametrize("local", ["missing", "closed"])
def test_f5_inconsistent_absence_swapped_alias_never_proves(
    controller, monkeypatch, tmp_path, name, local
):
    pair = _f5_inconsistent_pairs()[name]
    _f5_harness(monkeypatch, controller, tmp_path, pair=pair)
    _f5_prepare_local(controller, local)
    try:
        verdict = controller.cmd_close("dev")
    except (controller.Blocked, controller.Failure):
        return
    assert not (verdict.status == "PASS" and verdict.revoked), f"inconsistent {name} must not pass"


@pytest.mark.parametrize("local", ["missing", "closed"])
@pytest.mark.parametrize(
    "kind", ["both-absent", "both-revoked", "one-absent"],
)
def test_f5_valid_pairs_stay_idempotent(controller, monkeypatch, tmp_path, local, kind):
    if kind == "both-absent":
        pair = {"snapshot": "c" * 64, "user": _f5_absent("user"), "admin": _f5_absent("admin")}
    elif kind == "both-revoked":
        pair = {
            "snapshot": "c" * 64,
            "user": _f5_revoked("user", 31),
            "admin": _f5_revoked("admin", 32),
        }
    else:
        pair = {"snapshot": "c" * 64, "user": _f5_absent("user"), "admin": _f5_revoked("admin", 33)}
    _f5_harness(monkeypatch, controller, tmp_path, pair=pair)
    _f5_prepare_local(controller, local)
    verdict = controller.cmd_close("dev")
    assert verdict.status == "PASS" and verdict.revoked, f"valid {kind} must stay PASS"


@pytest.mark.parametrize("token", ["vfyA:" + RUN + ":" + "f" * 32, "vfyP:" + RUN + ":" + "f" * 32])
def test_f5_owned_orphan_blocks_without_recover(controller, monkeypatch, tmp_path, token):
    active = {
        "username": "verify_user",
        "user_id": 41,
        "token": token,
        "exists": True,
        "owned": True,
        "is_active": True,
        "has_usable_password": True,
        "is_staff": False,
        "is_superuser": False,
        "must_change_password": False,
    }
    pair = {"snapshot": "c" * 64, "user": active, "admin": _f5_absent("admin")}
    ctx = _f5_harness(monkeypatch, controller, tmp_path, pair=pair)
    with pytest.raises(controller.Blocked):
        controller.cmd_close("dev")
    assert "recover" not in ctx["django_actions"]


@pytest.mark.parametrize("recover_mode", ["negative", "malformed", "error"])
@pytest.mark.parametrize("local", ["missing", "closed"])
def test_f5_negative_recover_never_announces_revoked(
    controller, monkeypatch, tmp_path, recover_mode, local
):
    pair = {"snapshot": "c" * 64, "user": _f5_absent("user"), "admin": _f5_absent("admin")}
    _f5_harness(monkeypatch, controller, tmp_path, pair=pair, recover_mode=recover_mode)
    _f5_prepare_local(controller, local)
    verdict = controller.cmd_close("dev", recover=True, run_id=RUN)
    assert not (verdict.status == "PASS" and verdict.revoked), "negative recover must not pass"
    assert verdict.status == "FAIL" and not verdict.revoked
    if local == "missing":
        assert not (tmp_path / "dev" / "session.json").exists(), "no false CLOSED on negative"


@pytest.mark.parametrize("local", ["missing", "closed"])
def test_f5_incomplete_recover_issues_no_recover(controller, monkeypatch, tmp_path, local):
    pair = {"snapshot": "c" * 64, "user": _f5_absent("user")}
    ctx = _f5_harness(monkeypatch, controller, tmp_path, pair=pair, recover_mode="ok")
    _f5_prepare_local(controller, local)
    verdict = controller.cmd_close("dev", recover=True, run_id=RUN)
    assert verdict.status == "FAIL" and not verdict.revoked
    assert "recover" not in ctx["django_actions"], "incomplete must block recover"
    if local == "missing":
        assert not (tmp_path / "dev" / "session.json").exists(), "no false CLOSED on incomplete"



def _f7_fail_session_rename(monkeypatch, *, fail_on="all", fail_from=1, message=None):
    """Fail os.rename for session.tmp publishes; count attempts, delegate rest."""
    import os as _os

    real_rename = _os.rename
    state = {"count": 0}
    fault = message if message is not None else "injected storage fault"

    def fake_rename(src, dst, *args, **kwargs):
        if str(src).endswith("session.tmp"):
            state["count"] += 1
            if state["count"] >= fail_from and (fail_on == "all" or state["count"] == fail_on):
                raise OSError(fault)
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(_os, "rename", fake_rename)
    return state


def _f7_track_dirs(monkeypatch):
    """Record dir-fd opens, closes and syncs; delegate everything to the real os."""
    import os as _os

    real_open = _os.open
    real_close = _os.close
    real_fsync = _os.fsync
    open_dirs: dict[int, str] = {}
    synced: list[str] = []

    def fake_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        open_dirs[fd] = str(path)
        return fd

    def fake_close(fd):
        open_dirs.pop(fd, None)
        return real_close(fd)

    def fake_fsync(fd):
        if fd in open_dirs:
            synced.append(open_dirs[fd])
        return real_fsync(fd)

    monkeypatch.setattr(_os, "open", fake_open)
    monkeypatch.setattr(_os, "close", fake_close)
    monkeypatch.setattr(_os, "fsync", fake_fsync)
    return SimpleNamespace(open_dirs=open_dirs, synced=synced)


def test_f7_nested_state_dirs_synced_before_mutation(controller, monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path / "n1" / "n2")
    tracked = _f7_track_dirs(monkeypatch)
    controller._write_state(
        controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None)
    )
    assert controller._read_state("dev").state == "CLOSED"
    root = str(tmp_path / "n1" / "n2")
    leaf = str(tmp_path / "n1" / "n2" / "dev")
    assert root in tracked.synced, f"fresh STATE_ROOT entry never synced: {tracked.synced}"
    assert leaf in tracked.synced, f"fresh slug directory never synced: {tracked.synced}"


def test_f7_lock_created_dirs_synced_before_write(controller, monkeypatch, tmp_path):
    """Behavioral contract (adjusted): lock acquisition performs no durability
    sync and must never block on one; directories the lock created are
    affirmed by the actual _write_state ancestry sync before publication."""
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path / "nest" / "root")
    tracked = _f7_track_dirs(monkeypatch)
    with controller._lock("dev", wait_seconds=5):
        pass
    assert (tmp_path / "nest" / "root" / "dev" / ".lock").exists()
    assert tracked.synced == [], (
        f"lock acquisition must not claim durability via sync: {tracked.synced}"
    )
    controller._write_state(
        controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None)
    )
    assert controller._read_state("dev").state == "CLOSED"
    root = str(tmp_path / "nest" / "root")
    leaf = str(tmp_path / "nest" / "root" / "dev")
    assert root in tracked.synced, f"lock-created STATE_ROOT never affirmed: {tracked.synced}"
    assert leaf in tracked.synced, f"lock-created slug dir never affirmed: {tracked.synced}"


def test_f7_file_sync_failure_never_publishes(controller, monkeypatch, tmp_path):
    """Characterization (already safe): file fsync fails before rename publishes."""
    import os as _os

    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    tracked = _f7_track_dirs(monkeypatch)
    real_fsync = _os.fsync
    renamed: list[str] = []

    def fake_fsync(fd):
        if fd not in tracked.open_dirs:
            raise OSError("injected file sync fault")
        return real_fsync(fd)

    def fake_rename(src, dst, *args, **kwargs):
        renamed.append(str(src))
        return _os.rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(_os, "fsync", fake_fsync)
    monkeypatch.setattr(_os, "rename", fake_rename)
    with pytest.raises(OSError):
        controller._write_state(
            controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None)
        )
    assert renamed == [], "failed file sync must never publish the tmp record"
    assert not (tmp_path / "dev" / "session.json").exists()


def test_f7_directory_sync_failure_after_rename_is_not_durable(
    controller, monkeypatch, tmp_path
):
    """Characterization (already propagated): lost post-rename ack stays a failure."""
    import os as _os

    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    tracked = _f7_track_dirs(monkeypatch)
    real_fsync = _os.fsync
    renamed = _f7_fail_session_rename(monkeypatch, fail_on="never")

    def fake_fsync(fd):
        if fd in tracked.open_dirs and renamed["count"] > 0:
            raise OSError("injected directory sync fault")
        return real_fsync(fd)

    monkeypatch.setattr(_os, "fsync", fake_fsync)
    with pytest.raises(OSError):
        controller._write_state(
            controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None)
        )
    assert renamed["count"] == 1, "rename must have happened before the lost ack"


def test_f7_rename_failure_propagates_without_publish(controller, monkeypatch, tmp_path):
    """Characterization (already propagated): rename failure never claims durability."""
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    renamed = _f7_fail_session_rename(monkeypatch, fail_on="all")
    with pytest.raises(OSError):
        controller._write_state(
            controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None)
        )
    assert renamed["count"] == 1
    assert not (tmp_path / "dev" / "session.json").exists()


def test_f7_initial_opening_failure_blocks_activation(
    controller, monkeypatch, tmp_path, capsys
):
    ctx = _f4_harness(
        monkeypatch, controller, tmp_path, prepare_mode="ok", close_mode="ok", cancel_mode="ok"
    )
    _f7_fail_session_rename(monkeypatch, fail_on=1)
    code = controller.main(["open", "--target", "dev", "--confirm-fictitious"])
    assert code == 1
    assert "prepare" not in ctx["django_actions"], "no PREPARE after OPENING persist failure"
    assert "open" not in ctx["django_actions"], "no ACTIVATE after OPENING persist failure"
    assert ctx["armed_run_id"] is None, "no timer before durable OPENING"
    captured = capsys.readouterr()
    assert captured.out == "", "no credentials or verdict may be emitted on storage failure"
    assert "FAIL" in captured.err
    assert "recovery" in captured.err.lower()
    assert "Traceback" not in captured.err
    assert not (tmp_path / "dev" / "session.json").exists()


def test_f7_post_prepare_write_failure_compensates_same_run(controller, monkeypatch, tmp_path):
    ctx = _f4_harness(
        monkeypatch, controller, tmp_path, prepare_mode="ok", close_mode="ok", cancel_mode="ok"
    )
    _f7_fail_session_rename(monkeypatch, fail_on=2)
    with pytest.raises(OSError):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert ctx["committed_run_id"] is not None
    assert "close" in ctx["django_actions"], "uncertain post-PREPARE write must revoke"
    assert ctx["close_run_id"] == ctx["committed_run_id"], "revoke must target the same run"
    assert "open" not in ctx["django_actions"], "no activation after failed checkpoint"
    assert ctx["stop_calls"], "confirmed revoke must retire the timer"
    durable = ctx["state_at_stop"][0]
    assert durable is not None and durable.get("state") == "CLOSING"


def test_f7_post_prepare_persistent_failure_retains_timer(controller, monkeypatch, tmp_path):
    ctx = _f4_harness(
        monkeypatch, controller, tmp_path, prepare_mode="ok", close_mode="ok", cancel_mode="ok"
    )
    _f7_fail_session_rename(monkeypatch, fail_on="all", fail_from=2)
    with pytest.raises((controller.Blocked, controller.Failure)) as excinfo:
        controller.cmd_open("dev", confirm_fictitious=True)
    assert "close" in ctx["django_actions"], "affirmative revoke must still be attempted"
    assert ctx["close_run_id"] == ctx["committed_run_id"]
    assert "open" not in ctx["django_actions"]
    assert ctx["stop_calls"] == [], "timer must stay alive when CLOSING cannot persist"
    assert "timer retained" in str(excinfo.value)
    record = controller._read_state("dev")
    assert record.state == "OPENING", "first durable OPENING stays recoverable"
    assert record.run_id == ctx["committed_run_id"]


def _f7_close_setup(controller, monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    controller._write_state(
        controller.ActiveRecord(
            state="ACTIVE",
            target="dev",
            run_id=RUN,
            deadline_iso="2030-01-01T00:00:00+00:00",
            timer_unit=_timer_base() + ".timer",
            pair_ids=(1, 2),
        )
    )
    monkeypatch.setattr(
        controller, "_resolve_target", lambda *a, **k: _verified_target(str(tmp_path))
    )
    monkeypatch.setattr(
        controller, "_collect_db_identity", lambda *a, **k: ("d" * 64, "172.18.0.2", 5432)
    )
    monkeypatch.setattr(
        controller,
        "_run_django",
        lambda *a, **k: {"revoked": True, "already_revoked": False, "snapshot_after": "e" * 64},
    )
    cancelled: list[bool] = []
    monkeypatch.setattr(controller, "_cancel_timer", lambda *a, **k: cancelled.append(True))
    return cancelled


def test_f7_closing_persist_failure_retains_timer(controller, monkeypatch, tmp_path, capsys):
    cancelled = _f7_close_setup(controller, monkeypatch, tmp_path)
    _f7_fail_session_rename(monkeypatch, fail_on="all")
    code = controller.main(["close", "--target", "dev"])
    assert code == 1
    assert cancelled == [], "timer must not retire when CLOSING cannot persist"
    captured = capsys.readouterr()
    assert "PASS" not in captured.out
    assert "FAIL" in captured.err
    assert "recovery" in captured.err.lower()
    assert "Traceback" not in captured.err
    assert controller._read_state("dev").state == "ACTIVE"


def test_f7_final_closed_failure_never_passes(controller, monkeypatch, tmp_path, capsys):
    cancelled = _f7_close_setup(controller, monkeypatch, tmp_path)
    _f7_fail_session_rename(monkeypatch, fail_on=2)
    code = controller.main(["close", "--target", "dev"])
    assert code == 1
    captured = capsys.readouterr()
    assert "PASS" not in captured.out, "undurable closure must never claim PASS"
    assert "FAIL" in captured.err
    assert "Traceback" not in captured.err
    assert cancelled, "cancel after durable CLOSING is the observed ordering"
    assert controller._read_state("dev").state == "CLOSING"


def test_f7_callback_storage_failure_is_controlled(controller, monkeypatch, tmp_path, capsys):
    cancelled = _f7_close_setup(controller, monkeypatch, tmp_path)
    _f7_fail_session_rename(monkeypatch, fail_on="all")
    code = controller.main(["callback", "--target", "dev", "--run-id", RUN])
    assert code == 1
    assert cancelled == [], "callback must not retire the timer when CLOSING cannot persist"
    captured = capsys.readouterr()
    assert "PASS" not in captured.out
    assert "FAIL" in captured.err
    assert "recovery" in captured.err.lower()
    assert "Traceback" not in captured.err


def test_f7_retry_after_sync_failure_resyncs_ancestry(controller, monkeypatch, tmp_path):
    import os as _os

    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path / "r1" / "r2")
    real_open = _os.open
    real_close = _os.close
    real_fsync = _os.fsync
    real_rename = _os.rename
    open_dirs: dict[int, str] = {}
    events: list[tuple[str, str]] = []
    calls = {"fsync": 0}

    def fake_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        open_dirs[fd] = str(path)
        return fd

    def fake_close(fd):
        open_dirs.pop(fd, None)
        return real_close(fd)

    def fake_fsync(fd):
        calls["fsync"] += 1
        if calls["fsync"] == 1:
            raise OSError("injected first sync fault")
        if fd in open_dirs:
            events.append(("sync", open_dirs[fd]))
        return real_fsync(fd)

    def fake_rename(src, dst, *args, **kwargs):
        if str(src).endswith("session.tmp"):
            events.append(("rename", str(src)))
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(_os, "open", fake_open)
    monkeypatch.setattr(_os, "close", fake_close)
    monkeypatch.setattr(_os, "fsync", fake_fsync)
    monkeypatch.setattr(_os, "rename", fake_rename)
    with pytest.raises(OSError):
        controller._write_state(
            controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None)
        )
    assert not (tmp_path / "r1" / "r2" / "dev" / "session.json").exists()
    events.clear()
    controller._write_state(
        controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None)
    )
    assert controller._read_state("dev").state == "CLOSED"
    root = str(tmp_path / "r1" / "r2")
    leaf = str(tmp_path / "r1" / "r2" / "dev")
    syncs = [path for kind, path in events if kind == "sync"]
    renames = [index for index, (kind, _) in enumerate(events) if kind == "rename"]
    assert renames, "retry must publish the record"
    assert root in syncs, f"retry skipped STATE_ROOT ancestry sync: {syncs}"
    assert leaf in syncs, f"retry skipped slug directory sync: {syncs}"
    first_publish = min(renames)
    for anchor in (root, leaf):
        affirmed = [index for index, event in enumerate(events) if event == ("sync", anchor)]
        assert affirmed and min(affirmed) < first_publish, (
            "ancestry must be affirmed before the publish"
        )


def _f7_direct_compensate(controller, monkeypatch, tmp_path, *, fail_on, original):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    controller._write_state(
        controller.OpeningRecord(
            state="OPENING",
            target="dev",
            run_id=RUN,
            deadline_iso="2030-01-01T00:00:00+00:00",
            timer_unit=_timer_base() + ".timer",
            expect_state="c" * 64,
        )
    )
    renamed = _f7_fail_session_rename(monkeypatch, fail_on=fail_on)
    monkeypatch.setattr(
        controller,
        "_run_django",
        lambda *a, **k: {"revoked": True, "already_revoked": False, "snapshot_after": "e" * 64},
    )
    cancelled: list[bool] = []
    monkeypatch.setattr(controller, "_cancel_timer", lambda *a, **k: cancelled.append(True))
    resolved = _verified_target(str(tmp_path))
    with pytest.raises(controller.Failure) as excinfo:
        controller._compensate_open_failure(
            resolved, "dev", RUN, _timer_base() + ".timer", original, fingerprint="d" * 64
        )
    return SimpleNamespace(excinfo=excinfo, cancelled=cancelled, renamed=renamed)


def test_f7_compensate_final_closed_failure_is_factual(controller, monkeypatch, tmp_path):
    sentinel = "SENTINEL-PAYLOAD-7XQ9"
    outcome = _f7_direct_compensate(
        controller, monkeypatch, tmp_path, fail_on=2, original=OSError(sentinel)
    )
    assert outcome.cancelled, "cancel succeeded before the final CLOSED checkpoint"
    assert outcome.renamed["count"] == 2
    message = str(outcome.excinfo.value)
    assert "timer retained" not in message, f"false protection evidence: {message}"
    assert "manual recovery" in message.lower()
    assert "CLOSED" in message
    assert sentinel not in message, "raw original payload must not leak into the diagnostic"
    assert "OSError" in message, "original failure category must be preserved"
    assert controller._read_state("dev").state == "CLOSING"


def test_f7_compensate_closing_failure_retains_timer(controller, monkeypatch, tmp_path):
    outcome = _f7_direct_compensate(
        controller, monkeypatch, tmp_path, fail_on=1, original=controller.Failure("prepare lost")
    )
    assert outcome.cancelled == [], "timer must stay alive when CLOSING cannot persist"
    message = str(outcome.excinfo.value)
    assert "timer retained" in message
    assert "manual close/recovery" in message
    record = controller._read_state("dev")
    assert record.state == "OPENING" and record.run_id == RUN


def test_f7_storage_diagnostic_never_leaks_payload(controller, monkeypatch, tmp_path, capsys):
    sentinel = "SENTINEL-PAYLOAD-4ZQ2"
    ctx = _f4_harness(
        monkeypatch, controller, tmp_path, prepare_mode="ok", close_mode="ok", cancel_mode="ok"
    )
    _f7_fail_session_rename(monkeypatch, fail_on="all", fail_from=2, message=sentinel)
    code = controller.main(["open", "--target", "dev", "--confirm-fictitious"])
    assert code == 1
    assert "open" not in ctx["django_actions"]
    captured = capsys.readouterr()
    assert "PASS" not in captured.out
    assert "FAIL" in captured.err
    assert sentinel not in captured.out, "sensitive payload leaked to stdout"
    assert sentinel not in captured.err, "sensitive payload leaked to stderr"
    assert "Traceback" not in captured.err


def _f7_fault_dirsync(monkeypatch):
    """Armed narrow fault: os.fsync on directory fds fails once armed.

    Only the fsync of directories opened O_RDONLY (the _sync_dir seam)
    fails; every other operation delegates to the real os.
    """
    import os as _os

    real_open = _os.open
    real_close = _os.close
    real_fsync = _os.fsync
    open_dirs: dict[int, str] = {}
    fault = {"armed": False}

    def fake_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        if flags == _os.O_RDONLY:
            open_dirs[fd] = str(path)
        return fd

    def fake_close(fd):
        open_dirs.pop(fd, None)
        return real_close(fd)

    def fake_fsync(fd):
        if fault["armed"] and fd in open_dirs:
            raise OSError("injected directory sync fault")
        return real_fsync(fd)

    monkeypatch.setattr(_os, "open", fake_open)
    monkeypatch.setattr(_os, "close", fake_close)
    monkeypatch.setattr(_os, "fsync", fake_fsync)
    return fault


def _f7_revocation_harness(monkeypatch, controller, tmp_path):
    """Drive REAL close/callback over durable ACTIVE state.

    Only the external subprocess boundary is faked (docker identity,
    django adapter, systemd stop). The durable ACTIVE record and a
    preexisting stable lock inode are established on the real temporary
    filesystem before any fault is armed.
    """
    checkout = _f4_checkout(monkeypatch, controller, tmp_path)
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    controller._write_state(
        controller.ActiveRecord(
            state="ACTIVE",
            target="dev",
            run_id=RUN,
            deadline_iso="2030-01-01T00:00:00+00:00",
            timer_unit=_timer_base() + ".timer",
            pair_ids=(1, 2),
        )
    )
    with controller._lock("dev", wait_seconds=5):
        pass
    lock_inode = (tmp_path / "dev" / ".lock").stat().st_ino
    ctx: dict = {
        "django_actions": [],
        "close_run_id": None,
        "stop_calls": [],
        "lock_inode": lock_inode,
    }
    files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
    ps_full = (
        f"sirhosp-db|db|sirhosp|running|{checkout}|{files}\n"
        f"sirhosp-web|web|sirhosp|running|{checkout}|{files}"
    )

    def fake_run(argv, **kwargs):
        text = " ".join(argv)
        if "database_identity" in text:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(["d" * 64, "172.18.0.2", 5432]), stderr=""
            )
        if "verification_session" in argv:
            action = argv[argv.index("verification_session") + 1]
            ctx["django_actions"].append(action)
            if action == "close":
                ctx["close_run_id"] = argv[argv.index("--run-id") + 1]
                payload = {
                    "revoked": True,
                    "already_revoked": False,
                    "snapshot_after": "e" * 64,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")
        if argv[:1] == ["systemctl"] and "stop" in argv:
            ctx["stop_calls"].append(list(argv))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "version" in argv:
            return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")
        if "volume" in argv:
            return SimpleNamespace(returncode=0, stdout="sirhosp_sirhosp_db_data", stderr="")
        if "Mounts" in text:
            return SimpleNamespace(
                returncode=0,
                stdout="sirhosp_sirhosp_db_data|/var/lib/postgresql/data",
                stderr="",
            )
        if "sirhosp_default" in text:
            return SimpleNamespace(returncode=0, stdout="172.18.0.2", stderr="")
        if "Ports" in text:
            return SimpleNamespace(returncode=0, stdout="5432/tcp", stderr="")
        if "ps" in argv:
            if "-a" in argv:
                return SimpleNamespace(returncode=0, stdout=ps_full, stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    return ctx


def test_f7_dirsync_fault_close_still_attempts_revocation(
    controller, monkeypatch, tmp_path, capsys
):
    """Contract A: a directory sync fault on the existing state namespace
    must not prevent the revocation attempt while the stable lock, a
    readable ACTIVE generation and the verified database remain available."""
    ctx = _f7_revocation_harness(monkeypatch, controller, tmp_path)
    fault = _f7_fault_dirsync(monkeypatch)
    fault["armed"] = True
    code = controller.main(["close", "--target", "dev"])
    assert code == 1, "undurable CLOSING checkpoint must stay a controlled FAIL"
    assert "close" in ctx["django_actions"], (
        "directory sync fault on the state namespace must not prevent the DB close attempt"
    )
    assert ctx["close_run_id"] == RUN, "revocation must target the same run first"
    assert ctx["stop_calls"] == [], "timer must not retire while CLOSING is unconfirmed"
    captured = capsys.readouterr()
    assert "PASS" not in captured.out
    assert "FAIL" in captured.err
    assert "recovery" in captured.err.lower()
    assert "Traceback" not in captured.err
    assert controller._read_state("dev").state == "ACTIVE", "durable ACTIVE must survive"
    assert (tmp_path / "dev" / ".lock").stat().st_ino == ctx["lock_inode"], (
        "lock acquisition must never recreate the stable lock inode"
    )


def test_f7_dirsync_fault_callback_still_attempts_revocation(
    controller, monkeypatch, tmp_path, capsys
):
    """Contract A for the callback: same stable lock, DB close of the same
    run first, and no timer retirement when the CLOSING record cannot be
    durably published."""
    ctx = _f7_revocation_harness(monkeypatch, controller, tmp_path)
    fault = _f7_fault_dirsync(monkeypatch)
    fault["armed"] = True
    code = controller.main(["callback", "--target", "dev", "--run-id", RUN])
    assert code == 1, "undurable CLOSING checkpoint must stay a controlled FAIL"
    assert "close" in ctx["django_actions"], (
        "directory sync fault on the state namespace must not prevent the DB close attempt"
    )
    assert ctx["close_run_id"] == RUN, "callback revocation must target the same run first"
    assert ctx["stop_calls"] == [], (
        "callback must not retire the timer while CLOSING is unconfirmed"
    )
    captured = capsys.readouterr()
    assert "PASS" not in captured.out
    assert "FAIL" in captured.err
    assert "recovery" in captured.err.lower()
    assert "Traceback" not in captured.err
    assert controller._read_state("dev").state == "ACTIVE", "durable ACTIVE must survive"
    assert (tmp_path / "dev" / ".lock").stat().st_ino == ctx["lock_inode"], (
        "lock acquisition must never recreate the stable lock inode"
    )


def _f7_fail_session_rename_payload(monkeypatch, markers):
    """Fail os.rename for session.tmp publishes whose payload carries a marker."""
    import os as _os

    real_rename = _os.rename
    state = {"count": 0}

    def fake_rename(src, dst, *args, **kwargs):
        if str(src).endswith("session.tmp"):
            try:
                payload = Path(src).read_text()
            except OSError:
                payload = ""
            if any(marker in payload for marker in markers):
                state["count"] += 1
                raise OSError("injected storage fault")
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(_os, "rename", fake_rename)
    return state


def test_f7_compensate_cancel_failure_reports_unknown_cleanup(
    controller, monkeypatch, tmp_path, capsys
):
    """Contract B: a stop that partially executed and then failed leaves the
    cleanup outcome unknown; the following undurable CLOSING checkpoint must
    demand manual recovery without affirming retention or completion."""
    ctx = _f4_harness(
        monkeypatch, controller, tmp_path, prepare_mode="ok", close_mode="ok", cancel_mode="fail"
    )
    markers = ['"expect_state":"' + "e" * 64, "open cleanup cancel failed"]
    faulted = _f7_fail_session_rename_payload(monkeypatch, markers)
    code = controller.main(["open", "--target", "dev", "--confirm-fictitious"])
    assert code == 1
    assert "open" not in ctx["django_actions"], "no activation after the failed checkpoint"
    assert "close" in ctx["django_actions"], "compensation must still revoke"
    assert ctx["close_run_id"] == ctx["committed_run_id"], "revoke must target the same run"
    assert ctx["stop_calls"], "timer cancel must have been attempted and failed"
    assert faulted["count"] == 2, (
        "exactly the post-prepare write and the post-cancel checkpoint may fault"
    )
    captured = capsys.readouterr()
    assert "PASS" not in captured.out
    assert "FAIL" in captured.err
    assert "timer retained" not in captured.err, (
        f"failed stop must not affirm timer retention: {captured.err}"
    )
    assert "cleanup completed" not in captured.err, (
        f"failed stop must not affirm completed cleanup: {captured.err}"
    )
    assert "unknown" in captured.err.lower(), "cleanup outcome must be reported as unknown"
    assert "recovery" in captured.err.lower()
    assert "Traceback" not in captured.err
    assert controller._read_state("dev").state == "CLOSING", "durable CLOSING must survive"


# --- F8: assisted CLI emission of the returned credentials ----------------------


def test_f8_cli_open_emits_returned_credentials_once(controller, monkeypatch, tmp_path, capsys):
    """F8/R3: the assisted CLI open must emit the returned credentials
    exactly once, only after every guard, activation, durable checkpoint and
    the final timer recheck have already succeeded inside cmd_open."""
    _f4_harness(
        monkeypatch, controller, tmp_path, prepare_mode="ok", close_mode="ok", cancel_mode="ok"
    )
    code = controller.main(["open", "--target", "dev", "--confirm-fictitious"])
    assert code == 0
    captured = capsys.readouterr()
    emitted = json.loads(captured.out)
    assert set(emitted) == {"run_id", "target", "passwords", "origin"}
    assert controller.RUN_RE.fullmatch(emitted["run_id"])
    assert emitted["target"] == "dev"
    assert emitted["origin"] == SYN_DEV_ORIGIN
    assert emitted["passwords"] == {"verify_user": "u" * 43, "verify_admin": "a" * 43}
    for password in emitted["passwords"].values():
        assert captured.out.count(password) == 1, "credentials must be printed exactly once"
        assert password not in captured.err
    persisted = (tmp_path / "dev" / "session.json").read_text()
    for password in emitted["passwords"].values():
        assert password not in persisted, "no durable password store may exist"
    assert controller._read_state("dev").state == "ACTIVE"


def test_f8_cli_failed_open_never_emits_credentials(controller, monkeypatch, tmp_path, capsys):
    """F8/R3: when the final timer recheck fails after activation, the
    credentials held in the lost response must never reach CLI output."""
    _f4_harness(
        monkeypatch, controller, tmp_path, prepare_mode="ok", close_mode="ok", cancel_mode="ok"
    )
    real_confirm = controller._confirm_timer
    attempts = {"count": 0}

    def flaky_confirm(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 3:
            raise controller.Blocked("timer disappeared before emission")
        return real_confirm(*args, **kwargs)

    monkeypatch.setattr(controller, "_confirm_timer", flaky_confirm)
    code = controller.main(["open", "--target", "dev", "--confirm-fictitious"])
    assert code == 2
    captured = capsys.readouterr()
    for password in ("u" * 43, "a" * 43):
        assert password not in captured.out
        assert password not in captured.err
    assert controller._read_state("dev").state == "CLOSED"


def test_f8_cli_other_commands_never_reemit_credentials(
    controller, monkeypatch, tmp_path, capsys
):
    """F8/R3: doctor, status, close and callback output never carries the
    emitted credential material, and the credentials are never retransmitted."""
    _f4_harness(
        monkeypatch, controller, tmp_path, prepare_mode="ok", close_mode="ok", cancel_mode="ok"
    )
    assert controller.main(["open", "--target", "dev", "--confirm-fictitious"]) == 0
    opened = json.loads(capsys.readouterr().out)
    commands = [
        ["doctor", "--target", "dev", "--confirm-fictitious"],
        ["status", "--target", "dev"],
        ["close", "--target", "dev"],
        ["callback", "--target", "dev", "--run-id", opened["run_id"]],
    ]
    for argv in commands:
        controller.main(argv)
        captured = capsys.readouterr()
        for password in opened["passwords"].values():
            assert password not in captured.out
            assert password not in captured.err


# --- F9: honoring explicit stop in the CLOSED/absent close branches -------------


def _f9_owned_entry(username, user_id, *, token):
    return {
        "username": username,
        "user_id": user_id,
        "token": token,
        "exists": True,
        "owned": True,
        "is_active": False,
        "has_usable_password": False,
        "is_staff": False,
        "is_superuser": False,
        "must_change_password": False,
    }


def _f9_revoked_pair():
    token = "vfyR:" + RUN + ":revision"
    return {
        "snapshot": "e" * 64,
        "user": _f9_owned_entry("verify_user", 1, token=token),
        "admin": _f9_owned_entry("verify_admin", 2, token=token),
    }


def _f9_closed_harness(
    monkeypatch,
    controller,
    tmp_path,
    *,
    record="closed",
    stop_mode="ok",
    recover_mode="ok",
    pair=None,
):
    """Drive REAL close over durable state with only the external subprocess
    boundary faked. ``record`` selects the persisted shape: a writer ACTIVE
    run, a writer CLOSED record, or no record at all. ``stop_mode`` fails the
    compose stop of dev services; ``recover_mode`` fails the recovery answer."""
    checkout = _f4_checkout(monkeypatch, controller, tmp_path)
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    if record == "active":
        controller._write_state(
            controller.ActiveRecord(
                state="ACTIVE",
                target="dev",
                run_id=RUN,
                deadline_iso="2030-01-01T00:00:00+00:00",
                timer_unit=_timer_base() + ".timer",
                pair_ids=(1, 2),
            )
        )
    elif record == "closed":
        controller._write_state(
            controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None)
        )
    owned_pair = _f9_revoked_pair() if pair is None else pair
    files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
    ps_full = (
        f"sirhosp-db|db|sirhosp|running|{checkout}|{files}\n"
        f"sirhosp-web|web|sirhosp|running|{checkout}|{files}"
    )
    ctx: dict = {
        "django_actions": [],
        "close_run_id": None,
        "recover_run_id": None,
        "service_stops": [],
        "timer_stops": [],
        "events": [],
    }

    def fake_run(argv, **kwargs):
        text = " ".join(argv)
        if "database_identity" in text:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(["d" * 64, "172.18.0.2", 5432]), stderr=""
            )
        if "verification_session" in argv:
            action = argv[argv.index("verification_session") + 1]
            ctx["django_actions"].append(action)
            ctx["events"].append(("django", action))
            if action in {"close", "recover"}:
                ctx[f"{action}_run_id"] = argv[argv.index("--run-id") + 1]
                payload = {"revoked": recover_mode == "ok", "snapshot_after": "e" * 64}
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            if action == "owned-status":
                payload = {
                    "fingerprint": "d" * 64,
                    "server_address": "172.18.0.2",
                    "server_port": 5432,
                    "pair": owned_pair,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            if action == "preflight":
                payload = {
                    "fingerprint": "d" * 64,
                    "server_address": "172.18.0.2",
                    "server_port": 5432,
                    "pair": owned_pair,
                    "debug": False,
                    "migrations_clean": True,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")
        if argv[:1] == ["docker"] and "compose" in argv and "stop" in argv:
            service = argv[-1]
            ctx["service_stops"].append(service)
            ctx["events"].append(("stop", service))
            if stop_mode == "fail":
                return SimpleNamespace(returncode=1, stdout="", stderr="compose stop failed")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[:1] == ["systemctl"] and "stop" in argv:
            ctx["timer_stops"].append(list(argv))
            ctx["events"].append(("timer-stop", list(argv)))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "version" in argv:
            return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")
        if "volume" in argv:
            return SimpleNamespace(returncode=0, stdout="sirhosp_sirhosp_db_data", stderr="")
        if "Mounts" in text:
            return SimpleNamespace(
                returncode=0, stdout="sirhosp_sirhosp_db_data|/var/lib/postgresql/data", stderr=""
            )
        if "sirhosp_default" in text:
            return SimpleNamespace(returncode=0, stdout="172.18.0.2", stderr="")
        if "Ports" in text:
            return SimpleNamespace(returncode=0, stdout="5432/tcp", stderr="")
        if "ps" in argv:
            if "-a" in argv:
                return SimpleNamespace(returncode=0, stdout=ps_full, stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    return ctx


def test_f9_closed_record_stop_is_honored_after_verified_revocation(
    controller, monkeypatch, tmp_path, capsys
):
    """F9/R7: close --stop on a CLOSED record must still stop dev web/db
    after target identity and owned-pair revocation are confirmed."""
    ctx = _f9_closed_harness(monkeypatch, controller, tmp_path, record="closed")
    code = controller.main(["close", "--target", "dev", "--stop"])
    assert code == 0
    assert "owned-status" in ctx["django_actions"]
    assert ctx["service_stops"] == ["web", "db"], "explicit stop must be honored after CLOSED"
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["status"] == "PASS" and verdict["revoked"] is True
    assert controller._read_state("dev").state == "CLOSED"


def test_f9_absent_record_stop_is_honored(controller, monkeypatch, tmp_path, capsys):
    """F9/R7: close --stop with no persisted record must honor the explicit
    stop once the owned pair is verified as revoked."""
    ctx = _f9_closed_harness(monkeypatch, controller, tmp_path, record="absent")
    code = controller.main(["close", "--target", "dev", "--stop"])
    assert code == 0
    assert ctx["service_stops"] == ["web", "db"]
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["status"] == "PASS" and verdict["revoked"] is True


def test_f9_closed_record_stop_failure_is_not_pass(controller, monkeypatch, tmp_path, capsys):
    """F9/R7: a failed stop after a verified CLOSED pair must return FAIL,
    keep the truthful CLOSED state and never claim the services were stopped."""
    ctx = _f9_closed_harness(monkeypatch, controller, tmp_path, record="closed", stop_mode="fail")
    code = controller.main(["close", "--target", "dev", "--stop"])
    assert code == 1
    assert ctx["service_stops"] == ["web", "db"] or ctx["service_stops"] == ["web"]
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["status"] == "FAIL"
    assert verdict["revoked"] is True, "revocation itself stayed confirmed"
    assert controller._read_state("dev").state == "CLOSED", "state stays truthful"


def test_f9_recovery_on_closed_record_stops_after_revocation(
    controller, monkeypatch, tmp_path, capsys
):
    """F9/R7: recovery close over a CLOSED record must honor --stop only
    after the affirmative recovery revocation."""
    ctx = _f9_closed_harness(monkeypatch, controller, tmp_path, record="closed")
    code = controller.main(["close", "--target", "dev", "--recover", "--stop", "--run-id", RUN])
    assert code == 0
    assert ctx["recover_run_id"] == RUN
    recover_at = ctx["events"].index(("django", "recover"))
    first_stop = ctx["events"].index(("stop", "web"))
    assert recover_at < first_stop, "revocation must precede stopping dev services"
    assert ctx["service_stops"] == ["web", "db"]
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["status"] == "PASS" and verdict["revoked"] is True
    assert controller._read_state("dev").state == "CLOSED"


def test_f9_recovery_stop_failure_stays_recoverable(controller, monkeypatch, tmp_path, capsys):
    """F9/R7: a failed stop during recovery keeps a recoverable CLOSING state
    with the truthful run id instead of announcing a false CLOSED."""
    ctx = _f9_closed_harness(monkeypatch, controller, tmp_path, record="closed", stop_mode="fail")
    code = controller.main(["close", "--target", "dev", "--recover", "--stop", "--run-id", RUN])
    assert code == 1
    assert ctx["recover_run_id"] == RUN, "the recovery revocation must target the named run"
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["status"] == "FAIL"
    assert verdict["revoked"] is True
    state = controller._read_state("dev")
    assert state.state == "CLOSING" and state.run_id == RUN
    assert controller.main(["close", "--target", "dev", "--recover", "--run-id", RUN]) == 0
    assert controller._read_state("dev").state == "CLOSED"


def test_f9_closed_orphan_denies_stop_without_recover(controller, monkeypatch, tmp_path, capsys):
    """F9 guard: an orphaned active pair in the CLOSED branch keeps denying
    stop and revocation without explicit recovery."""
    pair = _f9_revoked_pair()
    for name in ("user", "admin"):
        pair[name].update(
            is_active=True, has_usable_password=True, token="vfyA:" + RUN + ":revision"
        )
    ctx = _f9_closed_harness(monkeypatch, controller, tmp_path, record="closed", pair=pair)
    code = controller.main(["close", "--target", "dev", "--stop"])
    assert code == 2
    assert ctx["service_stops"] == []
    assert "close" not in ctx["django_actions"] and "recover" not in ctx["django_actions"]
    assert controller._read_state("dev").state == "CLOSED"
    capsys.readouterr()


def test_f9_recovery_revocation_failure_denies_stop(controller, monkeypatch, tmp_path, capsys):
    """F9 guard: a negative recovery answer must fail without stopping dev
    services and without writing a false CLOSED record."""
    ctx = _f9_closed_harness(
        monkeypatch, controller, tmp_path, record="closed", recover_mode="negative"
    )
    code = controller.main(["close", "--target", "dev", "--recover", "--stop", "--run-id", RUN])
    assert code == 1
    assert ctx["service_stops"] == [], "no stopping before verified revocation"
    assert controller._read_state("dev").state == "CLOSED"
    capsys.readouterr()


# --- F11: validation of persisted state records ---------------------------------


def _f11_opening_record():
    return {
        "state": "OPENING",
        "target": "dev",
        "run_id": RUN,
        "deadline_iso": "2030-01-01T00:00:00+00:00",
        "timer_unit": _timer_base() + ".timer",
        "expect_state": "c" * 64,
    }


def _f11_active_record():
    return {
        "state": "ACTIVE",
        "target": "dev",
        "run_id": RUN,
        "deadline_iso": "2030-01-01T00:00:00+00:00",
        "timer_unit": _timer_base() + ".timer",
        "pair_ids": [1, 2],
    }


_F11_INVALID_RECORDS = {
    "opening-null-run-id": {**_f11_opening_record(), "run_id": None},
    "opening-int-run-id": {**_f11_opening_record(), "run_id": 12345678901234567890123456789012},
    "opening-foreign-timer": {**_f11_opening_record(), "timer_unit": _timer_base(NEXT) + ".timer"},
    "opening-timer-without-suffix": {**_f11_opening_record(), "timer_unit": _timer_base()},
    "opening-naive-deadline": {**_f11_opening_record(), "deadline_iso": "2030-01-01T00:00:00"},
    "opening-bad-snapshot": {**_f11_opening_record(), "expect_state": "zz"},
    "opening-wrong-target": {**_f11_opening_record(), "target": "prod"},
    "opening-missing-target": {k: v for k, v in _f11_opening_record().items() if k != "target"},
    "opening-extra-field": {**_f11_opening_record(), "extra": True},
    "active-bool-pair-id": {**_f11_active_record(), "pair_ids": [1, True]},
    "active-string-pair-ids": {**_f11_active_record(), "pair_ids": ["1", "2"]},
    "active-float-pair-id": {**_f11_active_record(), "pair_ids": [1, 2.5]},
    "active-equal-pair-ids": {**_f11_active_record(), "pair_ids": [7, 7]},
    "active-nonpositive-pair-id": {**_f11_active_record(), "pair_ids": [0, 2]},
    "active-pair-ids-truncated": {**_f11_active_record(), "pair_ids": [1, 2, 3]},
    "closed-int-last-run": {"state": "CLOSED", "target": "dev", "last_run_id": 123},
    "closed-garbage-last-run": {"state": "CLOSED", "target": "dev", "last_run_id": "not-a-run"},
    "closed-extra-field": {"state": "CLOSED", "target": "dev", "last_run_id": None, "x": 1},
    "closing-int-diagnostic": {"state": "CLOSING", "target": "dev", "run_id": RUN, "diagnostic": 5},
}


@pytest.mark.parametrize("name", sorted(_F11_INVALID_RECORDS))
def test_f11_malformed_records_fail_closed(controller, monkeypatch, tmp_path, name):
    """F11/R5: malformed persisted fields must fail closed instead of being
    coerced into plausible strings or integers."""
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    directory = tmp_path / "dev"
    directory.mkdir()
    payload = json.dumps(_F11_INVALID_RECORDS[name])
    (directory / "session.json").write_text(payload)
    with pytest.raises(controller.Blocked):
        controller._read_state("dev")
    assert (directory / "session.json").read_text() == payload


def test_f11_writer_generated_records_stay_readable(controller, monkeypatch, tmp_path):
    """F11/R5: legitimate writer-generated records of every state keep
    loading unchanged through the stricter validation."""
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    records = [
        controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=None),
        controller.ClosedRecord(state="CLOSED", target="dev", last_run_id=RUN),
        controller.OpeningRecord(
            state="OPENING",
            target="dev",
            run_id=RUN,
            deadline_iso="2030-01-01T00:00:00+00:00",
            timer_unit=_timer_base() + ".timer",
            expect_state="c" * 64,
        ),
        controller.ActiveRecord(
            state="ACTIVE",
            target="dev",
            run_id=RUN,
            deadline_iso="2030-01-01T00:00:00+00:00",
            timer_unit=_timer_base() + ".timer",
            pair_ids=(1, 2),
        ),
        controller.ClosingRecord(
            state="CLOSING", target="dev", run_id=RUN, diagnostic="revocation confirmed"
        ),
    ]
    for record in records:
        controller._write_state(record)
        assert controller._read_state("dev") == record


def test_f11_cli_status_and_callback_fail_closed_on_coerced_record(
    controller, monkeypatch, tmp_path, capsys
):
    """F11/R5: a coerced run id must not surface as a valid status and must
    not look like a stale run for the deadline callback."""
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(
        controller, "_resolve_target", lambda *a, **k: _verified_target(str(tmp_path))
    )
    directory = tmp_path / "dev"
    directory.mkdir()
    payload = json.dumps(_F11_INVALID_RECORDS["opening-null-run-id"])
    (directory / "session.json").write_text(payload)
    code = controller.main(["status", "--target", "dev"])
    assert code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "BLOCKED" in captured.err
    assert "recovery" in captured.err.lower()
    code = controller.main(["callback", "--target", "dev", "--run-id", RUN])
    assert code == 1, "a coerced run id must not be mistaken for a stale run"
    captured = capsys.readouterr()
    assert "FAIL" in captured.out
    assert "recovery" in captured.out.lower()
    assert (directory / "session.json").read_text() == payload, "unreadable state stays untouched"


def test_f11_cli_status_reports_valid_records(controller, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(
        controller, "_resolve_target", lambda *a, **k: _verified_target(str(tmp_path))
    )
    controller._write_state(
        controller.ActiveRecord(
            state="ACTIVE",
            target="dev",
            run_id=RUN,
            deadline_iso="2030-01-01T00:00:00+00:00",
            timer_unit=_timer_base() + ".timer",
            pair_ids=(1, 2),
        )
    )
    assert controller.main(["status", "--target", "dev"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {"state": "ACTIVE", "target": "dev", "run_id": RUN}


# --- P1 repair: recovery over a malformed ACTIVE record --------------------------


def _p1_active_entry(username, user_id, token, *, staff=False):
    return {
        "username": username,
        "user_id": user_id,
        "token": token,
        "exists": True,
        "owned": True,
        "is_active": True,
        "has_usable_password": True,
        "is_staff": staff,
        "is_superuser": staff,
        "must_change_password": False,
    }


def _p1_active_pair(*, user_token=None, admin_token=None):
    token = "vfyA:" + RUN + ":" + "e" * 32
    return {
        "snapshot": "e" * 64,
        "user": _p1_active_entry("verify_user", 1, user_token or token),
        "admin": _p1_active_entry("verify_admin", 2, admin_token or token, staff=True),
    }


def _p1_malformed_active_payload():
    """Persisted ACTIVE record with deliberately malformed string pair ids."""
    return json.dumps(
        {
            "state": "ACTIVE",
            "target": "dev",
            "run_id": RUN,
            "deadline_iso": "2030-01-01T00:00:00+00:00",
            "timer_unit": _timer_base() + ".timer",
            "pair_ids": ["1", "2"],
        }
    )


def _p1_recovery_harness(monkeypatch, controller, tmp_path, *, pair=None, cancel_mode="ok"):
    """Drive REAL CLI recovery over a malformed ACTIVE record.

    Only the external subprocess boundary (Docker Compose, systemd) is
    faked. The owned timer armed by the previously active run is modelled
    as pending outside the process and changes state only through the fake
    owned cancellation success; a failed cancellation leaves its outcome
    modelled as still pending (unknown). Real lock, state and CLI helpers
    are used throughout.
    """
    checkout = _f4_checkout(monkeypatch, controller, tmp_path)
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    directory = tmp_path / "dev"
    directory.mkdir()
    raw = _p1_malformed_active_payload()
    (directory / "session.json").write_text(raw)
    owned_pair = _p1_active_pair() if pair is None else pair
    base = _timer_base()
    timers = {base + ".timer": "pending", base + ".service": "pending"}
    files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
    ps_full = (
        f"sirhosp-db|db|sirhosp|running|{checkout}|{files}\n"
        f"sirhosp-web|web|sirhosp|running|{checkout}|{files}"
    )
    ctx: dict = {
        "django_actions": [],
        "events": [],
        "recover_run_id": None,
        "timer_stops": [],
        "service_stops": [],
        "state_at_cancel": [],
        "timers": timers,
        "cancel_mode": cancel_mode,
        "raw_record": raw,
    }

    def fake_run(argv, **kwargs):
        text = " ".join(argv)
        if "database_identity" in text:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(["d" * 64, "172.18.0.2", 5432]), stderr=""
            )
        if "verification_session" in argv:
            action = argv[argv.index("verification_session") + 1]
            ctx["django_actions"].append(action)
            ctx["events"].append(("django", action))
            if action == "recover":
                ctx["recover_run_id"] = argv[argv.index("--run-id") + 1]
                stamp = "vfyR:" + ctx["recover_run_id"] + ":" + "e" * 32
                for entry in (owned_pair["user"], owned_pair["admin"]):
                    if entry["exists"]:
                        entry.update(is_active=False, has_usable_password=False, token=stamp)
                owned_pair["snapshot"] = "f" * 64
                payload = {
                    "revoked": True,
                    "already_revoked": False,
                    "snapshot_after": "f" * 64,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            if action == "owned-status":
                payload = {
                    "fingerprint": "d" * 64,
                    "server_address": "172.18.0.2",
                    "server_port": 5432,
                    "pair": owned_pair,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")
        if argv[:1] == ["docker"] and "compose" in argv and "stop" in argv:
            service = argv[-1]
            ctx["service_stops"].append(service)
            ctx["events"].append(("stop", service))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[:1] == ["systemctl"] and "stop" in argv:
            units = list(argv[argv.index("stop") + 1 :])
            ctx["timer_stops"].append(units)
            ctx["events"].append(("timer-stop", units))
            try:
                ctx["state_at_cancel"].append(
                    json.loads((directory / "session.json").read_text())
                )
            except (OSError, ValueError):
                ctx["state_at_cancel"].append(None)
            if ctx["cancel_mode"] == "fail":
                return SimpleNamespace(returncode=1, stdout="", stderr="systemd stop failed")
            for unit in units:
                timers.pop(unit, None)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "version" in argv:
            return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")
        if "volume" in argv:
            return SimpleNamespace(returncode=0, stdout="sirhosp_sirhosp_db_data", stderr="")
        if "Mounts" in text:
            return SimpleNamespace(
                returncode=0, stdout="sirhosp_sirhosp_db_data|/var/lib/postgresql/data", stderr=""
            )
        if "sirhosp_default" in text:
            return SimpleNamespace(returncode=0, stdout="172.18.0.2", stderr="")
        if "Ports" in text:
            return SimpleNamespace(returncode=0, stdout="5432/tcp", stderr="")
        if "ps" in argv:
            if "-a" in argv:
                return SimpleNamespace(returncode=0, stdout=ps_full, stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    return ctx


@pytest.mark.parametrize("named_run", [False, True])
def test_p1_malformed_active_recovery_retires_owned_generation(
    controller, monkeypatch, tmp_path, capsys, named_run
):
    """P1/R5/R6/F10: recovery over a malformed ACTIVE record must revoke the
    stamped database generation, publish durable CLOSING before cancelling
    exactly that owned timer, and prove the timer retired before CLOSED."""
    ctx = _p1_recovery_harness(monkeypatch, controller, tmp_path)
    argv = ["close", "--target", "dev", "--recover"]
    if named_run:
        argv += ["--run-id", RUN]
    assert controller.main(argv) == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["status"] == "PASS" and verdict["revoked"] is True
    assert ctx["recover_run_id"] == RUN, "revocation must target the stamped generation"
    assert ctx["timer_stops"] == [
        [_timer_base() + ".timer", _timer_base() + ".service"]
    ], "cancel exactly the owned generation units"
    durable = ctx["state_at_cancel"][0]
    assert durable is not None, "durable CLOSING must precede the cancel attempt"
    assert durable["state"] == "CLOSING" and durable["run_id"] == RUN
    assert not ctx["timers"], "owned timer no longer pending before durable CLOSED/PASS"
    final = controller._read_state("dev")
    assert final.state == "CLOSED" and final.last_run_id == RUN
    assert ctx["events"].index(("django", "recover")) < next(
        i for i, event in enumerate(ctx["events"]) if event[0] == "timer-stop"
    )


def test_p1_malformed_active_recovery_cancel_failure_stays_recoverable(
    controller, monkeypatch, tmp_path, capsys
):
    """P1/R6: failed owned-timer cancellation after recovery revocation must
    not announce PASS/CLOSED; the cleanup outcome stays unknown and the
    CLOSING record keeps recovery possible for the exact generation."""
    ctx = _p1_recovery_harness(monkeypatch, controller, tmp_path, cancel_mode="fail")
    assert controller.main(["close", "--target", "dev", "--recover"]) == 1
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["status"] == "FAIL"
    assert verdict["revoked"] is True, "the database revocation itself stayed confirmed"
    state = controller._read_state("dev")
    assert state.state == "CLOSING" and state.run_id == RUN
    assert ctx["timers"], "cancellation outcome stays unknown, timer still modelled pending"
    ctx["cancel_mode"] = "ok"
    assert controller.main(["close", "--target", "dev", "--recover", "--run-id", RUN]) == 0
    assert controller._read_state("dev").state == "CLOSED"
    assert not ctx["timers"], "retry completes the exact owned cleanup"


def test_p1_malformed_active_recovery_without_trusted_generation_is_not_pass(
    controller, monkeypatch, tmp_path, capsys
):
    """P1/R5: mixed owned stamps prove no cleanup generation, so recovery
    must stay non-PASS without revoking, stopping a guessed or foreign
    timer, or overwriting the malformed record."""
    pair = _p1_active_pair(
        user_token="vfyA:" + RUN + ":" + "e" * 32,
        admin_token="vfyA:" + NEXT + ":" + "e" * 32,
    )
    ctx = _p1_recovery_harness(monkeypatch, controller, tmp_path, pair=pair)
    assert controller.main(["close", "--target", "dev", "--recover"]) == 1
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["status"] == "FAIL" and verdict["revoked"] is False
    assert "recover" not in ctx["django_actions"], "no revocation without a trusted generation"
    assert ctx["timer_stops"] == [] and ctx["service_stops"] == []
    assert (tmp_path / "dev" / "session.json").read_text() == ctx[
        "raw_record"
    ], "unknown cleanup must not be overwritten or obscured"
    assert ctx["timers"], "the pending owned timer stays untouched, identity unproved"


def test_p1_malformed_active_recovery_run_id_alone_is_not_trusted(
    controller, monkeypatch, tmp_path, capsys
):
    """P1/R5: a syntactically valid supplied run id that disagrees with the
    stamped owned generation must never drive revocation or cleanup."""
    ctx = _p1_recovery_harness(monkeypatch, controller, tmp_path)
    assert controller.main(["close", "--target", "dev", "--recover", "--run-id", NEXT]) == 1
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["status"] == "FAIL" and verdict["revoked"] is False
    assert ctx["recover_run_id"] is None, "the foreign run id never reaches revocation"
    assert ctx["timer_stops"] == [] and ctx["service_stops"] == []
    assert (tmp_path / "dev" / "session.json").read_text() == ctx["raw_record"]
    assert ctx["timers"], "the pending owned timer stays untouched, identity unproved"


# --- systemd cleanup repair: nonzero joint stop versus proven unit state ------


def _cancel_repair_harness(
    monkeypatch,
    controller,
    tmp_path,
    *,
    record="ACTIVE",
    stop_exit=5,
    present=(),
    show_mode="state",
):
    """Drive REAL close/callback over durable state with only subprocess.run
    faked, modeling the real systemctl semantics proven by the operational
    diagnosis: the joint stop of a transient pair whose service never fired
    (or of already-unloaded units) exits 5 even though cleanup happened,
    while `systemctl --user show <unit> -p <prop> --value` still reports
    LoadState/ActiveState with exit 0 for absent units."""
    import subprocess as _subprocess

    checkout = _f4_checkout(monkeypatch, controller, tmp_path)
    monkeypatch.setattr(controller, "STATE_ROOT", tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1003/docker.sock")
    if record == "ACTIVE":
        controller._write_state(
            controller.ActiveRecord(
                state="ACTIVE",
                target="dev",
                run_id=RUN,
                deadline_iso="2030-01-01T00:00:00+00:00",
                timer_unit=_timer_base() + ".timer",
                pair_ids=(1, 2),
            )
        )
    else:
        # Durable leftover of a first close whose joint stop already
        # unloaded both units: a repeat stop keeps exiting 5 forever.
        controller._write_state(
            controller.ClosingRecord(
                state="CLOSING",
                target="dev",
                run_id=RUN,
                diagnostic="revocation confirmed, cleanup pending",
            )
        )
    ctx: dict = {
        "checkout": checkout,
        "django_actions": [],
        "close_run_id": None,
        "stop_calls": [],
        "show_calls": [],
        "systemctl_calls": [],
    }
    files = f"{checkout}/compose.yml,{checkout}/compose.dev.yml"
    ps_full = (
        f"sirhosp-db|db|sirhosp|running|{checkout}|{files}\n"
        f"sirhosp-web|web|sirhosp|running|{checkout}|{files}"
    )

    def fake_run(argv, **kwargs):
        text = " ".join(argv)
        if argv[:2] == ["systemctl", "--user"]:
            ctx["systemctl_calls"].append(list(argv))
            if "stop" in argv:
                ctx["stop_calls"].append(list(argv))
                stderr = ""
                if stop_exit != 0:
                    stderr = f"Failed to stop {argv[-1]}: Unit {argv[-1]} not loaded."
                return SimpleNamespace(returncode=stop_exit, stdout="", stderr=stderr)
            if "show" in argv:
                ctx["show_calls"].append(list(argv))
                if show_mode == "timeout":
                    raise _subprocess.TimeoutExpired(argv, 1)
                if show_mode == "fail":
                    return SimpleNamespace(returncode=1, stdout="", stderr="dbus down")
                if show_mode == "empty":
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                unit = argv[argv.index("show") + 1]
                prop = argv[argv.index("-p") + 1]
                if show_mode == "mismatch":
                    values = {"LoadState": "masked", "ActiveState": "failed"}
                elif unit in present:
                    values = {"LoadState": "loaded", "ActiveState": "active"}
                else:
                    values = {"LoadState": "not-found", "ActiveState": "inactive"}
                return SimpleNamespace(returncode=0, stdout=values[prop] + "\n", stderr="")
            raise AssertionError(f"unexpected systemctl argv {argv}")
        if "database_identity" in text:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(["d" * 64, "172.18.0.2", 5432]), stderr=""
            )
        if "verification_session" in argv:
            action = argv[argv.index("verification_session") + 1]
            ctx["django_actions"].append(action)
            if action == "close":
                ctx["close_run_id"] = argv[argv.index("--run-id") + 1]
                payload = {
                    "revoked": True,
                    "already_revoked": False,
                    "snapshot_after": "e" * 64,
                }
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")
        if "version" in argv:
            return SimpleNamespace(returncode=0, stdout="28.0.0", stderr="")
        if "volume" in argv:
            return SimpleNamespace(returncode=0, stdout="sirhosp_sirhosp_db_data", stderr="")
        if "Mounts" in text:
            return SimpleNamespace(
                returncode=0, stdout="sirhosp_sirhosp_db_data|/var/lib/postgresql/data", stderr=""
            )
        if "sirhosp_default" in text:
            return SimpleNamespace(returncode=0, stdout="172.18.0.2", stderr="")
        if "Ports" in text:
            return SimpleNamespace(returncode=0, stdout="5432/tcp", stderr="")
        if "ps" in argv:
            if "-a" in argv:
                return SimpleNamespace(returncode=0, stdout=ps_full, stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    return ctx


def _cancel_repair_only_generation_units(ctx, allowed):
    for argv in ctx["systemctl_calls"]:
        referenced = [part for part in argv if part.startswith("sirhosp-verify-")]
        assert referenced, f"systemctl traffic must target owned units: {argv}"
        for part in referenced:
            assert part in allowed, f"foreign generation unit {part} in {argv}"


def test_cancel_repair_exit5_absent_pair_completes_close(controller, monkeypatch, tmp_path):
    """Repair (a): the joint stop exits 5 while BOTH requested units are
    proven not-found/inactive, so cleanup is complete and close must reach a
    durable CLOSED/PASS verdict instead of the old FAIL/CLOSING."""
    ctx = _cancel_repair_harness(monkeypatch, controller, tmp_path)
    verdict = controller.cmd_close("dev")
    assert verdict.status == "PASS"
    assert verdict.revoked is True
    assert controller._read_state("dev").state == "CLOSED"
    assert ctx["stop_calls"] == [
        [
            "systemctl",
            "--user",
            "stop",
            _timer_base() + ".timer",
            _timer_base() + ".service",
        ]
    ]
    _cancel_repair_only_generation_units(
        ctx, {_timer_base() + ".timer", _timer_base() + ".service"}
    )


def test_cancel_repair_exit5_service_still_loaded_keeps_failing(
    controller, monkeypatch, tmp_path
):
    """Repair (b): exit 5 with the service still loaded/active proves
    nothing, so the ORIGINAL stop failure is kept: FAIL verdict with the
    revocation done and the durable CLOSING state preserving an unknown
    cleanup outcome."""
    ctx = _cancel_repair_harness(
        monkeypatch, controller, tmp_path, present={_timer_base() + ".service"}
    )
    verdict = controller.cmd_close("dev")
    assert verdict.status == "FAIL"
    assert verdict.revoked is True
    assert verdict.diagnostic == "command failed"
    assert controller._read_state("dev").state == "CLOSING"
    assert ctx["show_calls"], "the unit state proof must have been consulted"


@pytest.mark.parametrize("show_mode", ["fail", "empty", "mismatch", "timeout"])
def test_cancel_repair_inconclusive_show_reraises_original_failure(
    controller, monkeypatch, tmp_path, show_mode
):
    """Repair (c): an inconclusive state query (communication failure, empty
    or mismatched output, timeout) is never success, and the re-raised
    failure is the ORIGINAL stop failure, not the query failure."""
    ctx = _cancel_repair_harness(monkeypatch, controller, tmp_path, show_mode=show_mode)
    target = _verified_target(ctx["checkout"])
    with pytest.raises(controller.Failure) as excinfo:
        controller._cancel_timer(target, _timer_base() + ".timer", RUN, include_service=True)
    assert str(excinfo.value) == "command failed"


def test_cancel_repair_callback_running_service_never_stopped_or_queried(
    controller, monkeypatch, tmp_path, capsys
):
    """Repair (d): callback cleanup requires only the timer unit; its own
    running service may appear in NO stop/show argv, and proven timer
    absence alone must allow the callback to finish CLOSED with success."""
    service = _timer_base() + ".service"
    ctx = _cancel_repair_harness(monkeypatch, controller, tmp_path, present={service})
    assert controller.main(["callback", "--target", "dev", "--run-id", RUN]) == 0
    assert controller._read_state("dev").state == "CLOSED"
    _cancel_repair_only_generation_units(ctx, {_timer_base() + ".timer"})
    capsys.readouterr()


def test_cancel_repair_repeat_close_absent_units_reaches_closed(
    controller, monkeypatch, tmp_path, capsys
):
    """Repair (e): repeating close over already-unloaded units (the durable
    CLOSING leftover of the original bug) must now complete to CLOSED/PASS."""
    ctx = _cancel_repair_harness(monkeypatch, controller, tmp_path, record="CLOSING")
    assert controller.main(["close", "--target", "dev"]) == 0
    assert controller._read_state("dev").state == "CLOSED"
    assert ctx["close_run_id"] == RUN
    capsys.readouterr()


def test_cancel_repair_zero_exit_stop_never_queries_units(controller, monkeypatch, tmp_path):
    """Repair (g): a zero-exit joint stop keeps today's behavior unchanged:
    success without any follow-up unit state queries."""
    ctx = _cancel_repair_harness(monkeypatch, controller, tmp_path, stop_exit=0)
    verdict = controller.cmd_close("dev")
    assert verdict.status == "PASS"
    assert verdict.revoked is True
    assert controller._read_state("dev").state == "CLOSED"
    assert ctx["show_calls"] == []


# ---------------------------------------------------------------------------
# ORIG-001 — private origins wired into doctor/open/run (R2/R4/R5)
# ---------------------------------------------------------------------------


def _empty_home(tmp_path, monkeypatch):
    """Point $HOME at a directory without any private profile."""
    home = tmp_path / "nohome"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    return home


def test_orig1_doctor_blocked_without_profile_and_without_effects(
    controller, host, tmp_path, monkeypatch
):
    _empty_home(tmp_path, monkeypatch)
    with pytest.raises(controller.Blocked):
        controller.cmd_doctor("dev", confirm_fictitious=True)
    assert host.calls == []
    assert not (tmp_path / "dev").exists()


def test_orig1_open_blocked_with_invalid_profile_and_without_effects(
    controller, host, tmp_path, monkeypatch
):
    home = tmp_path / "home"
    (home / ".config" / "sirhosp" / "verification.env").write_text(
        "SIRHOSP_VERIFY_DEV_ORIGIN=http://portal-dev.verification.invalid/\n"
        f"SIRHOSP_VERIFY_PROD_ORIGIN={SYN_PROD_ORIGIN}\n",
        encoding="utf-8",
    )
    with pytest.raises(controller.Blocked):
        controller.cmd_open("dev", confirm_fictitious=True)
    assert "prepare" not in host.calls and "open" not in host.calls
    assert "arm" not in host.calls
    assert not (tmp_path / "dev").exists()


def test_orig1_run_blocked_without_profile_before_open_effects(
    controller, host, tmp_path, monkeypatch
):
    _empty_home(tmp_path, monkeypatch)
    with pytest.raises(controller.Blocked):
        controller.cmd_run(
            "dev", feature="auth", roles=("user",), confirm_synthetic_data=True
        )
    assert host.calls == []


def test_orig1_doctor_and_open_report_the_canonical_origin(controller, host):
    doctor = controller.cmd_doctor("dev", confirm_fictitious=True)
    assert doctor.status == "PASS"
    assert doctor.origin == SYN_DEV_ORIGIN
    opened = controller.cmd_open("dev", confirm_fictitious=True)
    assert opened.origin == SYN_DEV_ORIGIN
    assert opened.origin == doctor.origin


def test_orig1_open_main_emission_includes_origin(controller, host, capsys):
    assert controller.main(["open", "--target", "dev", "--confirm-fictitious"]) == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["origin"] == SYN_DEV_ORIGIN
    assert payload["target"] == "dev"


def test_orig1_doctor_main_emission_includes_origin(controller, host, capsys):
    assert controller.main(["doctor", "--target", "dev", "--confirm-fictitious"]) == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["origin"] == SYN_DEV_ORIGIN
    assert payload["status"] == "PASS"


def test_orig1_close_and_status_are_independent_of_the_profile(
    controller, host, tmp_path, monkeypatch
):
    opened = controller.cmd_open("dev", confirm_fictitious=True)
    _empty_home(tmp_path, monkeypatch)
    status = controller.cmd_status("dev")
    assert status.state == "ACTIVE"
    assert status.run_id == opened.run_id
    verdict = controller.cmd_close("dev", run_id=opened.run_id)
    assert verdict.status == "PASS"
    assert verdict.revoked is True


def test_orig1_stale_callback_is_independent_of_the_profile(
    controller, host, tmp_path, monkeypatch
):
    controller.cmd_open("dev", confirm_fictitious=True)
    _empty_home(tmp_path, monkeypatch)
    verdict = controller.cmd_callback("dev", run_id=RUN)
    assert verdict.status == "SKIPPED"
