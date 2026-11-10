"""Integration evidence for slice UPA-001 R4, R6, R7 and R10 (application logging).

Every case goes through the real middleware stack: CSRF exemption, the
password-change allowlist and the Bearer gate. Row payloads follow the exact
1:1 census identity contract; the photo is refused when a patient row carries
a blank name and carries ``cycle_seq`` (the served run primary key, v1.1
additive field) as its wall-clock-independent identity.

Synthetic values only: every prontuario, name and sector below is fabricated.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.accounts.models import UserProfile
from apps.census.models import BedStatus, CensusSnapshot
from apps.ingestion.models import IngestionRun

BAHIA = ZoneInfo("America/Bahia")
CAPTURED_AT = datetime(2026, 9, 6, 8, 0, tzinfo=BAHIA)
PHOTO_URL = "/api/v1/inpatients/current"
SYNTHETIC_TOKEN = "synthetic-upstream-token-0123456789abcdef"
pytestmark = pytest.mark.django_db

ROW_KEYS = {
    "setor_codigo",
    "setor",
    "leito",
    "prontuario",
    "nome",
    "bed_status",
    "especialidade",
    "source_admission_at",
    "source_movement_at",
}


@pytest.fixture(autouse=True)
def _configured_token(settings):
    settings.SIRHOSP_UPSTREAM_API_TOKEN = SYNTHETIC_TOKEN


def _client() -> Client:
    return Client(headers={"Authorization": f"Bearer {SYNTHETIC_TOKEN}"})


def _run(*, status: str = "succeeded") -> IngestionRun:
    return IngestionRun.objects.create(
        status=status,
        intent="census_extraction",
        finished_at=CAPTURED_AT + timedelta(hours=1),
    )


def _row(
    run: IngestionRun,
    *,
    setor: str = "CLINICA MEDICA",
    setor_codigo: str = "640",
    leito: str = "I10CA",
    prontuario: str = "0000001",
    nome: str = "PACIENTE EXEMPLO",
    especialidade: str = "CIV",
    bed_status: str = BedStatus.OCCUPIED,
    source_admission_at: datetime | None = None,
    source_movement_at: datetime | None = None,
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        ingestion_run=run,
        captured_at=CAPTURED_AT,
        setor=setor,
        setor_codigo=setor_codigo,
        leito=leito,
        prontuario=prontuario,
        nome=nome,
        especialidade=especialidade,
        bed_status=bed_status,
        source_admission_at=source_admission_at,
        source_movement_at=source_movement_at,
    )


def _photo() -> dict:
    response = _client().get(PHOTO_URL)
    assert response.status_code == 200
    return response.json()


ISO_WITH_OFFSET = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})")


def _has_explicit_offset(value: str) -> bool:
    return ISO_WITH_OFFSET.fullmatch(value) is not None


def test_photo_returns_patient_rows_with_the_exact_row_contract():
    run = _run()
    _row(
        run,
        source_admission_at=datetime(2026, 9, 5, 14, 30, tzinfo=BAHIA),
    )
    _row(run, prontuario="", nome="DESOCUPADO", leito="I10CB", bed_status=BedStatus.EMPTY)

    photo = _photo()

    assert set(photo) == {"captured_at", "cycle_seq", "row_count", "patients"}
    assert photo["row_count"] == 1
    assert _has_explicit_offset(photo["captured_at"])
    assert datetime.fromisoformat(photo["captured_at"]) == CAPTURED_AT
    row = photo["patients"][0]
    assert set(row) == ROW_KEYS
    assert row["setor_codigo"] == "640"
    assert row["setor"] == "CLINICA MEDICA"
    assert row["leito"] == "I10CA"
    assert row["prontuario"] == "0000001"
    assert row["nome"] == "PACIENTE EXEMPLO"
    assert row["bed_status"] == BedStatus.OCCUPIED
    assert row["especialidade"] == "CIV"
    assert _has_explicit_offset(row["source_admission_at"])
    assert datetime.fromisoformat(row["source_admission_at"]) == datetime(
        2026, 9, 5, 14, 30, tzinfo=BAHIA
    )
    assert row["source_movement_at"] is None


def test_source_timestamps_stay_null_when_the_source_informed_only_a_date():
    run = _run()
    _row(run, source_admission_at=None, source_movement_at=None)

    row = _photo()["patients"][0]

    assert row["source_admission_at"] is None
    assert row["source_movement_at"] is None


def test_sector_pairs_sharing_one_code_stay_distinct():
    run = _run()
    _row(run, setor="CLINICA MEDICA", setor_codigo="640", leito="I10CA", prontuario="0000001")
    _row(run, setor="CIRURGIA GERAL", setor_codigo="640", leito="C01", prontuario="0000002")

    patients = _photo()["patients"]

    assert [(row["setor_codigo"], row["setor"]) for row in patients] == [
        ("640", "CIRURGIA GERAL"),
        ("640", "CLINICA MEDICA"),
    ]
    assert len({row["prontuario"] for row in patients}) == 2


def test_patient_without_a_bed_keeps_an_empty_leito():
    run = _run()
    _row(run, leito="", prontuario="0000003", nome="PACIENTE SEM LEITO")

    row = _photo()["patients"][0]

    assert row["leito"] == ""
    assert row["prontuario"] == "0000003"
    assert row["nome"] == "PACIENTE SEM LEITO"


def test_rows_order_by_sector_code_bed_and_prontuario():
    run = _run()
    _row(run, setor="SETOR B", setor_codigo="700", leito="B02", prontuario="0000003")
    _row(run, setor="SETOR A", setor_codigo="640", leito="A02", prontuario="0000002")
    _row(run, setor="SETOR A", setor_codigo="640", leito="A01", prontuario="0000001")

    patients = _photo()["patients"]

    ordering = [
        (row["setor"], row["setor_codigo"], row["leito"], row["prontuario"])
        for row in patients
    ]
    assert ordering == [
        ("SETOR A", "640", "A01", "0000001"),
        ("SETOR A", "640", "A02", "0000002"),
        ("SETOR B", "700", "B02", "0000003"),
    ]


def test_duplicate_row_keys_order_by_primary_key_and_stay_stable():
    run = _run()
    _row(run, especialidade="CIV")
    _row(run, especialidade="NEF")

    first = _photo()
    second = _photo()

    assert [row["especialidade"] for row in first["patients"]] == ["CIV", "NEF"]
    assert first == second


def test_empty_completed_photo_is_200_with_no_patients():
    run = _run()
    _row(run, prontuario="", nome="DESOCUPADO", leito="I10CB", bed_status=BedStatus.EMPTY)

    photo = _photo()

    assert photo["patients"] == []
    assert photo["row_count"] == 0
    assert datetime.fromisoformat(photo["captured_at"]) == CAPTURED_AT
    assert photo["cycle_seq"] == run.pk


def test_photo_exposes_the_served_cycle_seq():
    run = _run()
    _row(run)

    photo = _photo()

    assert photo["cycle_seq"] == run.pk
    assert isinstance(photo["cycle_seq"], int)
    assert not isinstance(photo["cycle_seq"], bool)


def test_cycle_seq_distinguishes_cycles_sharing_one_captured_at():
    first = _run()
    _row(first, prontuario="0000001")
    second = _run()
    _row(second, prontuario="0000002")
    assert second.pk > first.pk

    photo = _photo()

    assert datetime.fromisoformat(photo["captured_at"]) == CAPTURED_AT
    assert photo["cycle_seq"] == second.pk
    assert photo["cycle_seq"] > first.pk
    assert [row["prontuario"] for row in photo["patients"]] == ["0000002"]


def test_repeated_polls_repeat_the_captured_at_and_cycle_seq_pair():
    run = _run()
    _row(run)

    first = _photo()
    second = _photo()

    assert (first["captured_at"], first["cycle_seq"]) == (
        second["captured_at"],
        second["cycle_seq"],
    )
    assert first["cycle_seq"] == run.pk


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_missing_photo_answers_404_no_snapshot(status: str):
    IngestionRun.objects.create(
        status=status, intent="census_extraction", finished_at=CAPTURED_AT
    )

    response = _client().get(PHOTO_URL)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_snapshot"
    assert response["Cache-Control"] == "no-store"


def test_repeated_polls_are_identical_and_persist_nothing():
    run = _run()
    _row(run)
    runs_before = IngestionRun.objects.count()
    rows_before = CensusSnapshot.objects.count()

    first = _client().get(PHOTO_URL)
    second = _client().get(PHOTO_URL)

    assert first.status_code == 200
    assert first.content == second.content
    assert first["Cache-Control"] == "no-store"
    assert first["Content-Type"] == "application/json; charset=utf-8"
    assert IngestionRun.objects.count() == runs_before
    assert CensusSnapshot.objects.count() == rows_before


def test_invalid_patient_row_fails_the_whole_photo():
    run = _run()
    _row(run, prontuario="0000008", nome="PACIENTE VALIDO")
    _row(run, prontuario="0000009", nome="")

    response = _client().get(PHOTO_URL)
    text = response.content.decode("utf-8")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "0000008" not in text
    assert "0000009" not in text
    assert "PACIENTE VALIDO" not in text
    assert "Traceback" not in text


def _failure_record_fields(caplog) -> dict[str, str]:
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "apps.upstream_api"
    ]
    assert len(messages) == 1
    return dict(re.findall(r"(\w+)=(\S+)", messages[0]))


def test_invalid_row_failure_logs_method_route_and_status_only(caplog):
    run = _run()
    _row(run, prontuario="0000009", nome="")

    with caplog.at_level(logging.ERROR, logger="apps.upstream_api"):
        response = _client().get(PHOTO_URL)

    assert response.status_code == 500
    assert _failure_record_fields(caplog) == {
        "method": "GET",
        "route": "/api/v1/inpatients/current",
        "status": "500",
    }
    assert "0000009" not in caplog.text


def test_unexpected_failure_logs_method_route_and_status_only(caplog, monkeypatch):
    def _boom():
        raise RuntimeError("synthetic boom 0000009")

    monkeypatch.setattr("apps.upstream_api.views.build_current_photo", _boom)

    with caplog.at_level(logging.ERROR, logger="apps.upstream_api"):
        response = _client().get(PHOTO_URL)

    assert response.status_code == 500
    assert _failure_record_fields(caplog) == {
        "method": "GET",
        "route": "/api/v1/inpatients/current",
        "status": "500",
    }
    assert "synthetic boom" not in caplog.text


def test_unauthenticated_post_is_refused_with_401_not_csrf_403():
    client = Client(enforce_csrf_checks=True)

    response = client.post(PHOTO_URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_authenticated_post_answers_405_and_keeps_no_store():
    client = Client(
        enforce_csrf_checks=True,
        headers={"Authorization": f"Bearer {SYNTHETIC_TOKEN}"},
    )

    response = client.post(PHOTO_URL)

    assert response.status_code == 405
    assert response["Allow"] == "GET"
    assert response["Cache-Control"] == "no-store"


def test_flagged_portal_session_is_not_redirected_on_the_api():
    user = User.objects.create_user("operador-exemplo", password="synthetic-pass")
    UserProfile.objects.create(user=user, must_change_password=True)
    client = Client()
    assert client.login(username="operador-exemplo", password="synthetic-pass")

    api_response = client.get(PHOTO_URL)
    portal_response = client.get("/beds/")

    assert api_response.status_code == 401
    assert api_response.json()["error"]["code"] == "unauthorized"
    assert portal_response.status_code == 302
    assert portal_response["Location"] == "/perfil/"
