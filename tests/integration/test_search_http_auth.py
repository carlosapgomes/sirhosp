"""Integration tests for search view authentication (Slice S4)."""

from __future__ import annotations

import pytest
from django.test import Client


@pytest.mark.django_db
class TestSearchAnonymousRedirect:
    """Anonymous users must be redirected to login for search endpoint."""

    def test_anonymous_search_redirects_to_login(self, client: Client) -> None:
        """GET /search/clinical-events/ without auth redirects to LOGIN_URL."""
        url = "/search/clinical-events/?q=test"
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]
        assert "next=" in response.url  # type: ignore[attr-defined]

    def test_authenticated_search_returns_json(self, client: Client) -> None:
        """Authenticated GET /search/clinical-events/ returns 200 (even if no results)."""
        from django.contrib.auth.models import User

        User.objects.create_user(username="searchuser", password="testpass123")
        client.login(username="searchuser", password="testpass123")

        url = "/search/clinical-events/?q=test"
        response = client.get(url)
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
