"""Fixed verification accounts with snapshot CAS and nonsecret generation stamps."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field

from django.contrib.auth.models import Permission, User
from django.db import IntegrityError, connection, transaction

from apps.accounts.models import UserProfile

PREPARED_PREFIX = "vfyP:"
ACTIVE_PREFIX = "vfyA:"
REVOKED_PREFIX = "vfyR:"
OWNED = (
    ("verify_user", "verify_user@verification.invalid"),
    ("verify_admin", "verify_admin@verification.invalid"),
)
RUN_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
SNAPSHOT_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
TOKEN_PATTERN = re.compile(r"vfy[PAR]:([0-9a-f]{32}):[0-9a-f]{32}\Z")


class OwnershipCollision(Exception):
    pass


class GenerationMismatch(Exception):
    pass


@dataclass(frozen=True)
class OwnedAccountState:
    username: str
    user_id: int | None
    token: str
    exists: bool
    owned: bool
    is_active: bool
    has_usable_password: bool
    is_staff: bool
    is_superuser: bool
    must_change_password: bool | None


@dataclass(frozen=True)
class OwnedPairState:
    user: OwnedAccountState
    admin: OwnedAccountState
    snapshot: str


@dataclass(frozen=True)
class PreparePairResult:
    snapshot_after: str


@dataclass(frozen=True)
class OpenPairResult:
    pair_ids: tuple[int, int]
    passwords: dict[str, str] = field(repr=False)
    snapshot_after: str


@dataclass(frozen=True)
class ClosePairResult:
    revoked: bool
    already_revoked: bool
    snapshot_after: str


def _validate(run_id: str, expect_state: str | None = None) -> None:
    if not RUN_PATTERN.fullmatch(run_id):
        raise GenerationMismatch("Invalid run-id")
    if expect_state is not None and not SNAPSHOT_PATTERN.fullmatch(expect_state):
        raise GenerationMismatch("Invalid snapshot")


def _rows(*, locked: bool = False) -> dict[str, User]:
    queryset = User.objects.filter(username__in=[name for name, _ in OWNED]).order_by("username")
    if locked:
        # Absent rows cannot be row-locked. This also serializes first creation.
        if connection.vendor != "postgresql":
            raise GenerationMismatch("Verification requires PostgreSQL")
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(1936287858, 1447449393)")
        queryset = queryset.select_for_update()
    return {user.username: user for user in queryset}


def _state(rows: dict[str, User]) -> OwnedPairState:
    accounts = []
    for username, email in OWNED:
        user = rows.get(username)
        profile = UserProfile.objects.filter(user=user).first() if user else None
        accounts.append(
            OwnedAccountState(
                username=username,
                user_id=user.pk if user else None,
                token=user.first_name if user else "",
                exists=user is not None,
                owned=user.email == email if user else True,
                is_active=user.is_active if user else False,
                has_usable_password=user.has_usable_password() if user else False,
                is_staff=user.is_staff if user else False,
                is_superuser=user.is_superuser if user else False,
                must_change_password=profile.must_change_password if profile else None,
            )
        )
    canonical = [
        [account.username, account.user_id, account.exists, account.token]
        for account in accounts
    ]
    digest = hashlib.sha256(
        b"vfy-pair-v2\n" + json.dumps(canonical, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    return OwnedPairState(accounts[0], accounts[1], digest)


def read_owned_pair_state() -> OwnedPairState:
    return _state(_rows())


def _check_owned(rows: dict[str, User]) -> None:
    for username, email in OWNED:
        if username in rows and rows[username].email != email:
            raise OwnershipCollision(f"Reserved username collision: {username}")


def _cas(rows: dict[str, User], expected: str) -> None:
    _check_owned(rows)
    if _state(rows).snapshot != expected:
        raise GenerationMismatch("Owned-pair snapshot changed")


def _token(prefix: str, run_id: str) -> str:
    return prefix + run_id + ":" + secrets.token_hex(16)


def _matches(token: str, prefix: str, run_id: str) -> bool:
    return bool(TOKEN_PATTERN.fullmatch(token)) and token.startswith(prefix + run_id + ":")


def prepare_owned_pair(*, run_id: str, expect_state: str) -> PreparePairResult:
    """Prepare inactive rows. Activation never accepts an absent-pair snapshot."""
    _validate(run_id, expect_state)
    for attempt in range(2):
        try:
            with transaction.atomic():
                rows = _rows(locked=True)
                _cas(rows, expect_state)
                for user in rows.values():
                    if (
                        user.is_active
                        or user.has_usable_password()
                        or user.first_name.startswith((PREPARED_PREFIX, ACTIVE_PREFIX))
                    ):
                        raise GenerationMismatch("Interrupted or active pair requires recovery")
                stamp = _token(PREPARED_PREFIX, run_id)
                for username, email in OWNED:
                    user = rows.get(username) or User(username=username, email=email)
                    user.set_unusable_password()
                    user.is_active = False
                    user.first_name = stamp
                    user.last_name = ""
                    user.save()
                    rows[username] = user
                return PreparePairResult(_state(rows).snapshot)
        except IntegrityError:
            if attempt:
                raise GenerationMismatch("Concurrent account creation") from None
    raise AssertionError("Unreachable")


def open_owned_pair(*, run_id: str, expect_state: str) -> OpenPairResult:
    _validate(run_id, expect_state)
    with transaction.atomic():
        rows = _rows(locked=True)
        _cas(rows, expect_state)
        if len(rows) != 2 or any(
            user.is_active
            or user.has_usable_password()
            or not _matches(user.first_name, PREPARED_PREFIX, run_id)
            for user in rows.values()
        ):
            raise GenerationMismatch("Activation requires the exact prepared pair")
        passwords = {username: secrets.token_urlsafe(32) for username, _ in OWNED}
        stamp = _token(ACTIVE_PREFIX, run_id)
        statistics = Permission.objects.filter(
            content_type__app_label="statistics_reports",
            codename__in=["view_daily_statistics", "export_daily_statistics"],
        )
        for username, _ in OWNED:
            user = rows[username]
            user.set_password(passwords[username])
            user.is_active = True
            user.is_staff = username == "verify_admin"
            user.is_superuser = username == "verify_admin"
            user.first_name = stamp
            user.last_name = ""
            user.save()
            if username == "verify_user":
                user.groups.clear()
                user.user_permissions.remove(*statistics)
            UserProfile.objects.update_or_create(
                user=user, defaults={"must_change_password": False}
            )
        common = User.objects.get(pk=rows["verify_user"].pk)
        if any(
            common.has_perm("statistics_reports." + name)
            for name in ("view_daily_statistics", "export_daily_statistics")
        ):
            raise GenerationMismatch("Common account retains statistics permissions")
        return OpenPairResult(
            (rows["verify_user"].pk, rows["verify_admin"].pk), passwords, _state(rows).snapshot
        )


def _revoke(rows: dict[str, User], run_id: str) -> ClosePairResult:
    already = all(
        not user.is_active
        and not user.has_usable_password()
        and _matches(user.first_name, REVOKED_PREFIX, run_id)
        for user in rows.values()
    )
    if not already:
        stamp = _token(REVOKED_PREFIX, run_id)
        for user in rows.values():
            user.set_unusable_password()
            user.is_active = False
            user.first_name = stamp
            user.last_name = ""
            user.save(update_fields=["password", "is_active", "first_name", "last_name"])
    return ClosePairResult(True, already, _state(rows).snapshot)


def close_owned_pair(*, run_id: str) -> ClosePairResult:
    _validate(run_id)
    with transaction.atomic():
        rows = _rows(locked=True)
        _check_owned(rows)
        for user in rows.values():
            if _matches(user.first_name, REVOKED_PREFIX, run_id):
                if user.is_active or user.has_usable_password():
                    raise GenerationMismatch("Revoked stamp has live authentication")
            elif not any(
                _matches(user.first_name, prefix, run_id)
                for prefix in (PREPARED_PREFIX, ACTIVE_PREFIX)
            ):
                raise GenerationMismatch("Close generation does not match")
        return _revoke(rows, run_id)


def recover_owned_pair(*, run_id: str, expect_state: str) -> ClosePairResult:
    _validate(run_id, expect_state)
    with transaction.atomic():
        rows = _rows(locked=True)
        _cas(rows, expect_state)
        return _revoke(rows, run_id)
