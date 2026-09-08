"""Integration tests for provisional-password provisioning and forced
first-login password change (SLICE-AUP-S2).

``RequirePasswordChangeMiddleware`` redirects an authenticated user whose
``UserProfile.must_change_password`` is active away from every path outside
the allowlist to ``/perfil/``; anonymous users and unflagged users are never
redirected. The ``create_portal_user`` management command provisions active
common users whose one-time password is printed exactly once on stdout and
reissues/re-flags via ``--reset-password``.
"""

import re
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client

from apps.accounts.models import UserProfile

COMMAND = "create_portal_user"
TOKEN_LINE_RE = re.compile(r"^temporary_password=(.+)$", re.MULTILINE)


@pytest.fixture
def client() -> Client:
    return Client()


def run_command(*args: str) -> str:
    """Run ``create_portal_user`` and return the captured stdout."""
    out = StringIO()
    call_command(COMMAND, *args, stdout=out)
    return out.getvalue()


def printed_token(output: str) -> str:
    """Extract the single ``temporary_password=<token>`` line value."""
    match = TOKEN_LINE_RE.search(output)
    assert match is not None, f"missing temporary_password line in: {output!r}"
    return match.group(1)


def assert_token_printed_once(output: str) -> str:
    """The token appears exactly once, on a stable ``temporary_password=`` line."""
    token = printed_token(output)
    assert output.count(token) == 1
    assert f"temporary_password={token}\n" in output
    return token


# ── R1: UserProfile 1:1 model ────────────────────────────────────


class TestUserProfileModel:
    def test_userprofile_flag_and_onetoone(self, db: None) -> None:
        """Profile is 1:1 with User and carries the flag plus created_at."""
        user = User.objects.create_user(
            username="operador",
            password="testpass123",
            first_name="Maria",
            last_name="Silva",
        )
        profile = UserProfile.objects.create(user=user, must_change_password=True)

        assert profile.user_id == user.id
        assert user.profile == profile
        assert profile.must_change_password is True
        assert profile.created_at is not None

        # Default flag is False for a fresh profile.
        plain = UserProfile.objects.create(user=User.objects.create_user("outro"))
        assert plain.must_change_password is False


# ── R2/R3: forced-change middleware ──────────────────────────────


def _flagged_user(db: None, username: str = "operador") -> User:
    """Create an active common user flagged for provisional-password change."""
    user = User.objects.create_user(
        username=username,
        password="testpass123",
        first_name="Maria",
        last_name="Silva",
    )
    UserProfile.objects.create(user=user, must_change_password=True)
    return user


class TestMiddlewareForcedChange:
    def test_flagged_user_redirected_from_painel(
        self, client: Client, db: None
    ) -> None:
        """Flagged authenticated user is sent from /painel/ to /perfil/."""
        _flagged_user(db)
        assert client.login(username="operador", password="testpass123")

        resp = client.get("/painel/")
        assert resp.status_code == 302
        assert resp["Location"] == "/perfil/"

    def test_allowlisted_paths_pass(self, client: Client, db: None) -> None:
        """Flagged user is not redirected on /perfil/, /health/, /admin/,
        /static/, /login/ and /logout/ paths."""
        _flagged_user(db)
        assert client.login(username="operador", password="testpass123")

        # /perfil/ renders the change form normally (no redirect).
        resp = client.get("/perfil/")
        assert resp.status_code == 200

        # Monitoring probe stays public even for an authenticated user.
        resp = client.get("/health/")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/json"

        # /login/ for an authenticated user redirects to the portal, not /perfil/.
        resp = client.get("/login/")
        assert resp.status_code == 302
        assert resp["Location"] != "/perfil/"

        # /admin/ and /static/ are handled by the app, never forced to /perfil/.
        for resp in [client.get("/admin/"), client.get("/static/app.css")]:
            assert resp.status_code != 302 or resp["Location"] != "/perfil/"

        # /logout/ still works for the flagged user.
        resp = client.post("/logout/")
        assert resp.status_code == 302
        assert resp["Location"] == "/"

    def test_anonymous_never_redirected(self, client: Client) -> None:
        """Anonymous requests are never redirected to /perfil/."""
        resp = client.get("/health/")
        assert resp.status_code == 200

        resp = client.get("/painel/")
        assert resp.status_code == 302
        assert resp["Location"] == "/login/?next=/painel/"

        resp = client.get("/perfil/")
        assert resp.status_code == 302
        assert resp["Location"] == "/login/?next=/perfil/"

    def test_unflagged_user_unaffected(self, client: Client, db: None) -> None:
        """Users without a flag (or without a profile) are not redirected."""
        user = _flagged_user(db)
        profile = user.profile
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])
        assert client.login(username="operador", password="testpass123")

        resp = client.get("/painel/")
        assert resp.status_code == 200

        # No profile at all: identical pre-slice behaviour.
        client.logout()
        User.objects.create_user(username="semperfil", password="testpass123")
        client.login(username="semperfil", password="testpass123")
        resp = client.get("/painel/")
        assert resp.status_code == 200


