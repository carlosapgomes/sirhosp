"""Versioned origin classification policy of detected entries (DSRS-S3).

The census row of a patient carries an origin value (``CensusSnapshot.origem``,
the origin sector/bed code of the last movement). Classifying an entry as a
hospital admission or as an internal transfer depends only on that value, so the
mapping from normalized source values or codes to :class:`OriginNature` is
declared as data and versioned:

- ``external`` values are origins outside the hospital;
- ``hospital_internal`` values are hospital origins, monitored or not
  (emergency, operating room, unmonitored wards);
- every other value stays unclassified, so an entry with an unknown or
  contradictory origin is never silently turned into an admission.

The exact real source values are only characterized with operational evidence
before activation; until then the declared policy classifies nothing and every
entry fails closed into ``unclassified_entry``. The mapping is supplied as
data (:class:`OriginPolicy`), never as ad hoc string checks in views, templates
or derivative modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import models


class OriginPolicyError(Exception):
    """A declared origin policy cannot classify origins unambiguously."""


ORIGIN_POLICY_VERSION = "admission-origin-v1"
"""Version of the declared origin mapping; bump it whenever values change."""


class OriginNature(models.TextChoices):
    """Institutional nature of an entry origin."""

    EXTERNAL = "external", "Externa ao hospital"
    HOSPITAL_INTERNAL = "hospital_internal", "Interna ao hospital"
    UNKNOWN = "unknown", "Não identificada"


def normalize_origin_value(value: str) -> str:
    """Normalized comparison form of one source origin value.

    Strips, uppercases and collapses inner whitespace so the declared mapping
    and the observed values compare by one single spelling.
    """
    return " ".join(value.split()).upper()


@dataclass(frozen=True)
class OriginPolicy:
    """Declared mapping of normalized origin values to their nature.

    Attributes:
        version: Auditable version of this mapping, stored with every event
            that used it so a classification can be reproduced.
        external: Normalized values that identify an origin outside the
            hospital.
        hospital_internal: Normalized values that identify a hospital origin,
            monitored or not.

    Raises:
        OriginPolicyError: When the version is empty, a value is declared in
            both natures or a declared value is not in normalized form.
    """

    version: str
    external: frozenset[str] = field(default_factory=frozenset)
    hospital_internal: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise OriginPolicyError("An origin policy requires a version.")
        conflicting = self.external & self.hospital_internal
        if conflicting:
            raise OriginPolicyError(
                "Origin values cannot be external and hospital-internal at "
                f"once: {', '.join(sorted(conflicting))}."
            )
        for value in self.external | self.hospital_internal:
            if normalize_origin_value(value) != value:
                raise OriginPolicyError(
                    f"Origin value {value!r} must be declared in normalized "
                    "form."
                )

    def classify(self, value: str) -> OriginNature | None:
        """Nature of one observed origin value, or ``None`` if unclassified.

        ``None`` means the policy does not recognize the value, which keeps the
        entry explicit instead of inferring an external origin.
        """
        normalized = normalize_origin_value(value)
        if not normalized:
            return None
        if normalized in self.external:
            return OriginNature.EXTERNAL
        if normalized in self.hospital_internal:
            return OriginNature.HOSPITAL_INTERNAL
        return None


DEFAULT_ORIGIN_POLICY = OriginPolicy(version=ORIGIN_POLICY_VERSION)
"""Declared policy in force until real source values are characterized.

It classifies no value on purpose: the operational characterization of
emergency, operating room, monitored and unmonitored ward values must be
recorded here (or injected as another :class:`OriginPolicy`) before activation.
"""
