"""Integration tests for the portal profile page and self-service password
change (SLICE-AUP-S1).

``/perfil/`` shows the authenticated user's read-only identity and a
password-change form built on ``django.contrib.auth.forms.PasswordChangeForm``.
A successful change keeps the current session alive
(``update_session_auth_hash``) and redirects back to the profile (PRG).
"""

import pytest
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from apps.accounts.models import UserProfile

NEW_PASSWORD = "NovaSenhaSegura#42"


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def user_password() -> str:
    return "testpass123"


@pytest.fixture
def registered_user(db: None, user_password: str) -> User:
    return User.objects.create_user(
        username="operador",
        password=user_password,
        first_name="Maria",
        last_name="Silva",
        email="maria.silva@example.com",
    )


# ── R1: anonymous redirect ───────────────────────────────────────


class TestAnonymousAccess:
    def test_anonymous_profile_redirects_to_login(self, client: Client) -> None:
        """Anonymous GET /perfil/ redirects to /login/ with next."""
        resp = client.get("/perfil/")
        assert resp.status_code == 302
        assert resp["Location"] == "/login/?next=/perfil/"


# ── R2: read-only identity ───────────────────────────────────────


class TestProfileIdentity:
    def test_profile_shows_own_identity_readonly(
        self,
        client: Client,
        registered_user: User,
        user_password: str,
    ) -> None:
        """Authenticated profile shows own identity and only password inputs."""
        assert client.login(username="operador", password=user_password)
        registered_user.refresh_from_db()

        resp = client.get("/perfil/")
        assert resp.status_code == 200
        content = resp.content.decode()

        assert "operador" in content
        assert "Maria Silva" in content
        assert "maria.silva@example.com" in content
        assert "usuário comum" in content
        last_login = timezone.localtime(registered_user.last_login).strftime(
            "%d/%m/%Y %H:%M"
        )
        assert last_login in content

        # Identity fields are read-only: the only editable inputs belong to
        # the password-change form.
        assert 'name="old_password"' in content
        assert 'name="new_password1"' in content
        assert 'name="new_password2"' in content
        assert 'name="username"' not in content
        assert 'name="email"' not in content
        assert 'name="first_name"' not in content
        assert 'name="last_name"' not in content


# ── R3: wrong current password ───────────────────────────────────


class TestWrongCurrentPassword:
    def test_wrong_current_password_is_rejected(
        self,
        client: Client,
        registered_user: User,
        user_password: str,
    ) -> None:
        """Wrong current password re-renders with field error, password intact."""
        assert client.login(username="operador", password=user_password)
        payload = {
            "old_password": "senha-atual-errada",
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        }

        invalid = PasswordChangeForm(user=registered_user, data=payload)
        assert not invalid.is_valid()
        expected_errors = list(invalid["old_password"].errors)
        assert expected_errors

        resp = client.post("/perfil/", payload)
        assert resp.status_code == 200
        content = resp.content.decode()
        for error in expected_errors:
            assert str(error) in content

        registered_user.refresh_from_db()
        assert registered_user.check_password(user_password)
        assert not registered_user.check_password(NEW_PASSWORD)


# ── R4: successful change ────────────────────────────────────────


class TestSuccessfulChange:
    def test_successful_change_keeps_session_and_new_password_works(
        self,
        client: Client,
        registered_user: User,
        user_password: str,
    ) -> None:
        """Valid change redirects (PRG), session survives, new password works."""
        assert client.login(username="operador", password=user_password)
        resp = client.post(
            "/perfil/",
            {
                "old_password": user_password,
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )
        assert resp.status_code == 302
        assert resp["Location"] == "/perfil/"

        # Current session remains authenticated without a re-login.
        page = client.get("/perfil/")
        assert page.status_code == 200

        # The new password authenticates in a fresh login.
        client.logout()
        assert client.login(username="operador", password=NEW_PASSWORD)

        # The old password no longer authenticates.
        client.logout()
        assert not client.login(username="operador", password=user_password)


# ── R5: weak new password ────────────────────────────────────────


class TestWeakNewPassword:
    def test_weak_new_password_is_rejected(
        self,
        client: Client,
        registered_user: User,
        user_password: str,
    ) -> None:
        """Weak new password is rejected by the validators, password intact."""
        assert client.login(username="operador", password=user_password)
        payload = {
            "old_password": user_password,
            "new_password1": "abc123",
            "new_password2": "abc123",
        }

        invalid = PasswordChangeForm(user=registered_user, data=payload)
        assert not invalid.is_valid()
        expected_errors = list(invalid["new_password2"].errors)
        assert expected_errors

        resp = client.post("/perfil/", payload)
        assert resp.status_code == 200
        content = resp.content.decode()
        for error in expected_errors:
            assert str(error) in content

        registered_user.refresh_from_db()
        assert registered_user.check_password(user_password)
        assert not registered_user.check_password("abc123")


class TestForcedPasswordChange:
    def test_password_change_clears_flag_and_releases_portal(
        self,
        client: Client,
        db: None,
        user_password: str,
    ) -> None:
        """A successful change clears must_change_password and releases the
        portal for a flagged user (R4)."""
        flagged = User.objects.create_user(
            username="operador",
            password=user_password,
            first_name="Maria",
            last_name="Silva",
        )
        UserProfile.objects.create(user=flagged, must_change_password=True)
        assert client.login(username="operador", password=user_password)

        # Flag active: the portal is blocked by the middleware.
        resp = client.get("/painel/")
        assert resp.status_code == 302
        assert resp["Location"] == "/perfil/"

        # Successful change on /perfil/ clears the flag.
        resp = client.post(
            "/perfil/",
            {
                "old_password": user_password,
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )
        assert resp.status_code == 302
        assert resp["Location"] == "/perfil/"

        profile = flagged.profile
        profile.refresh_from_db()
        assert profile.must_change_password is False

        # Portal released: /painel/ answers normally now.
        resp = client.get("/painel/")
        assert resp.status_code == 200


# ── R6: success message and sidebar link ─────────────────────────


class TestSuccessMessage:
    def test_success_message_is_shown(
        self,
        client: Client,
        registered_user: User,
        user_password: str,
    ) -> None:
        """A friendly success message appears after the PRG redirect."""
        assert client.login(username="operador", password=user_password)
        resp = client.post(
            "/perfil/",
            {
                "old_password": user_password,
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )
        assert resp.status_code == 302

        page = client.get(resp["Location"])
        assert page.status_code == 200
        assert "Senha alterada com sucesso." in page.content.decode()


class TestSidebarProfileLink:
    def test_sidebar_links_to_profile(
        self,
        client: Client,
        registered_user: User,
        user_password: str,
    ) -> None:
        """The authenticated sidebar contains a Perfil link to /perfil/."""
        assert client.login(username="operador", password=user_password)
        resp = client.get("/perfil/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'href="/perfil/"' in content
        assert "Perfil" in content
