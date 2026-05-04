"""Exchange rate helpers — USD/BRL conversion for cost display (STP-S4).

Provides:
    get_latest_rate() -> Optional[Decimal]
        Returns the most recent USD/BRL rate available in the database.
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
