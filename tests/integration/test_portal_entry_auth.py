"""Integration tests for portal entry, login, logout and post-login redirect.

Slice S1 — Entrada autenticada (landing + login + redirect).
"""

import pytest
from django.contrib.auth.models import User
from django.test import Client


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
    )


# ── Landing ──────────────────────────────────────────────────────


class TestLandingPage:
    def test_landing_is_public(self, client: Client) -> None:
        """Anonymous user can access the landing page."""
        resp = client.get("/")
        assert resp.status_code == 200

    def test_landing_has_login_cta(self, client: Client) -> None:
        """Landing contains a visible CTA pointing to /login/."""
        resp = client.get("/")
        content = resp.content.decode()
        assert "/login/" in content


# ── Login ────────────────────────────────────────────────────────


class TestLoginRoute:
    def test_login_page_renders(self, client: Client) -> None:
        """GET /login/ renders a login form."""
        resp = client.get("/login/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "username" in content.lower()

    def test_login_success_redirects_to_patients(
        self,
        client: Client,
        registered_user: User,
        user_password: str,
    ) -> None:
        """Successful login redirects to /patients/."""
        resp = client.post(
            "/login/",
            {"username": "operador", "password": user_password},
        )
        assert resp.status_code == 302
        assert resp["Location"] == "/patients/"


# ── Logout ───────────────────────────────────────────────────────


class TestLogoutRoute:
    def test_logout_redirects_to_landing(
        self,
        client: Client,
        registered_user: User,
        user_password: str,
    ) -> None:
        """Logout redirects to the landing page."""
        client.login(username="operador", password=user_password)
        resp = client.post("/logout/")
        assert resp.status_code == 302
        # LOGOUT_REDIRECT_URL should point to "/"
        assert resp["Location"] == "/"
