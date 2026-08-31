"""Patient flow snapshot contract (PFIF-S1, D1/D3).

Pure, immutable value object describing the result of an admissions capture
that may have been enriched by a read-only ``Atendimentos`` lookup. The
contract carries ONLY structural data: normalized admissions, the latest
structurally valid encounter date and a closed recency bucket.

It never carries patient/professional names, row text, type, specialty,
HTML, URLs or cookies. The recency calculation is pure and receives an
injectable ``today`` so tests and callers control the local calendar
(``America/Bahia`` in production).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping


class EncounterRecency(enum.Enum):
    """Closed recency buckets for date-only encounter evidence (D3)."""

    RECENT_CONFIRMED = "recent_confirmed"
    BOUNDARY = "boundary"
    STALE = "stale"
    NONE = "none"


OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION = "recent_encounter_without_admission"
"""Closed operational outcome for a recognized recent encounter."""


def classify_encounter_recency(
    latest_encounter_date: date | None, *, today: date
) -> EncounterRecency:
    """Classify a latest encounter date against the local calendar.

    Conservative buckets (D3): today/yesterday is ``recent_confirmed``;
    the day before yesterday is ``boundary`` (ambiguous 48h window, never
    accepted automatically); three or more days back is ``stale``; no valid
    date is ``none``. A future date is invalid evidence and is classified
    ``none`` — it is never recent.
    """
    if latest_encounter_date is None:
        return EncounterRecency.NONE
    delta_days = (today - latest_encounter_date).days
    if delta_days < 0:
        # Future dates are structurally invalid evidence, never recent.
        return EncounterRecency.NONE
    if delta_days <= 1:
        return EncounterRecency.RECENT_CONFIRMED
    if delta_days == 2:
        return EncounterRecency.BOUNDARY
    return EncounterRecency.STALE


@dataclass(frozen=True)
class PatientFlowSnapshot:
    """Immutable result of an admissions capture with optional enrichment.

    Attributes:
        admissions: Normalized admissions snapshot (possibly empty).
        latest_encounter_date: Latest structurally valid encounter date,
            or ``None`` when no valid date was found.
        encounter_recency: Closed recency bucket computed against the
            injected local ``today``.
    """

    admissions: tuple[dict[str, Any], ...]
    latest_encounter_date: date | None
    encounter_recency: EncounterRecency

    @classmethod
    def build(
        cls,
        *,
        admissions: Iterable[Mapping[str, Any]],
        encounter_dates: Iterable[date | None],
        today: date,
    ) -> "PatientFlowSnapshot":
        """Build the snapshot from raw pieces.

        Normalizes admissions into an immutable tuple, picks the latest
        valid encounter date deterministically (``max``) and classifies its
        recency against ``today``.
        """
        valid_dates = [d for d in encounter_dates if d is not None]
        latest = max(valid_dates) if valid_dates else None
        return cls(
            admissions=tuple(dict(a) for a in admissions),
            latest_encounter_date=latest,
            encounter_recency=classify_encounter_recency(latest, today=today),
        )

    @property
    def is_empty(self) -> bool:
        """True when the normalized admissions list is empty."""
        return not self.admissions

    @property
    def has_recent_encounter(self) -> bool:
        """True only when recency is ``recent_confirmed``."""
        return self.encounter_recency is EncounterRecency.RECENT_CONFIRMED
