"""Integration evidence for slice UPA-002 R1-R4: demographics by prontuario.

Every case crosses the real middleware stack: CSRF exemption, the
password-change allowlist and the Bearer gate. One patient is asserted field
by field against the D4 wire table, and the response key set must be exact
(no model-internal field may surface).

Synthetic values only: every prontuario, name, document and address below is
fabricated.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from zoneinfo import ZoneInfo

import pytest
from django.test import Client

from apps.patients.models import Patient

BAHIA = ZoneInfo("America/Bahia")
DEMOGRAPHICS_URL = "/api/v1/patients/0000001"
SYNTHETIC_TOKEN = "synthetic-upstream-token-0123456789abcdef"
pytestmark = pytest.mark.django_db

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

PHONE_KEYS = {"home", "cellular", "contact"}
ADDRESS_KEYS = {
    "street",
    "number",
    "complement",
    "neighborhood",
    "city",
    "state",
    "postal_code",
}

INTERNAL_KEYS = {"id", "source_system", "created_at", "patient_source_key"}

SYNTHETIC_PATIENT = {
    "patient_source_key": "0000001",
    "source_system": "tasy",
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
}

ISO_WITH_OFFSET = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})"
)


@pytest.fixture(autouse=True)
def _configured_token(settings):
    settings.SIRHOSP_UPSTREAM_API_TOKEN = SYNTHETIC_TOKEN


def _client() -> Client:
    return Client(headers={"Authorization": f"Bearer {SYNTHETIC_TOKEN}"})


def _patient(**overrides) -> Patient:
    return Patient.objects.create(**{**SYNTHETIC_PATIENT, **overrides})


def _get(prontuario: str) -> dict:
    response = _client().get(f"/api/v1/patients/{prontuario}")
    assert response.status_code == 200
    return response.json()


def test_demographics_returns_every_mapped_field_verbatim():
    patient = _patient()
    stored = Patient.objects.get(pk=patient.pk)

    response = _client().get(DEMOGRAPHICS_URL)

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response["Content-Type"] == "application/json; charset=utf-8"
    payload = response.json()
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
        "updated_at": stored.updated_at.isoformat(),
    }


def test_response_carries_exactly_the_allowlisted_keys():
    _patient()

    payload = _get("0000001")

    assert set(payload) == DEMOGRAPHICS_KEYS
    assert not set(payload) & INTERNAL_KEYS
    assert set(payload["phones"]) == PHONE_KEYS
    assert set(payload["address"]) == ADDRESS_KEYS


def test_updated_at_carries_an_explicit_offset():
    _patient()

    payload = _get("0000001")

    assert ISO_WITH_OFFSET.fullmatch(payload["updated_at"]), payload["updated_at"]


def test_absent_strings_stay_empty_and_only_the_birth_date_is_null():
    Patient.objects.create(patient_source_key="0000002", name="PACIENTE SEM DADOS")

    payload = _get("0000002")

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
    for key in DEMOGRAPHICS_KEYS - {
        "prontuario",
        "name",
        "date_of_birth",
        "phones",
        "address",
        "updated_at",
    }:
        assert payload[key] == "", key


def test_gender_stays_verbatim_free_text():
    _patient(patient_source_key="0000003", gender="Feminino")

    payload = _get("0000003")

    assert payload["gender"] == "Feminino"


def test_prontuario_is_echoed_verbatim():
    _patient(patient_source_key="0000042")

    payload = _get("0000042")

    assert payload["prontuario"] == "0000042"
    assert payload["name"] == "PACIENTE EXEMPLO"


def test_lookup_is_restricted_to_the_tasy_source_system():
    _patient(
        patient_source_key="0000006",
        source_system="legacy",
        name="PACIENTE OUTRA ORIGEM",
    )

    response = _client().get("/api/v1/patients/0000006")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "patient_not_found"


def test_tasy_patient_wins_over_another_source_system_with_the_same_key():
    _patient(
        patient_source_key="0000007",
        source_system="legacy",
        name="PACIENTE OUTRA ORIGEM",
    )
    _patient(patient_source_key="0000007", name="PACIENTE EXEMPLO")

    payload = _get("0000007")

    assert payload["name"] == "PACIENTE EXEMPLO"


def test_unknown_prontuario_answers_404_patient_not_found():
    response = _client().get("/api/v1/patients/0999999")

    body = response.json()

    assert response.status_code == 404
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == "patient_not_found"
    assert body["error"]["message"]
    assert response["Cache-Control"] == "no-store"
    assert "0999999" not in response.content.decode("utf-8")


def test_auth_runs_before_lookup():
    response = Client().get("/api/v1/patients/0999999")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_authenticated_non_get_methods_answer_405(method: str):
    _patient()
    client = Client(
        enforce_csrf_checks=True,
        headers={"Authorization": f"Bearer {SYNTHETIC_TOKEN}"},
    )

    response = getattr(client, method)(DEMOGRAPHICS_URL)

    assert response.status_code == 405
    assert response["Allow"] == "GET"
    assert response["Cache-Control"] == "no-store"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_unauthenticated_non_get_methods_are_refused_with_401(method: str):
    _patient()
    client = Client(enforce_csrf_checks=True)

    response = getattr(client, method)(DEMOGRAPHICS_URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize(
    "authorization", [None, f"Bearer {SYNTHETIC_TOKEN}"], ids=["no-header", "valid-token"]
)
def test_missing_setting_fails_closed_with_500(
    settings, method: str, authorization: str | None
):
    _patient()
    settings.SIRHOSP_UPSTREAM_API_TOKEN = ""
    client = Client()
    headers = {} if authorization is None else {"Authorization": authorization}

    response = getattr(client, method)(DEMOGRAPHICS_URL, headers=headers)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


def test_repeated_reads_are_identical_and_persist_nothing():
    _patient()
    patients_before = Patient.objects.count()

    first = _client().get(DEMOGRAPHICS_URL)
    second = _client().get(DEMOGRAPHICS_URL)

    assert first.status_code == 200
    assert first.content == second.content
    assert Patient.objects.count() == patients_before


def _failure_record_fields(caplog) -> dict[str, str]:
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "apps.upstream_api"
    ]
    assert len(messages) == 1
    return dict(re.findall(r"(\w+)=(\S+)", messages[0]))


def test_unexpected_failure_logs_method_sanitized_route_and_status_only(
    caplog, monkeypatch
):
    _patient()

    def _boom(prontuario: str) -> dict:
        raise RuntimeError("synthetic boom 0000001")

    monkeypatch.setattr("apps.upstream_api.views.build_patient_demographics", _boom)

    with caplog.at_level(logging.ERROR, logger="apps.upstream_api"):
        response = _client().get(DEMOGRAPHICS_URL)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "Traceback" not in response.content.decode("utf-8")
    assert _failure_record_fields(caplog) == {
        "method": "GET",
        "route": "/api/v1/patients/<prontuario>",
        "status": "500",
    }
    assert "0000001" not in caplog.text
    assert "synthetic boom" not in caplog.text
