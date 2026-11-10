"""Unit evidence for slice UPA-002 R1, R2 and R4.

The demographics serialization is asserted without the database: the mapping
is pure and must mirror the D4 wire table verbatim with exactly the 19
allowlisted top-level keys. The reuse checks prove the new view shares the
UPA-001 auth, envelope and no-store helpers instead of duplicating them.

Synthetic values only.
"""

from __future__ import annotations

import inspect
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from apps.patients.models import Patient
from apps.upstream_api import views
from apps.upstream_api.demographics import serialize_patient

BAHIA = ZoneInfo("America/Bahia")
UPDATED_AT = datetime(2026, 9, 6, 8, 0, tzinfo=BAHIA)

DEMOGRAPHICS_KEYS = {
    "prontuario",
    "name",
    "social_name",
    "date_of_birth",
    "gender",
    "gender_identity",
    "mother_name",
    "father_name",
    "race_color",
    "birthplace",
    "nationality",
    "marital_status",
    "education_level",
    "profession",
    "cns",
    "cpf",
    "phones",
    "address",
    "updated_at",
}

ISO_WITH_OFFSET = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})"
)


def _patient(**overrides) -> Patient:
    values = {
        "name": "PACIENTE EXEMPLO",
        "social_name": "NOME SOCIAL EXEMPLO",
        "date_of_birth": date(1980, 3, 17),
        "gender": "Masculino",
        "gender_identity": "Cisgenero",
        "mother_name": "MAE EXEMPLO",
        "father_name": "PAI EXEMPLO",
        "race_color": "Parda",
        "birthplace": "Salvador",
        "nationality": "Brasileira",
        "marital_status": "Solteiro",
        "education_level": "Superior completo",
        "profession": "Analista",
        "cns": "898000000000000",
        "cpf": "00000000000",
        "phone_home": "7133334444",
        "phone_cellular": "71999998888",
        "phone_contact": "7132221111",
        "street": "RUA EXEMPLO",
        "address_number": "100",
        "address_complement": "APTO 12",
        "neighborhood": "CENTRO",
        "city": "SALVADOR",
        "state": "BA",
        "postal_code": "40000000",
        "updated_at": UPDATED_AT,
    }
    values.update(overrides)
    return Patient(**values)


def test_serialize_patient_emits_exactly_the_allowlisted_keys():
    payload = serialize_patient(_patient(), "0000001")

    assert set(payload) == DEMOGRAPHICS_KEYS
    assert set(payload["phones"]) == {"home", "cellular", "contact"}
    assert set(payload["address"]) == {
        "street",
        "number",
        "complement",
        "neighborhood",
        "city",
        "state",
        "postal_code",
    }


def test_serialize_patient_maps_every_column_verbatim():
    payload = serialize_patient(_patient(), "0000001")

    assert payload == {
        "prontuario": "0000001",
        "name": "PACIENTE EXEMPLO",
        "social_name": "NOME SOCIAL EXEMPLO",
        "date_of_birth": "1980-03-17",
        "gender": "Masculino",
        "gender_identity": "Cisgenero",
        "mother_name": "MAE EXEMPLO",
        "father_name": "PAI EXEMPLO",
        "race_color": "Parda",
        "birthplace": "Salvador",
        "nationality": "Brasileira",
        "marital_status": "Solteiro",
        "education_level": "Superior completo",
        "profession": "Analista",
        "cns": "898000000000000",
        "cpf": "00000000000",
        "phones": {
            "home": "7133334444",
            "cellular": "71999998888",
            "contact": "7132221111",
        },
        "address": {
            "street": "RUA EXEMPLO",
            "number": "100",
            "complement": "APTO 12",
            "neighborhood": "CENTRO",
            "city": "SALVADOR",
            "state": "BA",
            "postal_code": "40000000",
        },
        "updated_at": UPDATED_AT.isoformat(),
    }


def test_serialize_patient_keeps_absent_strings_and_nulls_verbatim():
    patient = _patient(
        social_name="",
        date_of_birth=None,
        gender="",
        gender_identity="",
        mother_name="",
        father_name="",
        race_color="",
        birthplace="",
        nationality="",
        marital_status="",
        education_level="",
        profession="",
        cns="",
        cpf="",
        phone_home="",
        phone_cellular="",
        phone_contact="",
        street="",
        address_number="",
        address_complement="",
        neighborhood="",
        city="",
        state="",
        postal_code="",
    )

    payload = serialize_patient(patient, "0000002")

    assert payload["date_of_birth"] is None
    assert payload["phones"] == {"home": "", "cellular": "", "contact": ""}
    assert payload["address"] == {
        "street": "",
        "number": "",
        "complement": "",
        "neighborhood": "",
        "city": "",
        "state": "",
        "postal_code": "",
    }
    for key in ("social_name", "gender", "gender_identity", "cns", "cpf"):
        assert payload[key] == "", key


def test_serialize_patient_formats_the_birth_date_as_a_civil_date():
    payload = serialize_patient(_patient(date_of_birth=date(1974, 12, 1)), "0000001")

    assert payload["date_of_birth"] == "1974-12-01"


def test_serialize_patient_emits_updated_at_with_an_explicit_offset():
    payload = serialize_patient(_patient(), "0000001")

    assert ISO_WITH_OFFSET.fullmatch(payload["updated_at"]), payload["updated_at"]
    assert datetime.fromisoformat(payload["updated_at"]) == UPDATED_AT


def _wrapper_qualnames(view) -> list[str]:
    """Code qualnames of every decorator wrapper around ``view``, outermost first."""
    qualnames: list[str] = []
    current = view
    while hasattr(current, "__wrapped__"):
        qualnames.append(current.__code__.co_qualname)
        current = current.__wrapped__
    qualnames.append(current.__code__.co_qualname)
    return qualnames


AUTH_WRAPPER = "requires_upstream_token.<locals>.wrapper"


def test_both_endpoints_share_the_upa001_auth_and_no_store_helpers():
    photo = _wrapper_qualnames(views.current_inpatients)
    demographics = _wrapper_qualnames(views.patient_demographics)

    assert AUTH_WRAPPER in photo
    assert demographics[:-1] == photo[:-1]
    for view in (views.current_inpatients, views.patient_demographics):
        assert view.csrf_exempt is True
        source = inspect.getsource(view)
        assert "Authorization" not in source
        assert "compare_digest" not in source


def test_demographics_view_defers_the_envelope_and_headers_to_shared_helpers():
    source = inspect.getsource(views.patient_demographics)

    assert "JsonResponse(" not in source
    assert "Cache-Control" not in source
    assert "api_response(" in source
    assert "error_response(" in source