# ── R5: create mode ──────────────────────────────────────────────


class TestCreatePortalUserCommand:
    def test_create_user_common_active_with_flag_and_printed_password(
        self, client: Client, db: None
    ) -> None:
        """Create mode provisions an active common user, split full name,
        flagged profile and exactly one printed provisional password."""
        output = run_command("enfermeira.ana", "--full-name", "Ana Oliveira Souza")
        assert_token_printed_once(output)

        user = User.objects.get(username="enfermeira.ana")
        assert user.is_active is True
        assert user.is_staff is False
        assert user.is_superuser is False
        # Full-name split rule: first word -> first_name, rest -> last_name.
        assert user.first_name == "Ana"
        assert user.last_name == "Oliveira Souza"

        profile = user.profile
        assert profile.must_change_password is True

    def test_single_word_full_name_leaves_last_name_empty(
        self, client: Client, db: None
    ) -> None:
        """A single-word --full-name leaves last_name empty (split rule)."""
        output = run_command("diretora", "--full-name", "Camila")
        assert_token_printed_once(output)

        user = User.objects.get(username="diretora")
        assert user.first_name == "Camila"
        assert user.last_name == ""

    def test_printed_password_authenticates_and_forces_change(
        self, client: Client, db: None
    ) -> None:
        """The printed provisional password logs in and immediately forces
        the change (R6)."""
        output = run_command("enfermeira.bea", "--full-name", "Beatriz Rocha")
        token = assert_token_printed_once(output)

        assert client.login(username="enfermeira.bea", password=token)

        # Any non-allowlisted portal path redirects to /perfil/ right away.
        resp = client.get("/painel/")
        assert resp.status_code == 302
        assert resp["Location"] == "/perfil/"

        # The profile page itself stays reachable for the forced change.
        resp = client.get("/perfil/")
        assert resp.status_code == 200

    def test_duplicate_username_fails_without_mutation(
        self, client: Client, db: None
    ) -> None:
        """Recreating an existing username fails clearly and mutates nothing."""
        first = run_command("operador", "--full-name", "Maria Silva")
        token = assert_token_printed_once(first)

        out = StringIO()
        with pytest.raises(CommandError) as excinfo:
            call_command(COMMAND, "operador", "--full-name", "Maria Silva", stdout=out)
        assert "já existe" in str(excinfo.value)
        assert out.getvalue() == ""

        # No mutation: same single user, still active, same original password.
        assert User.objects.filter(username="operador").count() == 1
        assert UserProfile.objects.filter(user__username="operador").count() == 1
        user = User.objects.get(username="operador")
        assert user.check_password(token)
        assert not user.check_password("Maria Silva")

    def test_no_plaintext_password_persisted(self, client: Client, db: None) -> None:
        """Only the hash is stored; the plain provisional token is not (R9)."""
        output = run_command("enfermeira.duda", "--full-name", "Duda Lima")
        token = assert_token_printed_once(output)

        user = User.objects.get(username="enfermeira.duda")
        assert token not in user.password
        assert user.check_password(token)
        assert user.has_usable_password()


# ── R7: reset mode ───────────────────────────────────────────────


class TestResetPasswordMode:
    def test_reset_password_reissues_and_reflags(
        self, client: Client, db: None
    ) -> None:
        """Reset reissues a provisional password and re-arms the flag."""
        first = run_command("operador", "--full-name", "Maria Silva")
        old_token = assert_token_printed_once(first)

        # Simulate a completed forced change: new password, flag cleared.
        user = User.objects.get(username="operador")
        user.set_password("SenhaTrocada#42")
        user.save(update_fields=["password"])
        user.profile.must_change_password = False
        user.profile.save(update_fields=["must_change_password"])
        assert not user.profile.must_change_password

        output = run_command("--reset-password", "operador")
        new_token = assert_token_printed_once(output)
        assert new_token != old_token

        user.refresh_from_db()
        assert user.profile.must_change_password is True
        assert user.check_password(new_token)
        assert not user.check_password(old_token)

        # The reissued password forces the change again.
        client.login(username="operador", password=new_token)
        resp = client.get("/painel/")
        assert resp.status_code == 302
        assert resp["Location"] == "/perfil/"

    def test_reset_password_unknown_user_fails_clearly(
        self, client: Client, db: None
    ) -> None:
        """Resetting an unknown username fails with a clear error."""
        out = StringIO()
        with pytest.raises(CommandError) as excinfo:
            call_command(COMMAND, "--reset-password", "nao-existe", stdout=out)
        assert "nao-existe" in str(excinfo.value)
        assert "não encontrado" in str(excinfo.value)
        assert User.objects.filter(username="nao-existe").exists() is False
