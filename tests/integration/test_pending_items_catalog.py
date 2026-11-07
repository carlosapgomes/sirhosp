"""STRUCT-PEND-S1: canonical catalog (R1) and the D8 load matrix (R3).

``TestFreshDatabaseCatalog`` reads the catalog a migrated database
received. ``TestCatalogLoadMatrix`` moves the ``pending_items`` app back
to ``0002_bootstrap_outro_group`` (the pre-change shape), seeds a
synthetic historical state, and migrates forward so the real data
migration has to decide every row of the D8 matrix.

All fixtures are synthetic; no production source is ever contacted.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps as django_apps
from django.contrib.auth.models import Group
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.patients.models import Admission, Patient
from apps.pending_items.catalog import CatalogLoadError, load_pending_item_catalog
from apps.pending_items.models import (
    CATEGORY_SLUG_OUTRAS_PENDENCIAS,
    GROUP_NAME,
    OUTRO_NAME,
    OUTRO_SLUG,
    PendingItem,
    PendingItemCategory,
    PendingItemRevision,
    PendingItemType,
)

TZ = ZoneInfo("America/Bahia")
BASE_MIGRATION = ("pending_items", "0002_bootstrap_outro_group")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


EXPECTED_CATEGORIES = sorted(
    [
        ("centro-cirurgico", "Centro Cirúrgico"),
        ("exames-imagem", "Exames de imagem"),
        ("chd", "CHD (Centro de Hemorragia Digestiva)"),
        ("hemodinamica", "Hemodinâmica"),
        ("radiointervencao", "Radiointervenção"),
        ("quadro-clinico", "Quadro clínico"),
        ("controle-infeccioso", "Controle infeccioso"),
        ("regulacao", "Regulação"),
        ("sumario-alta", "Sumário de alta"),
        ("outras-pendencias", "Outras pendências"),
    ]
)

EXPECTED_TYPES = sorted(
    [
        # Centro Cirúrgico
        ("cc-cirurgia", "Cirurgia", "centro-cirurgico", "agendamento", False, False),
        (
            "cc-procedimentos",
            "Procedimentos",
            "centro-cirurgico",
            "agendamento",
            False,
            False,
        ),
        # Exames de imagem
        (
            "imagem-tomografia",
            "Tomografia",
            "exames-imagem",
            "agendamento",
            False,
            False,
        ),
        ("imagem-rnm", "RNM", "exames-imagem", "agendamento", True, False),
        ("imagem-cprm", "CPRM", "exames-imagem", "agendamento", False, False),
        ("imagem-usg", "USG", "exames-imagem", "agendamento", False, False),
        ("imagem-eco-tt", "ECO TT", "exames-imagem", "agendamento", False, False),
        ("imagem-eco-te", "ECO TE", "exames-imagem", "agendamento", False, False),
        # CHD
        ("chd-cpre", "CPRE", "chd", "agendamento", False, False),
        ("chd-ecoeda", "EcoEDA", "chd", "agendamento", False, False),
        ("chd-eda", "EDA", "chd", "agendamento", False, False),
        (
            "chd-eda-dilatacao",
            "EDA + dilatação",
            "chd",
            "agendamento",
            False,
            False,
        ),
        (
            "chd-eda-troca-protese",
            "EDA + troca de prótese",
            "chd",
            "agendamento",
            False,
            False,
        ),
        ("chd-gtt", "GTT", "chd", "agendamento", False, False),
        ("chd-colonoscopia", "Colonoscopia", "chd", "agendamento", False, False),
        (
            "chd-retossigmoidoscopia",
            "Retossigmoidoscopia",
            "chd",
            "agendamento",
            False,
            False,
        ),
        ("chd-rnm", "RNM", "chd", "agendamento", True, False),
        # Hemodinâmica
        (
            "hemo-arteriografia",
            "Arteriografia",
            "hemodinamica",
            "agendamento",
            False,
            False,
        ),
        (
            "hemo-flebografia",
            "Flebografia",
            "hemodinamica",
            "agendamento",
            False,
            False,
        ),
        ("hemo-cate", "CATE", "hemodinamica", "agendamento", False, False),
        (
            "hemo-embolizacao",
            "Embolização",
            "hemodinamica",
            "agendamento",
            False,
            False,
        ),
        (
            "hemo-angioplastia",
            "Angioplastia",
            "hemodinamica",
            "agendamento",
            False,
            False,
        ),
        # Radiointervenção
        (
            "radio-biopsia",
            "Biópsia",
            "radiointervencao",
            "agendamento",
            False,
            False,
        ),
        (
            "radio-drenagem",
            "Drenagem de abscesso/coleção",
            "radiointervencao",
            "agendamento",
            False,
            False,
        ),
        # Quadro clínico
        (
            "quadro-melhora-clinica",
            "Melhora clínica",
            "quadro-clinico",
            "registro-simples",
            False,
            False,
        ),
        (
            "quadro-risco-obito",
            "Risco de óbito",
            "quadro-clinico",
            "registro-simples",
            False,
            False,
        ),
        (
            "quadro-quimioterapia",
            "Quimioterapia",
            "quadro-clinico",
            "registro-simples",
            False,
            False,
        ),
        # Controle infeccioso
        (
            "infeccioso-antibioticos",
            "Antibióticos",
            "controle-infeccioso",
            "tratamento-periodo",
            False,
            False,
        ),
        (
            "infeccioso-antifungicos",
            "Antifúngicos",
            "controle-infeccioso",
            "tratamento-periodo",
            False,
            False,
        ),
        (
            "infeccioso-cultura-antibiograma",
            "Cultura / Antibiograma",
            "controle-infeccioso",
            "registro-simples",
            False,
            False,
        ),
        (
            "infeccioso-painel-viral",
            "Painel viral",
            "controle-infeccioso",
            "registro-simples",
            False,
            False,
        ),
        # Regulação
        (
            "regulacao-cirurgia-cardiaca",
            "Cirurgia cardíaca",
            "regulacao",
            "registro-simples",
            False,
            False,
        ),
        (
            "regulacao-ortopedia",
            "Ortopedia",
            "regulacao",
            "registro-simples",
            False,
            False,
        ),
        (
            "regulacao-paliacao",
            "Paliação",
            "regulacao",
            "registro-simples",
            False,
            False,
        ),
        (
            "regulacao-cronicos",
            "Crônicos",
            "regulacao",
            "registro-simples",
            False,
            False,
        ),
        (
            "regulacao-contra-referencia",
            "Contra-referência",
            "regulacao",
            "registro-simples",
            False,
            False,
        ),
        (
            "regulacao-outros",
            "Outros",
            "regulacao",
            "registro-simples",
            False,
            True,
        ),
        # Sumário de alta
        (
            "sumario-assinatura",
            "Assinatura do sumário de alta",
            "sumario-alta",
            "assinatura-documento",
            False,
            False,
        ),
        # Outras pendências
        (
            "outras-definicao-conduta",
            "Definição de conduta médica",
            "outras-pendencias",
            "registro-simples",
            False,
            False,
        ),
        (
            "outras-relatorio-ad",
            "Relatório para Atenção Domiciliar",
            "outras-pendencias",
            "registro-simples",
            False,
            False,
        ),
        (
            "outras-interconsultas",
            "Interconsultas",
            "outras-pendencias",
            "registro-simples",
            False,
            False,
        ),
        (
            "outras-agendamento-externo",
            "Agendamento de exames externos",
            "outras-pendencias",
            "registro-simples",
            False,
            False,
        ),
        (
            "outras-resultado-externo",
            "Resultado de exames externos",
            "outras-pendencias",
            "registro-simples",
            False,
            False,
        ),
        (
            "outras-aquisicao",
            "Aquisição de material/medicamento",
            "outras-pendencias",
            "registro-simples",
            False,
            False,
        ),
        (
            "outras-hemodialise-acesso",
            "Hemodiálise para teste de acesso",
            "outras-pendencias",
            "registro-simples",
            False,
            False,
        ),
        (
            "outro",
            "Outro",
            "outras-pendencias",
            "registro-simples",
            False,
            True,
        ),
    ]
)


def _leaf_node() -> tuple[str, str]:
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    return executor.loader.graph.leaf_nodes("pending_items")[0]


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([target])
    executor.loader.build_graph()
    return executor


def _clear_pending_items_rows() -> None:
    """Empty the pending-items tables before reversing the catalog schema.

    Reversing ``0003`` restores the global unique type name, so the
    load-matrix tests must clear the catalog (except the protected
    ``Outro``) before migrating back.
    """
    PendingItemRevision.objects.all().delete()
    PendingItem.objects.all().delete()
    PendingItemType.objects.exclude(slug=OUTRO_SLUG).delete()


def _reset_to_base_state():
    """Migrate back to 0002 and return its app registry with a clean base."""
    _clear_pending_items_rows()
    executor = _migrate(BASE_MIGRATION)
    apps = executor.loader.project_state([BASE_MIGRATION]).apps
    ItemType = apps.get_model("pending_items", "PendingItemType")
    ItemType.objects.all().delete()
    Group.objects.get_or_create(name=GROUP_NAME)
    ItemType.objects.create(slug=OUTRO_SLUG, name=OUTRO_NAME)
    return apps


def _make_admission(key: str) -> Admission:
    patient = Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE SINTETICO {key}",
    )
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=f"ADM_{key}",
        admission_date=_dt("2026-06-01T08:00:00"),
    )


@pytest.mark.django_db
class TestFreshDatabaseCatalog:
    def test_new_database_receives_exact_catalog(self) -> None:
        slugs = list(
            PendingItemType.objects.order_by("slug").values_list("slug", flat=True)
        )
        assert slugs == [row[0] for row in EXPECTED_TYPES]

        categories = list(
            PendingItemCategory.objects.order_by("slug").values_list("slug", "name")
        )
        assert categories == EXPECTED_CATEGORIES

        rows = sorted(
            PendingItemType.objects.values_list(
                "slug",
                "name",
                "category__slug",
                "profile",
                "has_rnm_complements",
                "requires_description",
            )
        )
        assert rows == EXPECTED_TYPES

    def test_cate_is_unique_and_both_rnm_entries_are_distinct(self) -> None:
        cate = list(PendingItemType.objects.filter(name="CATE"))
        assert len(cate) == 1
        assert cate[0].category.slug == "hemodinamica"

        rnm = list(
            PendingItemType.objects.filter(name="RNM").select_related("category")
        )
        assert {entry.category.slug for entry in rnm} == {"exames-imagem", "chd"}
        assert len({entry.slug for entry in rnm}) == 2
        assert all(entry.profile == "agendamento" for entry in rnm)
        assert all(entry.has_rnm_complements for entry in rnm)

    def test_outro_contract_and_relationship_are_canonical(self) -> None:
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        assert outro.name == OUTRO_NAME
        assert outro.category.slug == CATEGORY_SLUG_OUTRAS_PENDENCIAS
        assert outro.profile == "registro-simples"
        assert outro.has_rnm_complements is False
        assert outro.requires_description is True


@pytest.mark.django_db(transaction=True)
class TestCatalogLoadMatrix:
    @pytest.fixture(autouse=True)
    def _canonical_catalog_after_test(self):
        yield
        _reset_to_base_state()
        _migrate(_leaf_node())

    def test_initial_context_creates_entries_without_legacy_state(self) -> None:
        _reset_to_base_state()
        _migrate(_leaf_node())
        assert PendingItemCategory.objects.count() == 10
        assert PendingItemType.objects.count() == 46
        created = PendingItemType.objects.get(slug="cc-cirurgia")
        assert created.category.slug == "centro-cirurgico"
        assert created.profile == "agendamento"
        assert created.has_rnm_complements is False
        assert created.requires_description is False

    def test_initial_context_adopts_exact_slug_and_name(self) -> None:
        apps = _reset_to_base_state()
        ItemType = apps.get_model("pending_items", "PendingItemType")
        Item = apps.get_model("pending_items", "PendingItem")
        Revision = apps.get_model("pending_items", "PendingItemRevision")
        admission = _make_admission("P_S1_ADOPT")
        legacy = ItemType.objects.create(slug="imagem-tomografia", name="Tomografia")
        item = Item.objects.create(
            admission_id=admission.pk,
            item_type_id=legacy.pk,
            description="pendencia legada sintetica",
            status="active",
            version=1,
        )
        Revision.objects.create(
            item_id=item.pk,
            version=1,
            action="created",
            item_type_id=legacy.pk,
            type_name="Tomografia",
            description="pendencia legada sintetica",
            status="active",
        )
        legacy_pk = legacy.pk

        _migrate(_leaf_node())

        adopted = PendingItemType.objects.get(slug="imagem-tomografia")
        assert adopted.pk == legacy_pk
        assert adopted.name == "Tomografia"
        assert adopted.category.slug == "exames-imagem"
        assert adopted.profile == "agendamento"
        assert adopted.has_rnm_complements is False

        preserved_item = PendingItem.objects.get(pk=item.pk)
        assert preserved_item.item_type_id == legacy_pk
        assert preserved_item.description == "pendencia legada sintetica"
        revision = PendingItemRevision.objects.get(item_id=item.pk, version=1)
        assert revision.type_name == "Tomografia"
        assert revision.category_name is None
        assert revision.category_slug is None
        assert revision.profile is None
        assert revision.has_rnm_complements is None
        assert revision.requires_description is None

    def test_initial_context_rejects_reserved_slug_with_divergent_name(
        self,
    ) -> None:
        apps = _reset_to_base_state()
        ItemType = apps.get_model("pending_items", "PendingItemType")
        legacy = ItemType.objects.create(
            slug="imagem-tomografia", name="Tomografia Legada"
        )
        legacy_pk = legacy.pk

        with pytest.raises(CatalogLoadError):
            _migrate(_leaf_node())

        assert PendingItemCategory.objects.count() == 0
        unchanged = PendingItemType.objects.get(pk=legacy_pk)
        assert unchanged.name == "Tomografia Legada"
        assert unchanged.category_id is None

    def test_initial_context_preserves_homonym_with_other_slug(self) -> None:
        apps = _reset_to_base_state()
        ItemType = apps.get_model("pending_items", "PendingItemType")
        legacy = ItemType.objects.create(slug="tomografia-antiga", name="Tomografia")
        legacy_pk = legacy.pk

        _migrate(_leaf_node())

        preserved = PendingItemType.objects.get(pk=legacy_pk)
        assert preserved.slug == "tomografia-antiga"
        assert preserved.category.slug == CATEGORY_SLUG_OUTRAS_PENDENCIAS
        assert preserved.profile == "registro-simples"
        assert preserved.has_rnm_complements is False
        assert preserved.requires_description is False

        canonical = PendingItemType.objects.get(slug="imagem-tomografia")
        assert canonical.pk != legacy_pk
        assert canonical.category.slug == "exames-imagem"

    def test_initial_context_rejects_collision_with_preserved_type(self) -> None:
        apps = _reset_to_base_state()
        ItemType = apps.get_model("pending_items", "PendingItemType")
        legacy = ItemType.objects.create(
            slug="interconsultas-antigas", name="Interconsultas"
        )
        legacy_pk = legacy.pk

        with pytest.raises(CatalogLoadError):
            _migrate(_leaf_node())

        assert PendingItemCategory.objects.count() == 0
        unchanged = PendingItemType.objects.get(pk=legacy_pk)
        assert unchanged.name == "Interconsultas"
        assert unchanged.slug == "interconsultas-antigas"
        assert unchanged.category_id is None

    def test_initial_context_preserves_unmatched_type(self) -> None:
        apps = _reset_to_base_state()
        ItemType = apps.get_model("pending_items", "PendingItemType")
        legacy = ItemType.objects.create(slug="legado-x", name="Tipo Legado")
        legacy_pk = legacy.pk

        _migrate(_leaf_node())

        preserved = PendingItemType.objects.get(pk=legacy_pk)
        assert preserved.name == "Tipo Legado"
        assert preserved.slug == "legado-x"
        assert preserved.category.slug == CATEGORY_SLUG_OUTRAS_PENDENCIAS
        assert preserved.profile == "registro-simples"
        assert preserved.has_rnm_complements is False
        assert preserved.requires_description is False

    def test_reapply_preserves_renamed_and_customized_entries(self) -> None:
        _reset_to_base_state()
        _migrate(_leaf_node())
        renamed = PendingItemType.objects.get(slug="quadro-quimioterapia")
        renamed.name = "Quimioterapia Renomeada"
        renamed.save()
        customized = PendingItemType.objects.get(slug="imagem-usg")
        customized.requires_description = True
        customized.save()
        before = PendingItemType.objects.count()

        load_pending_item_catalog(django_apps, initial=False)

        assert PendingItemType.objects.count() == before
        kept_rename = PendingItemType.objects.get(slug="quadro-quimioterapia")
        assert kept_rename.name == "Quimioterapia Renomeada"
        kept_contract = PendingItemType.objects.get(slug="imagem-usg")
        assert kept_contract.requires_description is True
        assert kept_contract.category.slug == "exames-imagem"

    def test_reapply_recreates_missing_slug_without_collision(self) -> None:
        _reset_to_base_state()
        _migrate(_leaf_node())
        removed = PendingItemType.objects.get(slug="imagem-eco-te")
        old_pk = removed.pk
        removed.delete()

        load_pending_item_catalog(django_apps, initial=False)

        recreated = PendingItemType.objects.get(slug="imagem-eco-te")
        assert recreated.pk != old_pk
        assert recreated.category.slug == "exames-imagem"
        assert recreated.profile == "agendamento"

    def test_reapply_rejects_missing_slug_with_name_collision(self) -> None:
        _reset_to_base_state()
        _migrate(_leaf_node())
        category = PendingItemCategory.objects.get(slug="quadro-clinico")
        PendingItemType.objects.get(slug="quadro-quimioterapia").delete()
        PendingItemType.objects.create(
            slug="quimio-antiga",
            name="Quimioterapia",
            category=category,
            profile="registro-simples",
        )

        with pytest.raises(CatalogLoadError):
            load_pending_item_catalog(django_apps, initial=False)

        assert not PendingItemType.objects.filter(
            slug="quadro-quimioterapia"
        ).exists()
        assert PendingItemType.objects.filter(slug="quimio-antiga").exists()

    def test_reapply_rejects_inconsistent_outro_contract(self) -> None:
        _reset_to_base_state()
        _migrate(_leaf_node())
        PendingItemType.objects.filter(slug=OUTRO_SLUG).update(profile="agendamento")

        with pytest.raises(CatalogLoadError):
            load_pending_item_catalog(django_apps, initial=False)

        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        assert outro.profile == "agendamento"

    def test_initial_context_rejects_divergent_category_name(self) -> None:
        _reset_to_base_state()
        _migrate(_leaf_node())
        PendingItemCategory.objects.filter(slug="chd").update(
            name="Categoria Divergente"
        )

        with pytest.raises(CatalogLoadError):
            load_pending_item_catalog(django_apps, initial=True)

    def test_initial_context_rejects_category_name_owned_by_other_slug(
        self,
    ) -> None:
        _reset_to_base_state()
        _migrate(_leaf_node())
        PendingItemCategory.objects.filter(slug="sumario-alta").update(
            slug="sumario-renomeado"
        )

        with pytest.raises(CatalogLoadError):
            load_pending_item_catalog(django_apps, initial=True)
