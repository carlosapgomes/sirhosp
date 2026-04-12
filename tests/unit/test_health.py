import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_endpoint_returns_ok() -> None:
    client = Client()
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "sirhosp"}
