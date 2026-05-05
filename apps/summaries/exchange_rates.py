"""Exchange rate helpers — USD/BRL conversion for cost display (STP-S4, STP-S8).

Provides:
    get_latest_rate() -> Optional[Decimal]
        Returns the most recent USD/BRL rate available in the database.
    usd_to_brl(usd_amount: Decimal | None) -> str
        Convert a USD amount to a BRL display string using the latest rate.
        Returns "---" when rate is unavailable.
    format_brl_with_rate(usd_amount: Decimal | None, rate: Decimal | None) -> str
        Convert a USD amount to a BRL display string using a pre-loaded rate.
        Use this to avoid repeated DB queries when formatting many amounts.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from apps.summaries.models import ExchangeRateSnapshot


def get_latest_rate() -> Optional[Decimal]:
    """Return the most recent USD/BRL rate, or None if no snapshot exists."""
    snapshot = (
        ExchangeRateSnapshot.objects.filter(
            base_currency="USD",
            quote_currency="BRL",
        )
        .order_by("-reference_date")
        .first()
    )
    if snapshot is None:
        return None
    return snapshot.rate


def _fmt_brl(amount: Decimal) -> str:
    """Format a Decimal as Brazilian currency string (R$ X.XXX,XX)."""
    brl = amount.quantize(Decimal("0.01"))
    return f"R$ {brl:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_brl_with_rate(
    usd_amount: Decimal | None,
    rate: Decimal | None,
) -> str:
    """Convert USD amount to BRL using a pre-loaded rate.

    Use this when formatting many amounts in a single request to avoid
    repeated DB lookups in get_latest_rate().

    Returns "---" when amount or rate is None.
    """
    if usd_amount is None or rate is None:
        return "---"
    return _fmt_brl(usd_amount * rate)


def usd_to_brl(usd_amount: Decimal | None) -> str:
    """Convert a USD decimal to a BRL display string using the latest rate.

    Returns "---" when either the amount is None or no rate is available.
    The output is formatted with Brazilian locale (R$ X.XXX,XX).
    """
    if usd_amount is None:
        return "---"
    rate = get_latest_rate()
    return format_brl_with_rate(usd_amount, rate)
