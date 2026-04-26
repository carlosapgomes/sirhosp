"""Slice IRMD-S6: Ingestion metrics page route tests."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
class TestIngestionMetricsRoute:
    """S6: Ingestion metrics route authentication and rendering."""

    def test_ingestion_metrics_authenticated(self, admin_client):
        """Authenticated user receives 200 on the ingestion metrics page."""
        url = reverse("services_portal:ingestion_metrics")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert "Ingestão" in response.content.decode()

    def test_ingestion_metrics_anonymous_redirects_to_login(self):
        """Anonymous user is redirected to login page."""
        client = Client()
        url = reverse("services_portal:ingestion_metrics")
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith("/login")
