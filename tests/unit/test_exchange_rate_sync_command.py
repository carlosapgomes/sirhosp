"""Tests for sync_exchange_rates command and exchange rate helpers (STP-S4).

TDD: tests first (RED), then implement (GREEN), then refactor.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from apps.summaries.models import ExchangeRateSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_primary_response(rate: float = 5.72) -> dict:
    return {
        "amount": 1.0,
        "base": "USD",
        "date": "2026-05-03",
        "rates": {"BRL": rate},
    }


def _make_fallback_response(rate: float = 5.72) -> dict:
    return {
        "result": "success",
        "base_code": "USD",
        "rates": {"BRL": rate},
    }


def _mock_httpx_get_success(mock_client_cls, response_dict, status=200):
    """Configure mocked httpx.Client to return a successful JSON response."""
    mock_instance = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.json.return_value = response_dict
    mock_response.text = json.dumps(response_dict)
    mock_instance.get.return_value = mock_response
    mock_client_cls.return_value.__enter__.return_value = mock_instance
    return mock_instance


def _mock_httpx_get_failure(mock_client_cls, status=500, text="Internal Server Error"):
    """Configure mocked httpx.Client to return an error response."""
    mock_instance = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.text = text
    mock_response.raise_for_status.side_effect = Exception(f"HTTP {status}")
    mock_instance.get.return_value = mock_response
    mock_client_cls.return_value.__enter__.return_value = mock_instance
    return mock_instance


# ---------------------------------------------------------------------------
# sync_exchange_rates command
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncExchangeRatesPrimary:
    """Tests for primary source (frankfurter.dev — no API key)."""

    @patch("httpx.Client")
    def test_primary_source_success_creates_snapshot(self, mock_client_cls):
        """Command fetches from primary source and creates ExchangeRateSnapshot."""
        _mock_httpx_get_success(mock_client_cls, _make_primary_response(5.72))

        call_command("sync_exchange_rates")

        snapshots = ExchangeRateSnapshot.objects.all()
        assert snapshots.count() == 1
        snap = snapshots[0]
        assert snap.base_currency == "USD"
        assert snap.quote_currency == "BRL"
        assert snap.rate == Decimal("5.72")
        assert snap.reference_date == date(2026, 5, 3)
        assert snap.provider == "frankfurter"

    @patch("httpx.Client")
    def test_primary_source_success_upserts_same_date(self, mock_client_cls):
        """Second sync on the same day updates the existing snapshot."""
        _mock_httpx_get_success(mock_client_cls, _make_primary_response(5.50))
        call_command("sync_exchange_rates")

        # Second call — new rate for same date
        _mock_httpx_get_success(mock_client_cls, _make_primary_response(5.72))
        call_command("sync_exchange_rates")

        snapshots = ExchangeRateSnapshot.objects.filter(reference_date=date(2026, 5, 3))
        assert snapshots.count() == 1
        assert snapshots[0].rate == Decimal("5.72")

    @patch("httpx.Client")
    def test_different_dates_create_separate_snapshots(self, mock_client_cls):
        """Two different dates produce two snapshots (retention)."""
        _mock_httpx_get_success(
            mock_client_cls,
            {"amount": 1.0, "base": "USD", "date": "2026-05-01", "rates": {"BRL": 5.50}},
        )
        call_command("sync_exchange_rates")

        _mock_httpx_get_success(
            mock_client_cls,
            {"amount": 1.0, "base": "USD", "date": "2026-05-03", "rates": {"BRL": 5.72}},
        )
        call_command("sync_exchange_rates")

        snapshots = ExchangeRateSnapshot.objects.order_by("reference_date")
        assert snapshots.count() == 2
        assert snapshots[0].rate == Decimal("5.50")
        assert snapshots[1].rate == Decimal("5.72")


@pytest.mark.django_db
class TestSyncExchangeRatesFallback:
    """Tests for fallback source (exchangerate-api.com — requires API key)."""

    @patch("httpx.Client")
    @patch.dict("os.environ", {"SUMMARY_EXCHANGE_FALLBACK_API_KEY": "test-fallback-key"})
    def test_fallback_used_when_primary_fails(self, mock_client_cls):
        """When primary fails and fallback API key is configured, fallback is used."""
        # First call (primary) fails, second call (fallback) succeeds
        mock_instance = MagicMock()

        fail_response = MagicMock()
        fail_response.status_code = 503
        fail_response.text = "Service Unavailable"
        fail_response.raise_for_status.side_effect = Exception("HTTP 503")

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = _make_fallback_response(5.72)
        success_response.text = json.dumps(_make_fallback_response(5.72))

        mock_instance.get.side_effect = [fail_response, success_response]
        mock_client_cls.return_value.__enter__.return_value = mock_instance

        call_command("sync_exchange_rates")

        snapshots = ExchangeRateSnapshot.objects.all()
        assert snapshots.count() == 1
        assert snapshots[0].rate == Decimal("5.72")
        assert snapshots[0].provider == "exchangerate_api"

    @patch("httpx.Client")
    def test_fallback_skipped_when_api_key_missing(self, mock_client_cls):
        """When primary fails and fallback API key is not configured, command exits gracefully."""
        mock_instance = MagicMock()
        fail_response = MagicMock()
        fail_response.status_code = 503
        fail_response.text = "Service Unavailable"
        fail_response.raise_for_status.side_effect = Exception("HTTP 503")
        mock_instance.get.return_value = fail_response
        mock_client_cls.return_value.__enter__.return_value = mock_instance

        # Ensure no fallback API key in env
        with patch.dict("os.environ", {}, clear=False):
            # Remove the key if present
            import os
            orig = os.environ.pop("SUMMARY_EXCHANGE_FALLBACK_API_KEY", None)
            try:
                call_command("sync_exchange_rates")
            finally:
                if orig is not None:
                    os.environ["SUMMARY_EXCHANGE_FALLBACK_API_KEY"] = orig

        snapshots = ExchangeRateSnapshot.objects.all()
        assert snapshots.count() == 0

    @patch("httpx.Client")
    @patch.dict("os.environ", {"SUMMARY_EXCHANGE_FALLBACK_API_KEY": "test-fallback-key"})
    def test_both_providers_fail_no_snapshot_created(self, mock_client_cls):
        """When both primary and fallback fail, no snapshot is created."""
        _mock_httpx_get_failure(mock_client_cls, status=503, text="Both down")

        call_command("sync_exchange_rates")

        assert ExchangeRateSnapshot.objects.count() == 0


# ---------------------------------------------------------------------------
# Retention policy
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExchangeRateRetention:
    """Tests for retention of at least 2 latest valid rates."""

    @patch("httpx.Client")
    def test_retain_at_least_two_latest_rates(self, mock_client_cls):
        """After syncing 3 different dates, at least the 2 latest remain."""
        dates_responses = [
            ("2026-05-01", 5.50),
            ("2026-05-02", 5.60),
            ("2026-05-03", 5.72),
        ]

        for ref_date, rate_val in dates_responses:
            _mock_httpx_get_success(
                mock_client_cls,
                {
                    "amount": 1.0,
                    "base": "USD",
                    "date": ref_date,
                    "rates": {"BRL": rate_val},
                },
            )
            call_command("sync_exchange_rates")

        snapshots = ExchangeRateSnapshot.objects.order_by("reference_date")
        # The command retains all snapshots (purge policy not yet enforced in
        # MVP); the spec requires at least 2 latest be available.
        assert snapshots.count() == 3
        # The two most recent should be correct
        latest_two = list(ExchangeRateSnapshot.objects.order_by("-reference_date")[:2])
        assert len(latest_two) == 2
        assert latest_two[0].rate == Decimal(f"{dates_responses[2][1]:.2f}")
        assert latest_two[1].rate == Decimal(f"{dates_responses[1][1]:.2f}")


# ---------------------------------------------------------------------------
# get_latest_rate helper
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetLatestRate:
    """Tests for exchange_rates.get_latest_rate() helper."""

    def test_returns_latest_rate_when_multiple_exist(self):
        """Returns the rate with the most recent reference_date."""
        ExchangeRateSnapshot.objects.create(
            base_currency="USD",
            quote_currency="BRL",
            rate=Decimal("5.50"),
            reference_date=date(2026, 5, 1),
            provider="frankfurter",
            fetched_at=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        )
        ExchangeRateSnapshot.objects.create(
            base_currency="USD",
            quote_currency="BRL",
            rate=Decimal("5.72"),
            reference_date=date(2026, 5, 3),
            provider="frankfurter",
            fetched_at=datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc),
        )

        from apps.summaries.exchange_rates import get_latest_rate

        rate = get_latest_rate()
        assert rate == Decimal("5.72")

    def test_returns_none_when_no_snapshots_exist(self):
        """Returns None when no exchange rate data is available."""
        from apps.summaries.exchange_rates import get_latest_rate

        rate = get_latest_rate()
        assert rate is None
