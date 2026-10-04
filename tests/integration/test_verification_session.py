"""Owned-pair generation fence and real PostgreSQL form-authentication proof."""

from __future__ import annotations

import hashlib
import importlib
import ipaddress
import json
import re
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection
from django.test import Client, override_settings

from apps.accounts.models import UserProfile

RUN = "a" * 32
NEXT = "b" * 32


@pytest.fixture
def domain():
    return importlib.import_module("apps.accounts.verification")


@pytest.fixture(autouse=True)
def isolated_database(db):
    assert connection.vendor == "postgresql"
    assert connection.settings_dict["NAME"].startswith("test_")


def open_pair(domain, run=RUN):
    prepared = domain.prepare_owned_pair(
        run_id=run, expect_state=domain.read_owned_pair_state().snapshot
    )
    return domain.open_owned_pair(run_id=run, expect_state=prepared.snapshot_after)


def metadata():
    return list(User.objects.order_by("pk").values())


def command(domain, action, *, run=RUN, snapshot=None, extra=()):
    adapter = importlib.import_module("apps.accounts.management.commands.verification_session")
    args = [
        action,
        "--dev-context-confirm",
        "--target",
        "dev",
        "--expect-db-fingerprint",
        adapter.database_fingerprint(),
    ]
    if action in {"prepare", "open", "close", "recover"}:
        args += ["--run-id", run]
    if snapshot is not None:
        args += ["--expect-state", snapshot]
    out = StringIO()
    call_command("verification_session", *args, *extra, stdout=out)
    lines = out.getvalue().strip().splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def form_login(client, username, password):
    page = client.get("/login/")
    assert page.status_code == 200
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode())
    assert token is not None
    return client.post(
        "/login/",
        {"username": username, "password": password, "csrfmiddlewaretoken": token.group(1)},
    )


def test_r2_missing_pair_creates_exact_roles_profiles_and_preserves_human(domain):
    human = User.objects.create_user(
        "synthetic-human", password="synthetic-only", first_name="Human"
    )
    before = metadata()
    opened = open_pair(domain)
    assert len(set(opened.passwords.values())) == 2
    assert len(opened.pair_ids) == 2
    assert set(opened.passwords) == {"verify_user", "verify_admin"}
    for username, password in opened.passwords.items():
        user = User.objects.get(username=username)
        assert user.is_active and user.check_password(password)
        assert user.email == username + "@verification.invalid"
        assert user.first_name.startswith("vfyA:" + RUN + ":") and user.last_name == ""
        assert user.is_staff == (username == "verify_admin")
        assert user.is_superuser == (username == "verify_admin")
        assert not user.profile.must_change_password
        assert user.has_perm("statistics_reports.view_daily_statistics") == (
            username == "verify_admin"
        )
        assert user.has_perm("statistics_reports.export_daily_statistics") == (
            username == "verify_admin"
        )
        assert password not in repr(opened)
        assert password not in repr(domain.read_owned_pair_state())
    assert metadata()[0] == before[0]
    human.refresh_from_db()
    assert human.first_name == "Human"


def test_r2_permission_paths_are_removed_on_common_account(domain):
    common = User.objects.create_user(
        "verify_user",
        email="verify_user@verification.invalid",
        is_active=False,
        is_staff=True,
        is_superuser=True,
    )
    permissions = Permission.objects.filter(
        content_type__app_label="statistics_reports",
        codename__in=["view_daily_statistics", "export_daily_statistics"],
    )
    assert permissions.count() == 2
    common.user_permissions.add(*permissions)
    group = Group.objects.create(name="synthetic-statistics")
    group.permissions.add(*permissions)
    common.groups.add(group)
    UserProfile.objects.create(user=common, must_change_password=True)
    open_pair(domain)
    fresh = User.objects.get(pk=common.pk)
    assert not fresh.groups.exists()
    assert not fresh.user_permissions.filter(pk__in=permissions.values("pk")).exists()
    assert not fresh.has_perm("statistics_reports.view_daily_statistics")
    assert not fresh.has_perm("statistics_reports.export_daily_statistics")
    assert not fresh.profile.must_change_password


