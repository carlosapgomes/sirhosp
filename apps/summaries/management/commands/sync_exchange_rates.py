"""Daily USD/BRL exchange rate sync (STP-S4).

Fetches the current USD/BRL rate from a primary provider (frankfurter.dev,
no API key) with fallback to exchangerate-api.com (requires API key).

Usage:
    python manage.py sync_exchange_rates

Environment variables:
    SUMMARY_EXCHANGE_PRIMARY_URL      Primary endpoint (default: frankfurter.dev)
    SUMMARY_EXCHANGE_FALLBACK_URL     Fallback endpoint (default: exchangerate-api.com)
    SUMMARY_EXCHANGE_FALLBACK_API_KEY API key for fallback (optional; if missing,
                                      fallback is skipped)
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import Optional, Tuple

import httpx
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from apps.summaries.models import ExchangeRateSnapshot

# ---------------------------------------------------------------------------
# Default endpoints
# ---------------------------------------------------------------------------

_DEFAULT_PRIMARY_URL = "https://api.frankfurter.dev/latest?from=USD&to=BRL"
_DEFAULT_FALLBACK_URL = "https://v6.exchangerate-api.com/v6/{api_key}/latest/USD"


def _fetch_from_frankfurter(url: str) -> Tuple[Optional[Decimal], Optional[date]]:
    """Fetch USD/BRL rate from frankfurter.dev (no API key).

    Returns (rate, reference_date) on success, or (None, None) on failure.
    """
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            rate_val = data["rates"]["BRL"]
            ref_date = date.fromisoformat(data["date"])
            return Decimal(str(rate_val)), ref_date
    except Exception:
        return None, None


def _fetch_from_exchangerate_api(url: str) -> Tuple[Optional[Decimal], Optional[date]]:
    """Fetch USD/BRL rate from exchangerate-api.com (API key required).

    Returns (rate, reference_date) on success, or (None, None) on failure.
    """
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            if data.get("result") != "success":
                return None, None
            rate_val = data["rates"]["BRL"]
            # exchangerate-api doesn't return a date per-rate in the free tier
            # response, so we use today's date as reference.
            ref_date = django_timezone.now().date()
            return Decimal(str(rate_val)), ref_date
    except Exception:
        return None, None


class Command(BaseCommand):
    help = "Fetch daily USD/BRL exchange rate (primary + optional fallback)."

    def handle(self, *args, **options):
        primary_url = os.getenv(
            "SUMMARY_EXCHANGE_PRIMARY_URL", _DEFAULT_PRIMARY_URL
        )
        fallback_api_key = os.getenv(
            "SUMMARY_EXCHANGE_FALLBACK_API_KEY", ""
        ).strip()

        rate: Optional[Decimal] = None
        ref_date: Optional[date] = None
        provider: str = ""

        # ── 1. Primary — frankfurter.dev (no API key) ──────────────────
        self.stdout.write("Fetching USD/BRL from primary provider...")
        rate, ref_date = _fetch_from_frankfurter(primary_url)
        if rate is not None and ref_date is not None:
            provider = "frankfurter"
            self.stdout.write(
                self.style.SUCCESS(
                    f"Primary OK: {rate} on {ref_date} ({provider})"
                )
            )

        # ── 2. Fallback — exchangerate-api.com (requires API key) ──────
        if rate is None and fallback_api_key:
            fallback_url_template = os.getenv(
                "SUMMARY_EXCHANGE_FALLBACK_URL", _DEFAULT_FALLBACK_URL
            )
            fallback_url = fallback_url_template.format(api_key=fallback_api_key)

            self.stdout.write("Primary failed. Attempting fallback...")
            rate, ref_date = _fetch_from_exchangerate_api(fallback_url)
            if rate is not None and ref_date is not None:
                provider = "exchangerate_api"
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Fallback OK: {rate} on {ref_date} ({provider})"
                    )
                )

        # ── 3. Persist ─────────────────────────────────────────────────
        if rate is not None and ref_date is not None:
            ExchangeRateSnapshot.objects.update_or_create(
                base_currency="USD",
                quote_currency="BRL",
                reference_date=ref_date,
                defaults={
                    "rate": rate,
                    "provider": provider,
                    "fetched_at": django_timezone.now(),
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Exchange rate persisted: {rate} on {ref_date} ({provider})"
                )
            )
        else:
            if not fallback_api_key:
                self.stdout.write(
                    self.style.WARNING(
                        "Primary failed and SUMMARY_EXCHANGE_FALLBACK_API_KEY "
                        "is not configured. No rate persisted."
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        "Both primary and fallback providers failed. "
                        "No rate persisted."
                    )
                )
