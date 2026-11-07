"""PEND-S4/STRUCT-PEND-S4: pending-items XLSX export HTTP integration.

Covers R1-R5: the exact 23-column PP-08 contract with one row per item
in its current state, native date/datetime/id cells, the four catalog
profiles (scheduling with and without RNM complements, treatment
period, signature and simple), literal text safety, the shared
conservative cut (filters, no pagination, ambiguity exclusion, empty
headers-only), cache directives, GET purity, no residual files and the
real confirmed exit excluding the episode from the current cut while
its contextual history remains.

All fixtures are synthetic; no production source is ever contacted.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import openpyxl
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from openpyxl.utils import get_column_letter

from apps.census.models import BedStatus, CensusSnapshot, Specialty
from apps.patients.models import EXIT_HOSPITAL_DISCHARGE, Admission, Patient
from apps.patients.reconciliation import (
    EVIDENCE_SOURCE_DISCHARGE_RECORD,
    DischargeExitEvidence,
    apply_discharge_exit,
    decide_discharge_match,
)
from apps.pending_items.export import EXPORT_HEADERS
from apps.pending_items.models import (
    OUTRO_SLUG,
    STATUS_ACTIVE,
    STATUS_CLOSED_UNRESOLVED,
    STATUS_RESOLVED,
    PendingItem,
    PendingItemRevision,
    PendingItemType,
)
from apps.pending_items.queries import AGGREGATE_PER_PAGE

TZ = ZoneInfo("America/Bahia")
UTC = ZoneInfo("UTC")
EXPORT_URL = "/pendencias/export.xlsx"

EXPECTED_HEADERS = [
    "ID da pendência",
    "ID da internação",
    "Registro",
    "Nome",
    "Unidade atual",
    "Leito",
    "Primeira unidade de internação",
    "Especialidade",
    "Categoria",
    "Tipo",
    "Descrição/observação",
    "Agendada?",
    "Data agendada",
    "Contraste",
    "Sedação",
    "Início do tratamento",
    "Previsão de término",
    "Assinatura do sumário em",
    "Status",
    "Criado em",
    "Criado por",
    "Atualizado em",
    "Atualizado por",
]

COLUMN = {header: index for index, header in enumerate(EXPECTED_HEADERS)}


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE SINTETICO {key}",
    )


def _make_admission(
    patient: Patient,
    key: str,
    start: str | None = "2026-06-01T08:00:00",
    end: str | None = None,
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=_dt(start) if start else None,
        discharge_date=_dt(end) if end else None,
    )


def _make_census_row(
    prontuario: str,
    *,
    setor: str = "CLINICA MEDICA",
    leito: str = "L01",
    especialidade: str = "",
    captured_at: str = "2026-06-10T08:00:00",
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        captured_at=_dt(captured_at),
        setor=setor,
        leito=leito,
        prontuario=prontuario,
        nome="PACIENTE SINTETICO",
        especialidade=especialidade,
        bed_status=BedStatus.OCCUPIED,
    )


def _make_item(
    admission: Admission,
    *,
    description: str = "pendencia sintetica",
    status: str = STATUS_ACTIVE,
    created_at: datetime | None = None,
    finalized_at: datetime | None = None,
) -> PendingItem:
    outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
    item = PendingItem.objects.create(
        admission=admission,
        item_type=outro,
        description=description,
        status=status,
        version=1,
        finalized_at=finalized_at,
    )
    if created_at is not None:
        PendingItem.objects.filter(pk=item.pk).update(created_at=created_at)
        item.refresh_from_db()
    return item


def _make_typed_item(
    admission: Admission,
    item_type: PendingItemType,
    *,
    description: str = "",
    **details: object,
) -> PendingItem:
    """Create one item of a catalog type with synthetic typed details."""
    return PendingItem.objects.create(
        admission=admission,
        item_type=item_type,
        description=description,
        status=STATUS_ACTIVE,
        version=1,
        **details,
    )


def _eligible_admission(
    key: str = "P_EXP_1",
    *,
    setor: str = "CLINICA MEDICA",
    leito: str = "L01",
    especialidade: str = "",
) -> Admission:
    patient = _make_patient(key)
    admission = _make_admission(patient, f"ADM_{key}")
    _make_census_row(
        key, setor=setor, leito=leito, especialidade=especialidade
    )
    return admission


def _workbook(response):
    assert response.status_code == 200
    return openpyxl.load_workbook(BytesIO(response.content)).active


def _rows(ws) -> list[list]:
    assert ws is not None
    return [
        [cell.value for cell in row] for row in ws.iter_rows(min_row=2)
    ]


def _cell(ws, row: int, header: str):
    return ws.cell(row=row, column=COLUMN[header] + 1)


def _row_for(ws, item_id: int) -> int:
    assert ws is not None
    for row in range(2, ws.max_row + 1):
        if _cell(ws, row, "ID da pendência").value == item_id:
            return row
    raise AssertionError(f"item {item_id} not exported")


def _descriptions(ws) -> list[str]:
    return [row[COLUMN["Descrição/observação"]] for row in _rows(ws)]


def _cache_directives(response) -> set[str]:
    header = response.headers.get("Cache-Control", "")
    return {part.strip().lower() for part in header.split(",") if part.strip()}


def _assert_private_no_store(response) -> None:
    directives = _cache_directives(response)
    assert "private" in directives
    assert "no-store" in directives


@pytest.fixture
def writer_client(client: Client, db: object) -> Client:
    user = User.objects.create_user(username="export_writer", password="pw123456")
    Group.objects.get(name="Desospitalização").user_set.add(user)
    client.login(username="export_writer", password="pw123456")
    return client


@pytest.fixture
def reader_client(client: Client, db: object) -> Client:
    User.objects.create_user(username="export_reader", password="pw123456")
    client.login(username="export_reader", password="pw123456")
    return client


@pytest.fixture
def groupless_superuser_client(client: Client, db: object) -> Client:
    User.objects.create_superuser(
        username="export_root", password="pw123456",
        email="root@example.com",
    )
    client.login(username="export_root", password="pw123456")
    return client


@pytest.mark.django_db
class TestExportAccess:
    def test_route_name_resolves_to_xlsx_path(self) -> None:
        assert reverse("pending_items:aggregate_export") == EXPORT_URL

    def test_reader_member_and_groupless_superuser_export(
        self,
        reader_client: Client,
        writer_client: Client,
        groupless_superuser_client: Client,
    ) -> None:
        admission = _eligible_admission("P_EXP_R1")
        _make_item(admission, description="exportavel por todos")
        for http_client in (
            reader_client, writer_client, groupless_superuser_client
        ):
            ws = _workbook(http_client.get(EXPORT_URL))
            assert "exportavel por todos" in _descriptions(ws)

    def test_export_grants_no_write_permission(
        self, reader_client: Client, groupless_superuser_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_R1W")
        item = _make_item(admission, description="protegida export")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        for http_client in (reader_client, groupless_superuser_client):
            assert http_client.get(EXPORT_URL).status_code == 200
            response = http_client.post(
                f"/pendencias/{item.pk}/edit/",
                {
                    "item_type": str(outro.pk),
                    "description": "tentativa",
                    "expected_version": "1",
                    "next": "/pendencias/",
                },
            )
            assert response.status_code == 403
        item.refresh_from_db()
        assert item.description == "protegida export"

    def test_anonymous_gets_login_without_bytes(self, client: Client) -> None:
        admission = _eligible_admission("P_EXP_ANON")
        _make_item(admission, description="anonima export")
        response = client.get(EXPORT_URL)
        assert response.status_code == 302
        assert "/login/" in response.url  # type: ignore[attr-defined]
        assert b"anonima export" not in response.content


@pytest.mark.django_db
class TestExportCutParity:
    def test_all_results_not_the_visible_page(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_PAGE")
        for index in range(AGGREGATE_PER_PAGE + 1):
            _make_item(admission, description=f"pagina-{index:02d}")
        page1 = reader_client.get("/pendencias/?view=items&page=1")
        assert f"pagina-{AGGREGATE_PER_PAGE:02d}" not in (
            page1.content.decode()
        )
        ws = _workbook(reader_client.get(f"{EXPORT_URL}?view=items"))
        assert _descriptions(ws) == [
            f"pagina-{index:02d}" for index in range(AGGREGATE_PER_PAGE + 1)
        ]

    def test_mode_is_ignored_views_export_same_selection(
        self, reader_client: Client
    ) -> None:
        first = _eligible_admission(
            "P_EXP_MODE1", setor="UTI", leito="U01"
        )
        second = _eligible_admission(
            "P_EXP_MODE2", setor="ENF", leito="E02"
        )
        _make_item(first, description="modo primeira")
        _make_item(second, description="modo segunda")
        patients = _rows(
            _workbook(reader_client.get(f"{EXPORT_URL}?view=patients"))
        )
        items = _rows(
            _workbook(reader_client.get(f"{EXPORT_URL}?view=items"))
        )
        assert patients == items
        assert [row[COLUMN["Descrição/observação"]] for row in patients] == [
            "modo segunda",
            "modo primeira",
        ]

    def test_status_and_unit_filters_apply_before_export(
        self, reader_client: Client
    ) -> None:
        first = _eligible_admission("P_EXP_F1", setor="UTI", leito="U01")
        second = _eligible_admission("P_EXP_F2", setor="UTI", leito="U02")
        _make_item(first, description="leito um")
        _make_item(
            second, description="leito dois resolvido",
            status=STATUS_RESOLVED,
            finalized_at=_dt("2026-06-11T10:00:00"),
        )
        ws = _workbook(
            reader_client.get(f"{EXPORT_URL}?status=all&unidade=UTI&leito=U02")
        )
        assert _descriptions(ws) == ["leito dois resolvido"]
        ws = _workbook(reader_client.get(EXPORT_URL))
        assert _descriptions(ws) == ["leito um"]

    def test_system_updater_and_time_bounds_match_panel(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_F3")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        now = timezone.now()
        PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description="encerrada automatica export",
            status=STATUS_CLOSED_UNRESOLVED,
            version=2,
            finalized_at=_dt("2026-06-11T10:00:00"),
            updated_by=None,
            updated_by_name="Sistema",
            is_system_updated=True,
        )
        _make_item(
            admission, description="antiga humana",
            created_at=now - timedelta(days=9),
        )
        _make_item(
            admission, description="recente humana",
            created_at=now - timedelta(days=1),
        )
        ws = _workbook(
            reader_client.get(f"{EXPORT_URL}?status=all&atualizador=system")
        )
        assert _descriptions(ws) == ["encerrada automatica export"]
        ws = _workbook(reader_client.get(f"{EXPORT_URL}?min_dias=5"))
        assert _descriptions(ws) == ["antiga humana"]
        ws = _workbook(
            reader_client.get(f"{EXPORT_URL}?max_dias=2&ordenar=tempo_desc")
        )
        assert _descriptions(ws) == ["recente humana"]

    def test_ambiguous_excluded_and_repetition_single(
        self, reader_client: Client
    ) -> None:
        conflict = _make_patient("P_EXP_AMB1")
        adm_conflict = _make_admission(conflict, "ADM_EXP_AMB1")
        _make_census_row("P_EXP_AMB1", setor="UTI", leito="U01")
        _make_census_row("P_EXP_AMB1", setor="ENF", leito="E02")
        _make_item(adm_conflict, description="leitos conflitantes export")
        two = _make_patient("P_EXP_AMB2")
        adm_two = _make_admission(two, "ADM_EXP_AMB2_A")
        _make_admission(two, "ADM_EXP_AMB2_B")
        _make_census_row("P_EXP_AMB2")
        _make_item(adm_two, description="duas abertas export")
        valid = _eligible_admission("P_EXP_AMB3")
        _make_census_row("P_EXP_AMB3")
        _make_item(valid, description="valida export")
        html = reader_client.get("/pendencias/?status=all").content.decode()
        ws = _workbook(reader_client.get(f"{EXPORT_URL}?status=all"))
        found = _descriptions(ws)
        assert "leitos conflitantes export" not in html
        assert "duas abertas export" not in html
        assert "leitos conflitantes export" not in found
        assert "duas abertas export" not in found
        assert found.count("valida export") == 1

    def test_invalid_time_bounds_export_headers_only(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_F4")
        _make_item(admission, description="visivel sem filtro export")
        ws = _workbook(reader_client.get(f"{EXPORT_URL}?min_dias=-2"))
        assert ws is not None
        assert ws.max_row == 1

    def test_ordering_matches_items_selection(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_ORD")
        now = timezone.now()
        _make_item(
            admission, description="ordem antiga",
            created_at=now - timedelta(days=9),
        )
        _make_item(
            admission, description="ordem recente",
            created_at=now - timedelta(days=1),
        )
        asc = _descriptions(
            _workbook(reader_client.get(f"{EXPORT_URL}?ordenar=tempo_asc"))
        )
        desc = _descriptions(
            _workbook(reader_client.get(f"{EXPORT_URL}?ordenar=tempo_desc"))
        )
        assert asc == ["ordem recente", "ordem antiga"]
        assert desc == ["ordem antiga", "ordem recente"]


@pytest.mark.django_db
class TestExportColumnsAndValues:
    def test_columns_values_authors_and_dates(
        self, reader_client: Client
    ) -> None:
        Specialty.objects.get_or_create(
            code="CIV", defaults={"name": "CIRURGIA VASCULAR"}
        )
        author = User.objects.get(username="export_reader")
        other = User.objects.create_user(
            username="export_editor", password="pw123456"
        )
        admission = _eligible_admission(
            "P_EXP_COL", setor="UTI GERAL", leito="U07",
            especialidade="CIV",
        )
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        item = PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description="linha completa export",
            status=STATUS_ACTIVE,
            version=1,
            created_by=author,
            created_by_name="export_reader",
            updated_by=other,
            updated_by_name="export_editor",
            is_system_updated=False,
        )
        PendingItem.objects.filter(pk=item.pk).update(
            created_at=_dt("2026-06-05T10:30:00"),
            updated_at=_dt("2026-06-09T18:45:00"),
        )
        ws = _workbook(reader_client.get(EXPORT_URL))
        assert ws is not None
        assert [cell.value for cell in ws[1]] == EXPECTED_HEADERS
        assert list(EXPORT_HEADERS) == EXPECTED_HEADERS
        rows = _rows(ws)
        assert len(rows) == 1
        assert rows[0][COLUMN["ID da pendência"]] == item.pk
        assert rows[0][COLUMN["ID da internação"]] == admission.pk
        assert rows[0][COLUMN["Registro"]] == "P_EXP_COL"
        assert rows[0][COLUMN["Nome"]] == "PACIENTE SINTETICO P_EXP_COL"
        assert rows[0][COLUMN["Unidade atual"]] == "UTI GERAL"
        assert rows[0][COLUMN["Leito"]] == "U07"
        assert rows[0][COLUMN["Primeira unidade de internação"]] == (
            "Primeira unidade não identificada"
        )
        assert rows[0][COLUMN["Especialidade"]] == "CIRURGIA VASCULAR"
        assert rows[0][COLUMN["Categoria"]] == "Outras pendências"
        assert rows[0][COLUMN["Tipo"]] == "Outro"
        assert rows[0][COLUMN["Descrição/observação"]] == (
            "linha completa export"
        )
        assert rows[0][COLUMN["Status"]] == "Ativa"
        assert rows[0][COLUMN["Criado em"]] == datetime(2026, 6, 5, 10, 30)
        assert rows[0][COLUMN["Criado por"]] == "export_reader"
        assert rows[0][COLUMN["Atualizado em"]] == datetime(
            2026, 6, 9, 18, 45
        )
        assert rows[0][COLUMN["Atualizado por"]] == "export_editor"

    def test_system_author_and_no_history_leak(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_SYS")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        item = PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description="atual sistema export",
            status=STATUS_CLOSED_UNRESOLVED,
            version=2,
            finalized_at=_dt("2026-06-11T10:00:00"),
            updated_by=None,
            updated_by_name="Sistema",
            is_system_updated=True,
        )
        PendingItemRevision.objects.create(
            item=item, version=1, action="created", item_type=outro,
            type_name=outro.name, description="atual sistema export",
            status=STATUS_ACTIVE,
        )
        PendingItemRevision.objects.create(
            item=item, version=2, action="finalized", item_type=outro,
            type_name=outro.name, description="atual sistema export",
            status=STATUS_CLOSED_UNRESOLVED, is_system=True,
            author_name="Sistema", note="nota-somente-revisao-export",
        )
        ws = _workbook(reader_client.get(f"{EXPORT_URL}?status=all"))
        rows = _rows(ws)
        assert len(rows) == 1
        assert rows[0][COLUMN["Status"]] == "Encerrada sem resolução"
        assert rows[0][COLUMN["Atualizado por"]] == "Sistema"
        flat = " ".join(str(value) for row in rows for value in row)
        assert "nota-somente-revisao-export" not in flat

    def test_first_unit_uses_episode_pathway(
        self, reader_client: Client
    ) -> None:
        from apps.census.models import PatientMovement

        admission = _eligible_admission("P_EXP_FU")
        day = datetime.strptime("2026-06-02", "%Y-%m-%d").date()
        PatientMovement.objects.create(
            patient=admission.patient, admission=admission,
            movement_date=day, sector="PRONTO SOCORRO", sequence=0,
            first_seen_at=_dt("2026-06-01T08:00:00"),
            last_seen_at=_dt("2026-06-01T08:00:00"),
        )
        _make_item(admission, description="com percurso export")
        ws = _workbook(reader_client.get(EXPORT_URL))
        assert _rows(ws)[0][COLUMN["Primeira unidade de internação"]] == (
            "PRONTO SOCORRO"
        )


@pytest.mark.django_db
class TestExportProfilesAndCellTypes:
    """R1/R2: one row per item and native cells for all four profiles."""

    def _scene(self) -> dict[str, object]:
        Specialty.objects.get_or_create(
            code="CIV", defaults={"name": "CIRURGIA VASCULAR"}
        )
        admission = _eligible_admission(
            "0001234", setor="UTI GERAL", leito="U07", especialidade="CIV"
        )
        tomografia = PendingItemType.objects.get(slug="imagem-tomografia")
        chd_rnm = PendingItemType.objects.get(slug="chd-rnm")
        antibioticos = PendingItemType.objects.get(
            slug="infeccioso-antibioticos"
        )
        sumario = PendingItemType.objects.get(slug="sumario-assinatura")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        return {
            "admission": admission,
            "tomografia": _make_typed_item(
                admission,
                tomografia,
                description="tomografia sintetica",
                is_scheduled=True,
                scheduled_date=date(2026, 1, 1),
            ),
            "rnm": _make_typed_item(
                admission,
                chd_rnm,
                description="rnm sintetica",
                is_scheduled=True,
                scheduled_date=date(2026, 11, 10),
                contrast=True,
            ),
            "antibioticos": _make_typed_item(
                admission,
                antibioticos,
                description="antibioticos sinteticos",
                treatment_start_date=date(2026, 11, 1),
                treatment_end_date=date(2026, 11, 10),
            ),
            "sumario": _make_typed_item(
                admission,
                sumario,
                description="sumario sintetico",
                signature_at=datetime(2026, 11, 12, 12, 30, tzinfo=UTC),
            ),
            "outro": _make_typed_item(
                admission, outro, description="registro simples sintetico"
            ),
        }

    def test_one_row_per_profile_with_typed_cells(
        self, reader_client: Client
    ) -> None:
        scene = self._scene()
        admission = scene["admission"]
        assert isinstance(admission, Admission)
        ws = _workbook(reader_client.get(EXPORT_URL))
        assert ws is not None
        assert [cell.value for cell in ws[1]] == EXPECTED_HEADERS
        assert ws.max_row == 6

        for name in ("tomografia", "rnm", "antibioticos", "sumario", "outro"):
            item = scene[name]
            assert isinstance(item, PendingItem)
            row = _row_for(ws, item.pk)
            assert _cell(ws, row, "ID da internação").value == admission.pk
            assert _cell(ws, row, "Registro").value == "0001234"
            assert _cell(ws, row, "Registro").data_type in ("s", "inlineStr")
            assert _cell(ws, row, "Status").value == "Ativa"
            assert _cell(ws, row, "Categoria").value == (
                item.item_type.category.name
            )
            assert _cell(ws, row, "Tipo").value == item.item_type.name

        # Scheduling without RNM complements: date native, complements N/A.
        rnm = scene["rnm"]
        assert isinstance(rnm, PendingItem)
        row = _row_for(ws, rnm.pk)
        assert _cell(ws, row, "Categoria").value == (
            "CHD (Centro de Hemorragia Digestiva)"
        )
        assert _cell(ws, row, "Tipo").value == "RNM"
        assert _cell(ws, row, "Agendada?").value == "Sim"
        scheduled = _cell(ws, row, "Data agendada")
        assert scheduled.is_date is True
        assert scheduled.number_format == "dd/mm/yyyy"
        assert scheduled.value == datetime(2026, 11, 10, 0, 0)
        assert _cell(ws, row, "Contraste").value == "Sim"
        assert _cell(ws, row, "Sedação").value == "Não informado"
        assert _cell(ws, row, "Início do tratamento").value in ("", None)
        assert _cell(ws, row, "Previsão de término").value in ("", None)
        assert _cell(ws, row, "Assinatura do sumário em").value in ("", None)

        # Tomografia: scheduled with known date, RNM complements empty.
        tomografia = scene["tomografia"]
        assert isinstance(tomografia, PendingItem)
        row = _row_for(ws, tomografia.pk)
        assert _cell(ws, row, "Agendada?").value == "Sim"
        assert _cell(ws, row, "Data agendada").value == datetime(
            2026, 1, 1, 0, 0
        )
        assert _cell(ws, row, "Contraste").value in ("", None)
        assert _cell(ws, row, "Sedação").value in ("", None)

        # Treatment period: both dates native, scheduling/signature N/A.
        antibioticos = scene["antibioticos"]
        assert isinstance(antibioticos, PendingItem)
        row = _row_for(ws, antibioticos.pk)
        assert _cell(ws, row, "Agendada?").value in ("", None)
        assert _cell(ws, row, "Data agendada").value in ("", None)
        assert _cell(ws, row, "Início do tratamento").value == datetime(
            2026, 11, 1, 0, 0
        )
        assert _cell(ws, row, "Previsão de término").value == datetime(
            2026, 11, 10, 0, 0
        )
        assert _cell(ws, row, "Assinatura do sumário em").value in ("", None)

        # Signature: institutional wall clock, tz-naive Excel instant.
        sumario = scene["sumario"]
        assert isinstance(sumario, PendingItem)
        row = _row_for(ws, sumario.pk)
        signature = _cell(ws, row, "Assinatura do sumário em")
        assert signature.is_date is True
        assert signature.number_format == "dd/mm/yyyy hh:mm"
        assert signature.value == datetime(2026, 11, 12, 9, 30)
        assert signature.value.tzinfo is None
        assert _cell(ws, row, "Início do tratamento").value in ("", None)

        # Simple record: every detail cell is empty, none reads as Não.
        outro = scene["outro"]
        assert isinstance(outro, PendingItem)
        row = _row_for(ws, outro.pk)
        for header in (
            "Agendada?",
            "Data agendada",
            "Contraste",
            "Sedação",
            "Início do tratamento",
            "Previsão de término",
            "Assinatura do sumário em",
        ):
            assert _cell(ws, row, header).value in ("", None), header

    def test_civil_date_is_not_timezone_shifted(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_CIVIL")
        chd_rnm = PendingItemType.objects.get(slug="chd-rnm")
        item = _make_typed_item(
            admission,
            chd_rnm,
            description="data civil sintetica",
            is_scheduled=True,
            scheduled_date=date(2026, 1, 1),
        )
        ws = _workbook(reader_client.get(EXPORT_URL))
        cell = _cell(ws, _row_for(ws, item.pk), "Data agendada")
        assert cell.value == datetime(2026, 1, 1, 0, 0)
        assert cell.value.date() == date(2026, 1, 1)

    def test_instants_use_institutional_wall_clock(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_INST")
        item = _make_item(admission, description="instante sintetico")
        PendingItem.objects.filter(pk=item.pk).update(
            created_at=datetime(2026, 6, 10, 15, 0, tzinfo=UTC),
            updated_at=datetime(2026, 6, 10, 18, 45, tzinfo=UTC),
        )
        ws = _workbook(reader_client.get(EXPORT_URL))
        row = _row_for(ws, item.pk)
        created = _cell(ws, row, "Criado em")
        updated = _cell(ws, row, "Atualizado em")
        assert created.value == datetime(2026, 6, 10, 12, 0)
        assert created.value.tzinfo is None
        assert created.number_format == "dd/mm/yyyy hh:mm"
        assert updated.value == datetime(2026, 6, 10, 15, 45)
        assert updated.value.tzinfo is None

    def test_unknown_scheduling_answer_stays_unknown(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_LEGACY")
        chd_rnm = PendingItemType.objects.get(slug="chd-rnm")
        item = _make_typed_item(
            admission, chd_rnm, description="agendada legada"
        )
        ws = _workbook(reader_client.get(EXPORT_URL))
        row = _row_for(ws, item.pk)
        assert _cell(ws, row, "Agendada?").value == "Não informado"
        assert _cell(ws, row, "Data agendada").value in ("", None)
        assert _cell(ws, row, "Contraste").value == "Não informado"
        assert _cell(ws, row, "Sedação").value == "Não informado"


@pytest.mark.django_db
class TestExportSheetUsability:
    """R5 at HTTP level: autofilter and frozen header on real responses."""

    def test_autofilter_and_frozen_header(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_SHEET")
        _make_item(admission, description="planilha usavel")
        ws = _workbook(reader_client.get(EXPORT_URL))
        assert ws is not None
        assert ws.freeze_panes == "A2"
        last_column = get_column_letter(len(EXPECTED_HEADERS))
        assert ws.auto_filter.ref == f"A1:{last_column}{ws.max_row}"

    def test_header_only_export_keeps_sheet_usability(
        self, reader_client: Client
    ) -> None:
        ws = _workbook(reader_client.get(f"{EXPORT_URL}?unidade=INEXISTENTE"))
        assert ws is not None
        assert ws.max_row == 1
        assert ws.max_column == 23
        assert ws.freeze_panes == "A2"
        assert ws.auto_filter.ref == "A1:W1"


@pytest.mark.django_db
class TestExportEnvelope:
    def test_mime_disposition_filename_and_cache(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_ENV")
        _make_item(admission, description="envelope export")
        response = reader_client.get(EXPORT_URL)
        assert response.status_code == 200
        assert response["Content-Type"] == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert response["Content-Disposition"] == (
            'attachment; filename="pendencias-20260610-0800.xlsx"'
        )
        _assert_private_no_store(response)

    def test_empty_result_is_valid_and_protected(
        self, reader_client: Client
    ) -> None:
        response = reader_client.get(f"{EXPORT_URL}?unidade=INEXISTENTE")
        ws = _workbook(response)
        assert ws is not None
        assert [cell.value for cell in ws[1]] == EXPECTED_HEADERS
        assert ws.max_row == 1
        _assert_private_no_store(response)

    def test_no_census_exports_headers_only(
        self, reader_client: Client
    ) -> None:
        patient = _make_patient("P_EXP_NOCENSUS")
        admission = _make_admission(patient, "ADM_EXP_NOCENSUS")
        _make_item(admission, description="sem foto export")
        ws = _workbook(reader_client.get(EXPORT_URL))
        assert ws is not None
        assert ws.max_row == 1
        assert _descriptions(ws) == []

    def test_formula_like_text_stays_literal_meanwhile_dates_are_native(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_FORM")
        chd_rnm = PendingItemType.objects.get(slug="chd-rnm")
        payload = '=HIPERLINK("http://x.example";"x")'
        text_item = _make_item(admission, description=payload)
        _make_item(admission, description="+1+1")
        date_item = _make_typed_item(
            admission,
            chd_rnm,
            description="-2+3",
            is_scheduled=True,
            scheduled_date=date(2026, 11, 10),
        )
        ws = _workbook(reader_client.get(EXPORT_URL))
        assert ws is not None
        assert payload in _descriptions(ws)
        row = _row_for(ws, text_item.pk)
        for header in ("Descrição/observação", "Nome", "Registro"):
            assert _cell(ws, row, header).data_type in ("s", "inlineStr")
        date_row = _row_for(ws, date_item.pk)
        assert _cell(ws, date_row, "Data agendada").is_date is True
        assert _cell(ws, date_row, "Descrição/observação").data_type in (
            "s",
            "inlineStr",
        )

    def test_gets_never_mutate_business_tables(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_PURE")
        item = _make_item(admission, description="pura export")
        before_items = PendingItem.objects.count()
        before_revisions = PendingItemRevision.objects.count()
        reader_client.get(EXPORT_URL)
        reader_client.get(f"{EXPORT_URL}?view=items&status=all")
        reader_client.get(f"{EXPORT_URL}?min_dias=-1")
        assert PendingItem.objects.count() == before_items
        assert PendingItemRevision.objects.count() == before_revisions
        item.refresh_from_db()
        assert item.description == "pura export"
        assert item.version == 1

    def test_export_leaves_no_file_on_the_server(
        self, reader_client: Client, settings, tmp_path
    ) -> None:
        settings.MEDIA_ROOT = tmp_path
        admission = _eligible_admission("P_EXP_MEM")
        _make_item(admission, description="memoria export")
        for _ in range(3):
            response = reader_client.get(EXPORT_URL)
            assert response.status_code == 200
            assert response.content
        assert list(tmp_path.rglob("*")) == []


@pytest.mark.django_db
class TestCategorizedExportParity:
    """STRUCT-PEND-S3/S4: the XLSX keeps the categorized cut of the panel."""

    def test_category_filter_matches_panel_and_workbook(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_CAT")
        chd_rnm = PendingItemType.objects.get(slug="chd-rnm")
        imagem_rnm = PendingItemType.objects.get(slug="imagem-rnm")
        chd_item = _make_typed_item(
            admission, chd_rnm, description="marcador-cat-chd"
        )
        imagem_item = _make_typed_item(
            admission, imagem_rnm, description="marcador-cat-imagem"
        )
        category = chd_rnm.category_id
        panel = reader_client.get(
            f"/pendencias/?categoria={category}"
        ).content.decode()
        assert "marcador-cat-chd" in panel
        assert "marcador-cat-imagem" not in panel
        ws = _workbook(reader_client.get(f"{EXPORT_URL}?categoria={category}"))
        assert _descriptions(ws) == ["marcador-cat-chd"]
        assert [
            row[COLUMN["ID da pendência"]] for row in _rows(ws)
        ] == [chd_item.pk]
        assert imagem_item.pk not in [
            row[COLUMN["ID da pendência"]] for row in _rows(ws)
        ]
        incompatible = _workbook(
            reader_client.get(
                f"{EXPORT_URL}?categoria={category}&tipo={imagem_rnm.pk}"
            )
        )
        assert incompatible.max_row == 1
        invalid = _workbook(
            reader_client.get(f"{EXPORT_URL}?categoria=abc")
        )
        assert invalid.max_row == 1

    def test_category_and_status_filters_combine_in_both_modes(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_CAT_STATUS")
        chd_rnm = PendingItemType.objects.get(slug="chd-rnm")
        active = _make_typed_item(
            admission, chd_rnm, description="marcador-cat-ativa"
        )
        finalized = _make_typed_item(
            admission, chd_rnm, description="marcador-cat-finalizada"
        )
        PendingItem.objects.filter(pk=finalized.pk).update(
            status=STATUS_RESOLVED,
            finalized_at=_dt("2026-06-11T10:00:00"),
        )
        category = chd_rnm.category_id
        for view in ("patients", "items"):
            default = _workbook(
                reader_client.get(
                    f"{EXPORT_URL}?view={view}&categoria={category}"
                )
            )
            assert default.max_row == 2
            assert [row[COLUMN["ID da pendência"]] for row in _rows(default)] == [
                active.pk
            ]
            everything = _workbook(
                reader_client.get(
                    f"{EXPORT_URL}?view={view}"
                    f"&categoria={category}&status=all"
                )
            )
            assert sorted(
                row[COLUMN["ID da pendência"]] for row in _rows(everything)
            ) == sorted([active.pk, finalized.pk])

    def test_confirmed_exit_leaves_panel_indicators_and_workbook(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_EXP_EXIT")
        item = _make_item(admission, description="marcador-saida-confirmada")
        _make_typed_item(
            _eligible_admission("P_EXP_EXIT_KEEP"),
            PendingItemType.objects.get(slug=OUTRO_SLUG),
            description="marcador-permanece",
        )
        Admission.objects.filter(pk=admission.pk).update(
            discharge_date=_dt("2026-06-12T10:00:00")
        )
        for query in ("", "?status=all"):
            panel = reader_client.get(f"/pendencias/{query}").content.decode()
            assert "marcador-saida-confirmada" not in panel
            assert "marcador-permanece" in panel
            workbook = _workbook(reader_client.get(f"{EXPORT_URL}{query}"))
            assert "marcador-saida-confirmada" not in _descriptions(workbook)
            assert "marcador-permanece" in _descriptions(workbook)
        assert 'data-testid="indicators-patients">1<' in panel
        context_url = f"/admissions/{admission.pk}/pending-items/"
        context = reader_client.get(context_url).content.decode()
        assert "marcador-saida-confirmada" in context
        history = reader_client.get(
            f"/pendencias/{item.pk}/history/",
            headers={"HX-Request": "true"},
        )
        assert history.status_code == 200
        assert "PACIENTE SINTETICO P_EXP_EXIT" in history.content.decode()


@pytest.mark.django_db
class TestExportConfirmedExit:
    """R3: a real confirmed exit removes the episode from the current cut.

    Separate evidence from the isolated Sistema-label serialization: the
    discharge boundary (not a direct column update) closes the actives,
    the episode leaves the current XLSX even with ``status=all`` and its
    contextual history stays readable. The admission is never reopened
    and the export cut is never widened.
    """

    def test_real_confirmed_exit_excluded_from_current_xlsx(
        self, reader_client: Client
    ) -> None:
        exited = _eligible_admission("P_EXP_REAL_EXIT")
        exited_item = _make_item(exited, description="marcador-saida-real")
        kept = _eligible_admission("P_EXP_REAL_KEEP", leito="L02")
        _make_item(kept, description="marcador-fica-real")
        exit_at = _dt("2026-06-12T10:00:00")

        evidence = DischargeExitEvidence(
            patient_record=exited.patient.patient_source_key,
            exit_datetime=exit_at,
            admission_key=exited.source_admission_key,
        )
        decision = decide_discharge_match(evidence=evidence)
        assert decision.admission is not None
        assert decision.admission.pk == exited.pk
        apply_discharge_exit(
            decision=decision,
            exit_datetime=exit_at,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind=EVIDENCE_SOURCE_DISCHARGE_RECORD,
            source_id=42,
        )

        exited.refresh_from_db()
        assert exited.discharge_date is not None
        assert Admission.objects.filter(
            patient_id=exited.patient_id, discharge_date__isnull=True
        ).count() == 0
        exited_item.refresh_from_db()
        assert exited_item.status == STATUS_CLOSED_UNRESOLVED
        assert exited_item.is_system_updated is True
        assert exited_item.updated_by_name == "Sistema"

        for query in ("", "?status=all", "?view=items&status=all"):
            workbook = _workbook(reader_client.get(f"{EXPORT_URL}{query}"))
            found = _descriptions(workbook)
            assert "marcador-saida-real" not in found, query
            assert "marcador-fica-real" in found, query
            panel = reader_client.get(f"/pendencias/{query}").content.decode()
            assert "marcador-saida-real" not in panel, query
            assert "marcador-fica-real" in panel, query

        context = reader_client.get(
            f"/admissions/{exited.pk}/pending-items/"
        ).content.decode()
        assert "marcador-saida-real" in context
        history = reader_client.get(
            f"/pendencias/{exited_item.pk}/history/",
            headers={"HX-Request": "true"},
        )
        assert history.status_code == 200
        history_body = history.content.decode()
        assert "PACIENTE SINTETICO P_EXP_REAL_EXIT" in history_body
        assert "Sistema" in history_body