@pytest.mark.parametrize("collision", ["verify_user", "verify_admin"])
def test_r2_collision_blocks_the_entire_pair(domain, collision):
    User.objects.create_user(
        collision, email="synthetic-human@example.invalid", password="synthetic-only"
    )
    before = metadata()
    with pytest.raises(domain.OwnershipCollision):
        open_pair(domain)
    assert metadata() == before


@pytest.mark.parametrize(
    "active,token,usable", [(True, "", False), (False, "vfyA:" + RUN, False), (False, "", True)]
)
def test_r2_unexpected_active_or_usable_rows_are_not_adopted(domain, active, token, usable):
    user = User.objects.create_user(
        "verify_user", email="verify_user@verification.invalid", is_active=active, first_name=token
    )
    if usable:
        user.set_password("synthetic-only")
        user.save()
    before = metadata()
    with pytest.raises(domain.GenerationMismatch):
        open_pair(domain)
    assert metadata() == before


def test_r3_passwords_differ_between_runs_and_are_only_returned_once(domain):
    first = open_pair(domain)
    domain.close_owned_pair(run_id=RUN)
    second = open_pair(domain, NEXT)
    assert len(set([*first.passwords.values(), *second.passwords.values()])) == 4
    assert all(len(value) >= 43 for value in second.passwords.values())
    with pytest.raises(domain.GenerationMismatch):
        open_pair(domain, NEXT)


def test_r4_real_csrf_form_login_and_old_session_refused_for_both_roles(domain):
    opened = open_pair(domain)
    clients = {}
    for username, password in opened.passwords.items():
        client = Client(enforce_csrf_checks=True)
        assert (
            client.post("/login/", {"username": username, "password": password}).status_code == 403
        )
        response = form_login(client, username, password)
        assert response.status_code == 302 and response["Location"] == "/painel/"
        panel = client.get("/painel/")
        assert panel.status_code == 200 and panel.wsgi_request.user.is_authenticated
        clients[username] = client
    assert domain.close_owned_pair(run_id=RUN).revoked
    for username, password in opened.passwords.items():
        user = User.objects.get(username=username)
        assert (
            not user.is_active
            and not user.has_usable_password()
            and not user.check_password(password)
        )
        panel = clients[username].get("/painel/")
        assert panel.status_code == 302 and not panel.wsgi_request.user.is_authenticated
        assert form_login(Client(enforce_csrf_checks=True), username, password).status_code == 200
    assert domain.close_owned_pair(run_id=RUN).already_revoked


@pytest.mark.parametrize(
    "missing", [[], ["verify_user"], ["verify_admin"], ["verify_user", "verify_admin"]]
)
def test_r4_close_never_creates_missing_rows(domain, missing):
    open_pair(domain)
    User.objects.filter(username__in=missing).delete()
    count = User.objects.count()
    assert domain.close_owned_pair(run_id=RUN).revoked
    assert domain.close_owned_pair(run_id=RUN).already_revoked
    assert User.objects.count() == count
    assert not User.objects.filter(is_active=True).exists()


def test_r4_close_and_recover_ignore_debug_and_migration_readiness(domain, monkeypatch):
    with override_settings(DEBUG=False):
        prepared = command(domain, "prepare", snapshot=domain.read_owned_pair_state().snapshot)
        command(domain, "open", snapshot=prepared["snapshot_after"])
    with override_settings(DEBUG=True):
        adapter = importlib.import_module("apps.accounts.management.commands.verification_session")
        monkeypatch.setattr(adapter, "migrations_clean", lambda: False)
        assert command(domain, "close")["revoked"]
        assert command(domain, "recover", snapshot=domain.read_owned_pair_state().snapshot)[
            "revoked"
        ]


def test_r5_recovery_advances_legacy_tombstone_and_fences_abandoned_open(domain):
    user = User.objects.create_user(
        "verify_user", email="verify_user@verification.invalid", is_active=False
    )
    observed = domain.read_owned_pair_state().snapshot
    recovered = domain.recover_owned_pair(run_id=RUN, expect_state=observed)
    assert recovered.revoked
    user.refresh_from_db()
    assert user.first_name.startswith("vfyR:" + RUN + ":")
    with pytest.raises(domain.GenerationMismatch):
        domain.open_owned_pair(run_id=NEXT, expect_state=observed)
    assert domain.recover_owned_pair(
        run_id=RUN, expect_state=recovered.snapshot_after
    ).already_revoked


