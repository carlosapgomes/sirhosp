"""PEND-S3: aggregate panel HTTP integration (R1-R6 over /pendencias/).

Failing-before: no ``pendencias`` route exists in
``apps/pending_items/urls.py`` and the sidebar has no Pendências entry,
so every aggregate GET below 404s until the slice is implemented.

Covers menu/active context, the conservative cut in both views with
group-atomic pagination, filters, first unit, indicators, modal edit
reusing the contextual service, on-demand history, cache directives,
escaping, GET purity and a relative query budget. All synthetic.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot, PatientMovement
from apps.patients.models import Admission, Patient
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
from apps.pending_items.services import CONFLICT_MESSAGE

TZ = ZoneInfo("America/Bahia")


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


def _make_movement(
    patient: Patient,
    *,
    admission: Admission | None,
    sector: str,
    movement_date: str,
    sequence: int = 0,
) -> PatientMovement:
    day = datetime.strptime(movement_date, "%Y-%m-%d").date()
    return PatientMovement.objects.create(
        patient=patient,
        admission=admission,
        movement_date=day,
        sector=sector,
        sequence=sequence,
        first_seen_at=_dt("2026-06-01T08:00:00"),
        last_seen_at=_dt("2026-06-01T08:00:00"),
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


def _eligible_admission(
    key: str = "P_PORTAL_1",
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


@pytest.fixture
def writer_client(client: Client, db: object) -> Client:
    user = User.objects.create_user(username="portal_writer", password="pw123456")
    Group.objects.get(name="Desospitalização").user_set.add(user)
    client.login(username="portal_writer", password="pw123456")
    return client


@pytest.fixture
def reader_client(client: Client, db: object) -> Client:
    User.objects.create_user(username="portal_reader", password="pw123456")
    client.login(username="portal_reader", password="pw123456")
    return client


def _cache_directives(response) -> set[str]:
    header = response.headers.get("Cache-Control", "")
    return {part.strip().lower() for part in header.split(",") if part.strip()}


def _assert_private_no_store(response) -> None:
    directives = _cache_directives(response)
    assert "private" in directives
    assert "no-store" in directives


@pytest.mark.django_db
class TestAggregateAccess:
    def test_anonymous_redirected_on_every_surface(
        self, client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_ANON")
        item = _make_item(admission, description="anonima")
        for url in (
            "/pendencias/",
            f"/pendencias/{item.pk}/history/",
            f"/pendencias/{item.pk}/edit/",
            f"/pendencias/{item.pk}/finalize/",
        ):
            response = client.get(url)
            assert response.status_code == 302
            assert "/login/" in response.url  # type: ignore[attr-defined]
            assert b"anonima" not in response.content
        posted = client.post(
            f"/pendencias/{item.pk}/edit/",
            {"item_type": "1", "description": "x", "expected_version": "1"},
        )
        assert posted.status_code == 302

    def test_reader_reads_without_write_actions(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_READ")
        _make_item(admission, description="leitura agregada")
        response = reader_client.get("/pendencias/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "leitura agregada" in content
        assert "pending-edit-" not in content
        assert "pending-finalize-" not in content
        assert "pending-history-" in content

    def test_menu_link_and_active_context(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_MENU")
        _make_item(admission, description="menu")
        response = writer_client.get("/pendencias/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Pendências" in content
        assert (
            'href="/pendencias/" '
            'class="sirhosp-sidebar-link active"' in content
        )
        items = writer_client.get("/pendencias/?view=items").content.decode()
        assert (
            'href="/pendencias/" '
            'class="sirhosp-sidebar-link active"' in items
        )


@pytest.mark.django_db
class TestAggregateCut:
    def test_default_shows_only_current_actives(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_CUT1")
        old = _make_admission(
            admission.patient, "ADM_PORTAL_CUT1_OLD",
            end="2026-05-02T10:00:00",
        )
        _make_item(admission, description="ativa atual")
        _make_item(
            admission, description="resolvida atual",
            status=STATUS_RESOLVED,
            finalized_at=_dt("2026-06-11T10:00:00"),
        )
        _make_item(old, description="ativa antiga")
        content = writer_client.get("/pendencias/").content.decode()
        assert "ativa atual" in content
        assert "resolvida atual" not in content
        assert "ativa antiga" not in content

    def test_status_all_still_excludes_previous_episodes(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_CUT2")
        old = _make_admission(
            admission.patient, "ADM_PORTAL_CUT2_OLD",
            end="2026-05-02T10:00:00",
        )
        _make_item(
            admission, description="resolvida atual",
            status=STATUS_RESOLVED,
            finalized_at=_dt("2026-06-11T10:00:00"),
        )
        _make_item(old, description="ativa antiga")
        for view in ("patients", "items"):
            content = writer_client.get(
                f"/pendencias/?view={view}&status=all"
            ).content.decode()
            assert "resolvida atual" in content
            assert "ativa antiga" not in content

    def test_ambiguous_cases_excluded_in_both_views(
        self, writer_client: Client
    ) -> None:
        conflict = _make_patient("P_PORTAL_AMB1")
        adm_conflict = _make_admission(conflict, "ADM_PORTAL_AMB1")
        _make_census_row("P_PORTAL_AMB1", setor="UTI", leito="U01")
        _make_census_row("P_PORTAL_AMB1", setor="ENF", leito="E02")
        _make_item(adm_conflict, description="leitos conflitantes")
        two = _make_patient("P_PORTAL_AMB2")
        adm_two = _make_admission(two, "ADM_PORTAL_AMB2_A")
        _make_admission(two, "ADM_PORTAL_AMB2_B")
        _make_census_row("P_PORTAL_AMB2")
        _make_item(adm_two, description="duas abertas")
        valid = _eligible_admission("P_PORTAL_AMB3")
        _make_item(valid, description="valida")
        for view in ("patients", "items"):
            content = writer_client.get(
                f"/pendencias/?view={view}&status=all"
            ).content.decode()
            assert "leitos conflitantes" not in content
            assert "duas abertas" not in content
            assert "valida" in content

    def test_equivalent_repetition_enters_once(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_REP")
        _make_census_row("P_PORTAL_REP")
        _make_item(admission, description="repeticao equivalente")
        for view in ("patients", "items"):
            content = writer_client.get(
                f"/pendencias/?view={view}"
            ).content.decode()
            assert content.count("repeticao equivalente") == 1

    def test_no_census_renders_empty_state(
        self, writer_client: Client
    ) -> None:
        patient = _make_patient("P_PORTAL_NOCENSUS")
        admission = _make_admission(patient, "ADM_PORTAL_NOCENSUS")
        _make_item(admission, description="sem foto")
        response = writer_client.get("/pendencias/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "sem foto" not in content
        assert "Nenhuma" in content or "nenhuma" in content

    def test_patients_view_pagination_never_splits_groups(
        self, writer_client: Client
    ) -> None:
        for index in range(AGGREGATE_PER_PAGE):
            admission = _eligible_admission(
                f"P_PORTAL_PG{index:02d}", leito=f"L{index:02d}"
            )
            _make_item(admission, description=f"grupo-{index:02d}")
        last = _eligible_admission("P_PORTAL_PGLAST", leito="LZ")
        for suffix in ("a", "b", "c"):
            _make_item(last, description=f"grupo-final-{suffix}")
        page1 = writer_client.get("/pendencias/?page=1").content.decode()
        assert "grupo-final-a" not in page1
        page2 = writer_client.get("/pendencias/?page=2").content.decode()
        assert "grupo-final-a" in page2
        assert "grupo-final-b" in page2
        assert "grupo-final-c" in page2

    def test_items_view_paginates_by_item(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_PI")
        for index in range(AGGREGATE_PER_PAGE + 1):
            _make_item(admission, description=f"item-{index:02d}")
        page1 = writer_client.get(
            "/pendencias/?view=items&page=1"
        ).content.decode()
        assert f"item-{AGGREGATE_PER_PAGE:02d}" not in page1
        page2 = writer_client.get(
            "/pendencias/?view=items&page=2"
        ).content.decode()
        assert f"item-{AGGREGATE_PER_PAGE:02d}" in page2

    def test_view_toggle_preserves_filters(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission(
            "P_PORTAL_TOG", setor="UTI", especialidade="CIV"
        )
        _make_item(admission, description="alternancia")
        content = writer_client.get(
            "/pendencias/?view=patients&status=all&unidade=UTI"
        ).content.decode()
        assert "alternancia" in content
        assert "view=items" in content
        assert "status=all" in content
        assert "unidade=UTI" in content


@pytest.mark.django_db
class TestAggregateFiltersHttp:
    def test_combined_unit_and_bed_filter(
        self, writer_client: Client
    ) -> None:
        first = _eligible_admission(
            "P_PORTAL_FF1", setor="UTI", leito="U01"
        )
        second = _eligible_admission(
            "P_PORTAL_FF2", setor="UTI", leito="U02"
        )
        _make_item(first, description="leito um")
        _make_item(second, description="leito dois")
        content = writer_client.get(
            "/pendencias/?unidade=UTI&leito=U02"
        ).content.decode()
        assert "leito um" not in content
        assert "leito dois" in content

    def test_system_updater_filter(self, writer_client: Client) -> None:
        admission = _eligible_admission("P_PORTAL_FF3")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description="encerrada automatica",
            status=STATUS_CLOSED_UNRESOLVED,
            version=2,
            finalized_at=_dt("2026-06-11T10:00:00"),
            updated_by=None,
            updated_by_name="Sistema",
            is_system_updated=True,
        )
        _make_item(admission, description="ativa humana")
        content = writer_client.get(
            "/pendencias/?status=all&atualizador=system"
        ).content.decode()
        assert "encerrada automatica" in content
        assert "ativa humana" not in content

    def test_invalid_time_bounds_show_error_and_empty_list(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_FF4")
        _make_item(admission, description="visivel sem filtro")
        response = writer_client.get("/pendencias/?min_dias=-2")
        assert response.status_code == 200
        content = response.content.decode()
        assert "visivel sem filtro" not in content
        assert "negativos" in content
        assert "Indicadores hospitalares" in content


@pytest.mark.django_db
class TestAggregateIndicatorsHttp:
    def _ages_scene(self) -> None:
        now = timezone.now()
        first = _eligible_admission("P_PORTAL_IND1")
        second = _eligible_admission("P_PORTAL_IND2")
        _make_item(
            first, description="dois dias",
            created_at=now - timedelta(days=2),
        )
        _make_item(
            first, description="oito dias",
            created_at=now - timedelta(days=8),
        )
        _make_item(
            second, description="cinco dias",
            created_at=now - timedelta(days=5),
        )

    def test_indicators_render_two_patients_mean_five_max_eight(
        self, writer_client: Client
    ) -> None:
        self._ages_scene()
        content = writer_client.get("/pendencias/").content.decode()
        assert "5,0 dias" in content
        assert "8,0 dias" in content

    def test_indicators_ignore_filters_mode_and_page(
        self, writer_client: Client
    ) -> None:
        self._ages_scene()
        plain = writer_client.get("/pendencias/").content.decode()
        filtered = writer_client.get(
            "/pendencias/?view=items&status=resolved&unidade=INEXISTENTE"
        ).content.decode()
        assert "dois dias" not in filtered
        for marker in ("5,0 dias", "8,0 dias"):
            assert marker in plain
            assert marker in filtered

    def test_zero_actives_show_zero_and_dashes(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_IND3")
        _make_item(
            admission, description="resolvida",
            status=STATUS_RESOLVED,
            finalized_at=_dt("2026-06-11T10:00:00"),
        )
        content = writer_client.get("/pendencias/").content.decode()
        assert "Nenhuma pendência ativa" in content
        assert "—" in content


@pytest.mark.django_db
class TestFirstUnitHttp:
    def test_ps_first_and_unknown_fallback_rendered(
        self, writer_client: Client
    ) -> None:
        tracked = _eligible_admission(
            "P_PORTAL_FU1", setor="ENFERMARIA 1", leito="E10"
        )
        _make_movement(
            tracked.patient, admission=None, sector="PRONTO SOCORRO",
            movement_date="2026-06-01",
        )
        _make_movement(
            tracked.patient, admission=None, sector="UTI GERAL",
            movement_date="2026-06-03",
        )
        _make_movement(
            tracked.patient, admission=None, sector="ENFERMARIA 1",
            movement_date="2026-06-05",
        )
        _make_item(tracked, description="com percurso")
        untracked = _eligible_admission("P_PORTAL_FU2")
        _make_item(untracked, description="sem percurso")
        for view in ("patients", "items"):
            content = writer_client.get(
                f"/pendencias/?view={view}"
            ).content.decode()
            assert "PRONTO SOCORRO" in content
            assert "Primeira unidade não identificada" in content
            assert "ENFERMARIA 1" in content


@pytest.mark.django_db
class TestAggregateEditHttp:
    def _post_payload(
        self, item: PendingItem, *, description: str = "editada portal"
    ) -> dict[str, str]:
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        return {
            "item_type": str(outro.pk),
            "description": description,
            "expected_version": str(item.version),
            "next": "/pendencias/?view=items&status=all",
        }

    def test_get_form_and_post_success_preserve_next(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_ED1")
        item = _make_item(admission, description="original portal")
        form = writer_client.get(f"/pendencias/{item.pk}/edit/")
        assert form.status_code == 200
        assert 'name="description"' in form.content.decode()
        response = writer_client.post(
            f"/pendencias/{item.pk}/edit/",
            self._post_payload(item),
        )
        assert response.status_code == 302
        assert response.url == "/pendencias/?view=items&status=all"  # type: ignore[attr-defined]
        item.refresh_from_db()
        assert item.description == "editada portal"
        assert item.version == 2
        assert PendingItemRevision.objects.filter(item=item).count() == 1

    def test_reader_cannot_get_or_post(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_ED2")
        item = _make_item(admission, description="protegida")
        assert reader_client.get(
            f"/pendencias/{item.pk}/edit/"
        ).status_code == 403
        response = reader_client.post(
            f"/pendencias/{item.pk}/edit/",
            self._post_payload(item),
        )
        assert response.status_code == 403
        item.refresh_from_db()
        assert item.description == "protegida"
        assert item.version == 1

    def test_stale_version_conflicts_without_overwrite(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_ED3")
        item = _make_item(admission, description="atual portal")
        PendingItem.objects.filter(pk=item.pk).update(version=2)
        payload = self._post_payload(item, description="tentativa antiga")
        payload["expected_version"] = "1"
        response = writer_client.post(
            f"/pendencias/{item.pk}/edit/", payload
        )
        assert response.status_code == 409
        content = response.content.decode()
        assert CONFLICT_MESSAGE in content
        assert "tentativa antiga" in content
        assert "sucesso" not in content.lower()
        item.refresh_from_db()
        assert item.description == "atual portal"
        assert item.version == 2

    def test_exit_during_open_modal_blocks_post(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_ED4")
        item = _make_item(admission, description="antes da saida")
        assert writer_client.get(
            f"/pendencias/{item.pk}/edit/"
        ).status_code == 200
        admission.discharge_date = _dt("2026-06-12T10:00:00")
        admission.save(update_fields=["discharge_date"])
        response = writer_client.post(
            f"/pendencias/{item.pk}/edit/",
            self._post_payload(item, description="depois da saida"),
        )
        assert response.status_code == 403
        item.refresh_from_db()
        assert item.description == "antes da saida"
        assert item.version == 1

    def test_lost_membership_blocks_post(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_ED5")
        item = _make_item(admission, description="antes da perda")
        Group.objects.get(name="Desospitalização").user_set.remove(
            User.objects.get(username="portal_writer")
        )
        response = writer_client.post(
            f"/pendencias/{item.pk}/edit/",
            self._post_payload(item),
        )
        assert response.status_code == 403
        item.refresh_from_db()
        assert item.description == "antes da perda"

    def test_finalized_item_has_no_form(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_ED6")
        item = _make_item(
            admission, description="finalizada portal",
            status=STATUS_RESOLVED,
            finalized_at=_dt("2026-06-11T10:00:00"),
        )
        form = writer_client.get(f"/pendencias/{item.pk}/edit/")
        assert form.status_code == 200
        assert 'name="description"' not in form.content.decode()
        response = writer_client.post(
            f"/pendencias/{item.pk}/edit/",
            self._post_payload(item),
        )
        assert response.status_code == 400
        item.refresh_from_db()
        assert item.description == "finalizada portal"

    def test_finalize_post_removes_item_from_actives(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_ED7")
        item = _make_item(admission, description="a finalizar portal")
        response = writer_client.post(
            f"/pendencias/{item.pk}/finalize/",
            {
                "target_status": STATUS_CLOSED_UNRESOLVED,
                "note": "",
                "expected_version": "1",
                "next": "/pendencias/",
            },
        )
        assert response.status_code == 302
        item.refresh_from_db()
        assert item.status == STATUS_CLOSED_UNRESOLVED
        content = writer_client.get("/pendencias/").content.decode()
        assert "a finalizar portal" not in content
        finalized = writer_client.get(
            "/pendencias/?status=closed_unresolved"
        ).content.decode()
        assert "a finalizar portal" in finalized

    def test_htmx_post_returns_redirect_without_false_success(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_ED8")
        item = _make_item(admission, description="htmx portal")
        fragment = writer_client.get(
            f"/pendencias/{item.pk}/edit/?next=/pendencias/",
            HTTP_HX_REQUEST="true",
        )
        assert fragment.status_code == 200
        assert b"<html" not in fragment.content
        assert 'name="description"' in fragment.content.decode()
        response = writer_client.post(
            f"/pendencias/{item.pk}/edit/",
            self._post_payload(item, description="htmx salva"),
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert response.headers.get("HX-Redirect") == (
            "/pendencias/?view=items&status=all"
        )
        item.refresh_from_db()
        assert item.description == "htmx salva"


@pytest.mark.django_db
class TestAggregateHistoryHttp:
    def test_reader_views_full_history_deterministically(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_H1")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        item = PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description="versao-dois-portal",
            status=STATUS_ACTIVE,
            version=2,
        )
        PendingItemRevision.objects.create(
            item=item, version=1, action="created", item_type=outro,
            type_name=outro.name, description="versao-um-portal",
            status=STATUS_ACTIVE,
        )
        PendingItemRevision.objects.create(
            item=item, version=2, action="updated", item_type=outro,
            type_name=outro.name, description="versao-dois-portal",
            status=STATUS_ACTIVE,
        )
        response = reader_client.get(f"/pendencias/{item.pk}/history/")
        assert response.status_code == 200
        content = response.content.decode()
        first = content.index("versao-um-portal")
        assert first < content.index("versao-dois-portal", first + 1)

    def test_htmx_history_is_on_demand_fragment(
        self, reader_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_H2")
        item = _make_item(admission, description="fragmento portal")
        PendingItemRevision.objects.create(
            item=item, version=1, action="created",
            item_type=item.item_type, type_name=item.item_type.name,
            description="fragmento portal", status=STATUS_ACTIVE,
        )
        PendingItemRevision.objects.filter(item=item, version=1).update(
            note="nota-somente-revisao-portal"
        )
        page = reader_client.get("/pendencias/")
        assert "fragmento portal" in page.content.decode()
        assert "nota-somente-revisao-portal" not in page.content.decode()
        fragment = reader_client.get(
            f"/pendencias/{item.pk}/history/", HTTP_HX_REQUEST="true"
        )
        assert fragment.status_code == 200
        assert b"<html" not in fragment.content
        assert "nota-somente-revisao-portal" in fragment.content.decode()


@pytest.mark.django_db
class TestAggregateCacheHeaders:
    def test_private_no_store_everywhere(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_CACHE")
        item = _make_item(admission, description="cache portal")
        page = writer_client.get("/pendencias/")
        assert page.status_code == 200
        _assert_private_no_store(page)
        history = writer_client.get(f"/pendencias/{item.pk}/history/")
        _assert_private_no_store(history)
        fragment = writer_client.get(
            f"/pendencias/{item.pk}/history/", HTTP_HX_REQUEST="true"
        )
        _assert_private_no_store(fragment)
        edit = writer_client.get(f"/pendencias/{item.pk}/edit/")
        _assert_private_no_store(edit)
        finalize = writer_client.get(f"/pendencias/{item.pk}/finalize/")
        _assert_private_no_store(finalize)
        error = writer_client.post(
            f"/pendencias/{item.pk}/edit/",
            {
                "item_type": "",
                "description": "",
                "expected_version": "1",
                "next": "/pendencias/",
            },
        )
        assert error.status_code == 200
        _assert_private_no_store(error)
        PendingItem.objects.filter(pk=item.pk).update(version=5)
        conflict = writer_client.post(
            f"/pendencias/{item.pk}/edit/",
            {
                "item_type": str(item.item_type_id),
                "description": "conflito cache",
                "expected_version": "1",
                "next": "/pendencias/",
            },
        )
        assert conflict.status_code == 409
        _assert_private_no_store(conflict)


@pytest.mark.django_db
class TestAggregateEscaping:
    def test_payload_is_escaped_on_panel_and_fragment(
        self, writer_client: Client
    ) -> None:
        admission = _eligible_admission("P_PORTAL_ESC")
        marker = "XSS-SINTETICO-7741"
        item = _make_item(
            admission, description=f"{marker}<script>alert('agg')</script>"
        )
        page = writer_client.get("/pendencias/")
        assert page.status_code == 200
        assert marker in page.content.decode()
        assert "&lt;script&gt;" in page.content.decode()
        assert "<script>alert" not in page.content.decode()
        PendingItemRevision.objects.create(
            item=item, version=1, action="created",
            item_type=item.item_type, type_name=item.item_type.name,
            description=item.description, status=STATUS_ACTIVE,
        )
        fragment = writer_client.get(
            f"/pendencias/{item.pk}/history/", HTTP_HX_REQUEST="true"
        )
        assert "&lt;script&gt;" in fragment.content.decode()
        assert "<script>alert" not in fragment.content.decode()


@pytest.mark.django_db
class TestAggregateGetPurity:
    def test_gets_never_mutate(self, writer_client: Client) -> None:
        admission = _eligible_admission("P_PORTAL_PURE")
        item = _make_item(admission, description="pura")
        before_items = PendingItem.objects.count()
        before_revisions = PendingItemRevision.objects.count()
        writer_client.get("/pendencias/?view=items&status=all")
        writer_client.get(f"/pendencias/{item.pk}/history/")
        writer_client.get(f"/pendencias/{item.pk}/edit/")
        writer_client.get(f"/pendencias/{item.pk}/finalize/")
        assert PendingItem.objects.count() == before_items
        assert PendingItemRevision.objects.count() == before_revisions
        item.refresh_from_db()
        assert item.description == "pura"
        assert item.version == 1


@pytest.mark.django_db
class TestAggregateQueryBudgetHttp:
    def _scene(self, count: int, prefix: str) -> None:
        for index in range(count):
            key = f"{prefix}{index}"
            admission = _eligible_admission(key, leito=f"L{index:02d}")
            _make_item(admission, description=f"orcamento {key}")
            _make_movement(
                admission.patient, admission=admission,
                sector="UTI GERAL", movement_date="2026-06-02",
            )

    def _get_cost(self, writer_client: Client) -> int:
        with CaptureQueriesContext(connection) as queries:
            response = writer_client.get("/pendencias/")
            assert response.status_code == 200
        return len(queries)

    def test_cost_does_not_grow_with_volume(
        self, writer_client: Client
    ) -> None:
        self._scene(2, "P_PORTAL_QA")
        small_cost = self._get_cost(writer_client)
        self._scene(6, "P_PORTAL_QB")
        big_cost = self._get_cost(writer_client)
        assert small_cost > 0
        assert big_cost <= small_cost
