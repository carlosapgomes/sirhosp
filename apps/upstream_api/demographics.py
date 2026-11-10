"""Patient demographics resolution and serialization (design D4).

The lookup is restricted to ``source_system "tasy"``, the only source the
pipeline writes, so a prontuario that exists only in another source is never
served. Values are mirrored verbatim: ``""`` stays ``""``, ``NULL`` stays
``null`` and ``gender`` keeps its free Portuguese text, because normalization
belongs to the consumer (contract v2). Exactly the 19 allowlisted top-level
keys are emitted; model internals (``id``, ``source_system``, ``created_at``)
never surface.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.patients.models import Patient

SOURCE_SYSTEM = "tasy"


def find_patient(prontuario: str) -> Patient | None:
    """Patient mirrored from TASY under this prontuario, or ``None``."""
    return Patient.objects.filter(
        source_system=SOURCE_SYSTEM,
        patient_source_key=prontuario,
    ).first()


def _civil_date(value: date | None) -> str | None:
    """``YYYY-MM-DD`` for a civil date; ``null`` stays ``null``."""
    return value.isoformat() if value is not None else None


def serialize_patient(patient: Patient, prontuario: str) -> dict[str, Any]:
    """The demographics wire shape, mirrored without business transformation."""
    return {
        "prontuario": prontuario,
        "name": patient.name,
        "social_name": patient.social_name,
        "date_of_birth": _civil_date(patient.date_of_birth),
        "gender": patient.gender,
        "gender_identity": patient.gender_identity,
        "mother_name": patient.mother_name,
        "father_name": patient.father_name,
        "race_color": patient.race_color,
        "birthplace": patient.birthplace,
        "nationality": patient.nationality,
        "marital_status": patient.marital_status,
        "education_level": patient.education_level,
        "profession": patient.profession,
        "cns": patient.cns,
        "cpf": patient.cpf,
        "phones": {
            "home": patient.phone_home,
            "cellular": patient.phone_cellular,
            "contact": patient.phone_contact,
        },
        "address": {
            "street": patient.street,
            "number": patient.address_number,
            "complement": patient.address_complement,
            "neighborhood": patient.neighborhood,
            "city": patient.city,
            "state": patient.state,
            "postal_code": patient.postal_code,
        },
        "updated_at": patient.updated_at.isoformat(),
    }


def build_patient_demographics(prontuario: str) -> dict[str, Any] | None:
    """Wire payload for one prontuario, or ``None`` when TASY has no such patient."""
    patient = find_patient(prontuario)
    if patient is None:
        return None
    return serialize_patient(patient, prontuario)