def test_r5_stale_close_cannot_revoke_new_generation(domain):
    open_pair(domain)
    domain.close_owned_pair(run_id=RUN)
    open_pair(domain, NEXT)
    before = metadata()
    with pytest.raises(domain.GenerationMismatch):
        domain.close_owned_pair(run_id=RUN)
    assert metadata() == before


def test_r5_mixed_generation_close_is_atomic(domain):
    open_pair(domain)
    User.objects.filter(username="verify_admin").update(first_name="vfyA:" + NEXT)
    before = metadata()
    with pytest.raises(domain.GenerationMismatch):
        domain.close_owned_pair(run_id=RUN)
    assert metadata() == before


def test_r5_recovery_collision_is_atomic(domain):
    open_pair(domain)
    User.objects.filter(username="verify_admin").update(email="synthetic-human@example.invalid")
    before = metadata()
    with pytest.raises(domain.OwnershipCollision):
        domain.recover_owned_pair(run_id=NEXT, expect_state=domain.read_owned_pair_state().snapshot)
    assert metadata() == before


@pytest.mark.django_db(transaction=True)
def test_r5_concurrent_open_cas_has_one_winner(domain):
    expected = domain.read_owned_pair_state().snapshot
    barrier = Barrier(2)

    def attempt(run):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            try:
                prepared = domain.prepare_owned_pair(run_id=run, expect_state=expected)
                domain.open_owned_pair(run_id=run, expect_state=prepared.snapshot_after)
                return "opened"
            except domain.GenerationMismatch:
                return "fenced"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, [RUN, NEXT]))
    assert sorted(outcomes) == ["fenced", "opened"]
    assert User.objects.filter(is_active=True).count() == 2


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["open"],
        ["open", "--dev-context-confirm"],
        ["close", "--dev-context-confirm", "--target", "prod"],
        ["open", "--dev-context-confirm", "--target", "dev", "--expect-db-fingerprint", "0" * 64],
    ],
)
def test_r1_bare_or_incomplete_direct_command_is_write_free(domain, args):
    before = metadata()
    with pytest.raises(CommandError):
        call_command("verification_session", *args, stdout=StringIO())
    assert metadata() == before


def test_r1_preflight_context_and_live_fingerprint_are_read_only(domain):
    before = metadata()
    result = command(domain, "preflight")
    assert re.fullmatch("[0-9a-f]{64}", result["fingerprint"])
    assert result["server_address"] and result["server_port"] == 5432
    assert result["pair"]["snapshot"] == domain.read_owned_pair_state().snapshot
    assert metadata() == before


def test_r1_direct_open_refuses_debug_and_drift(domain, monkeypatch):
    before = metadata()
    with override_settings(DEBUG=True), pytest.raises(CommandError):
        command(domain, "open", snapshot=domain.read_owned_pair_state().snapshot)
    adapter = importlib.import_module("apps.accounts.management.commands.verification_session")
    monkeypatch.setattr(adapter, "migrations_clean", lambda: False)
    with override_settings(DEBUG=False), pytest.raises(CommandError):
        command(domain, "open", snapshot=domain.read_owned_pair_state().snapshot)
    assert metadata() == before


@pytest.mark.parametrize("run,snapshot", [("bad", "0" * 64), (RUN, "bad")])
def test_r1_invalid_tokens_are_write_free(domain, run, snapshot):
    before = metadata()
    with override_settings(DEBUG=False), pytest.raises(CommandError):
        command(domain, "open", run=run, snapshot=snapshot)
    assert metadata() == before


def test_r3_command_output_contains_single_in_memory_credential_response(domain):
    with override_settings(DEBUG=False):
        prepared = command(domain, "prepare", snapshot=domain.read_owned_pair_state().snapshot)
        result = command(domain, "open", snapshot=prepared["snapshot_after"])
    assert set(result["passwords"]) == {"verify_user", "verify_admin"}
    status = command(domain, "owned-status")
    closed = command(domain, "close")
    for value in result["passwords"].values():
        assert value not in json.dumps(status) and value not in json.dumps(closed)


@pytest.mark.parametrize("action", ["close", "recover"])
def test_r5_absent_closure_followed_by_delayed_prepare_cannot_activate(domain, action):
    absent = domain.read_owned_pair_state().snapshot
    if action == "recover":
        domain.recover_owned_pair(run_id=RUN, expect_state=absent)
    else:
        domain.close_owned_pair(run_id=RUN)
    with pytest.raises(domain.GenerationMismatch):
        domain.open_owned_pair(run_id=RUN, expect_state=absent)
    domain.prepare_owned_pair(run_id=RUN, expect_state=absent)
    with pytest.raises(domain.GenerationMismatch):
        domain.open_owned_pair(run_id=RUN, expect_state=absent)
    assert not User.objects.filter(is_active=True).exists()
    assert all(not user.has_usable_password() for user in User.objects.all())
    with pytest.raises(domain.GenerationMismatch):
        domain.prepare_owned_pair(run_id=NEXT, expect_state=domain.read_owned_pair_state().snapshot)


def test_r5_delayed_duplicate_activation_cannot_revive_after_close(domain):
    prepared = domain.prepare_owned_pair(
        run_id=RUN, expect_state=domain.read_owned_pair_state().snapshot
    )
    domain.open_owned_pair(run_id=RUN, expect_state=prepared.snapshot_after)
    domain.close_owned_pair(run_id=RUN)
    assert domain.read_owned_pair_state().snapshot != prepared.snapshot_after
    with pytest.raises(domain.GenerationMismatch):
        domain.open_owned_pair(run_id=RUN, expect_state=prepared.snapshot_after)
    assert not User.objects.filter(is_active=True).exists()


def test_r5_new_preparation_fences_old_activation_and_recovery_without_aba(domain):
    observed = domain.read_owned_pair_state().snapshot
    prepared = domain.prepare_owned_pair(run_id=RUN, expect_state=observed)
    domain.close_owned_pair(run_id=RUN)
    tombstone = domain.read_owned_pair_state().snapshot
    newer = domain.prepare_owned_pair(run_id=NEXT, expect_state=tombstone)
    assert len({observed, prepared.snapshot_after, tombstone, newer.snapshot_after}) == 4
    with pytest.raises(domain.GenerationMismatch):
        domain.open_owned_pair(run_id=RUN, expect_state=prepared.snapshot_after)
    with pytest.raises(domain.GenerationMismatch):
        domain.recover_owned_pair(run_id=RUN, expect_state=tombstone)
    assert not User.objects.filter(is_active=True).exists()


def test_r5_snapshot_encoding_is_canonical_and_secret_free(domain):
    initial = domain.read_owned_pair_state().snapshot
    open_pair(domain)
    active = domain.read_owned_pair_state().snapshot
    assert initial != active
    user = User.objects.get(username="verify_user")
    user.set_password("another-synthetic-password")
    user.save(update_fields=["password"])
    assert domain.read_owned_pair_state().snapshot == active


@pytest.mark.parametrize("slot", ["verify_user", "verify_admin"])
def test_r6_pk_replacement_fences_activation(domain, slot):
    prepared = domain.prepare_owned_pair(
        run_id=RUN, expect_state=domain.read_owned_pair_state().snapshot
    )
    old_snapshot = prepared.snapshot_after
    assert domain.read_owned_pair_state().snapshot == old_snapshot
    row = User.objects.get(username=slot)
    old_pk = row.pk
    stamp = row.first_name
    assert stamp.startswith("vfyP:" + RUN + ":")
    profiles_before = UserProfile.objects.count()
    row.delete()
    replacement = User(
        username=slot,
        email=slot + "@verification.invalid",
        first_name=stamp,
        last_name="",
        is_active=False,
    )
    replacement.set_unusable_password()
    replacement.save()
    assert replacement.pk != old_pk
    with pytest.raises(domain.GenerationMismatch):
        domain.open_owned_pair(run_id=RUN, expect_state=old_snapshot)
    assert domain.read_owned_pair_state().snapshot != old_snapshot
    for username in ("verify_user", "verify_admin"):
        current = User.objects.get(username=username)
        assert not current.is_active
        assert not current.has_usable_password()
        assert current.first_name.startswith("vfyP:" + RUN + ":")
    assert UserProfile.objects.count() == profiles_before


def test_r6_snapshot_ignores_password_material(domain):
    prepared = domain.prepare_owned_pair(
        run_id=RUN, expect_state=domain.read_owned_pair_state().snapshot
    )
    before = prepared.snapshot_after
    user = User.objects.get(username="verify_user")
    user.set_password("another-synthetic-password")
    user.save(update_fields=["password"])
    assert domain.read_owned_pair_state().snapshot == before
    user.set_unusable_password()
    user.save(update_fields=["password"])
    assert domain.read_owned_pair_state().snapshot == before


def test_r1_server_address_matches_sql_host_without_cidr(domain):
    adapter = importlib.import_module("apps.accounts.management.commands.verification_session")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT inet_server_addr()::text, host(inet_server_addr()), inet_server_port()"
        )
        raw_cast, host_address, server_port = cursor.fetchone()
    masked_host, _, mask_bits = str(raw_cast).rpartition("/")
    assert masked_host == host_address and mask_bits in {"32", "128"}
    assert "/" not in str(host_address)
    _, address, port = adapter.database_identity()
    assert address == host_address
    assert "/" not in address
    assert ipaddress.ip_address(address)
    assert port == server_port
    result = command(domain, "preflight")
    assert result["server_address"] == host_address
    assert result["server_port"] == server_port


def test_r1_route_boundary_rejects_drifted_address_port_and_null(domain):
    controller = importlib.import_module("scripts.verify_portal")
    preflight = command(domain, "preflight")
    address = preflight["server_address"]
    port = preflight["server_port"]

    def target(expected_address, expected_port):
        return SimpleNamespace(db_address=expected_address, db_port=expected_port)

    controller._check_django_response(
        target(address, port), "preflight", expected=preflight["fingerprint"], payload=preflight
    )
    with pytest.raises(controller.Blocked, match="database route mismatch"):
        controller._check_django_response(
            target("192.0.2.77", port),
            "preflight",
            expected=preflight["fingerprint"],
            payload=preflight,
        )
    with pytest.raises(controller.Blocked, match="database port mismatch"):
        controller._check_django_response(
            target(address, int(port) + 1),
            "preflight",
            expected=preflight["fingerprint"],
            payload=preflight,
        )
    with pytest.raises(controller.Blocked, match="database endpoint unverified"):
        controller._check_django_response(
            target(address, port),
            "preflight",
            expected=preflight["fingerprint"],
            payload={**preflight, "server_address": None},
        )
    with pytest.raises(controller.Blocked, match="database fingerprint mismatch"):
        controller._check_django_response(
            target(address, port), "preflight", expected="0" * 64, payload=preflight
        )


def test_r1_fingerprint_primary_and_strict_full_row_fallback(domain, monkeypatch):
    adapter = importlib.import_module("apps.accounts.management.commands.verification_session")

    def digest(parts):
        return hashlib.sha256(
            b"vfy-db-v1\n" + json.dumps(list(parts), separators=(",", ":")).encode()
        ).hexdigest()

    with connection.cursor() as cursor:
        cursor.execute(adapter.IDENTITY_SQL)
        captured = list(cursor.fetchone())

    class FakeCursor:
        def __init__(self, row):
            self.row = tuple(row)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def execute(self, sql):
            del sql

        def fetchone(self):
            return self.row

    class FakeConnection:
        vendor = "postgresql"

        def __init__(self, row):
            self.row = list(row)

        def cursor(self):
            return FakeCursor(self.row)

    def identity_for(row):
        monkeypatch.setattr(adapter, "connection", FakeConnection(row))
        return adapter.database_identity()

    fingerprint, address, port = adapter.database_identity()
    assert address == captured[6] and port == captured[7]
    if captured[0]:
        assert fingerprint == digest(captured[:2])
    fallback_row = [None, *captured[1:]]
    assert identity_for(fallback_row)[0] == digest(fallback_row)
    drifted_address = [*fallback_row]
    drifted_address[6] = "192.0.2.77"
    assert identity_for(drifted_address)[0] != digest(fallback_row)
    drifted_port = [*fallback_row]
    drifted_port[7] = int(fallback_row[7]) + 1
    assert identity_for(drifted_port)[0] != digest(fallback_row)
    null_row = [*fallback_row]
    null_row[6] = None
    null_identity = identity_for(null_row)
    assert null_identity[1] is None and null_identity[0] == digest(null_row)
    masked_row = [*fallback_row]
    masked_row[6] = f"{fallback_row[6]}/32"
    assert identity_for(masked_row)[0] != digest(fallback_row)
