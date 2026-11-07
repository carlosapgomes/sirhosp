"""Canonical pending-item catalog and its deterministic load (S1).

The catalog in ``openspec/changes/structure-inpatient-pending-items/
catalog.md`` is materialized here as the single source used by the
``0004`` data migration and by the D8 load-matrix tests. The loader
receives the Django app registry so it can run against historical
models during a migration and against the live models in tests.

``initial`` is the explicit operation context required by design D8:
it is true only for the first load, which is also the single authorized
initialization of classification metadata for preexisting types. A
reapplication always runs with ``initial=False`` and never reinterprets
a renamed catalog entry as an initial collision.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.pending_items.models import (
    CATEGORY_SLUG_OUTRAS_PENDENCIAS,
    OUTRO_NAME,
    OUTRO_SLUG,
    PROFILE_SCHEDULING,
    PROFILE_SIMPLE,
    PendingItemType,
)


@dataclass(frozen=True)
class CatalogCategory:
    """One canonical category: stable slug plus visible name."""

    slug: str
    name: str


@dataclass(frozen=True)
class CatalogType:
    """One canonical type with the contract approved in ``catalog.md``."""

    slug: str
    name: str
    category: str
    profile: str
    has_rnm_complements: bool = False
    requires_description: bool = False


CATALOG_CATEGORIES: tuple[CatalogCategory, ...] = (
    CatalogCategory("centro-cirurgico", "Centro Cirúrgico"),
    CatalogCategory("exames-imagem", "Exames de imagem"),
    CatalogCategory("chd", "CHD (Centro de Hemorragia Digestiva)"),
    CatalogCategory("hemodinamica", "Hemodinâmica"),
    CatalogCategory("radiointervencao", "Radiointervenção"),
    CatalogCategory("quadro-clinico", "Quadro clínico"),
    CatalogCategory("controle-infeccioso", "Controle infeccioso"),
    CatalogCategory("regulacao", "Regulação"),
    CatalogCategory("sumario-alta", "Sumário de alta"),
    CatalogCategory(CATEGORY_SLUG_OUTRAS_PENDENCIAS, "Outras pendências"),
)

CATALOG_TYPES: tuple[CatalogType, ...] = (
    CatalogType("cc-cirurgia", "Cirurgia", "centro-cirurgico", PROFILE_SCHEDULING),
    CatalogType(
        "cc-procedimentos", "Procedimentos", "centro-cirurgico", PROFILE_SCHEDULING
    ),
    CatalogType(
        "imagem-tomografia", "Tomografia", "exames-imagem", PROFILE_SCHEDULING
    ),
    CatalogType(
        "imagem-rnm",
        "RNM",
        "exames-imagem",
        PROFILE_SCHEDULING,
        has_rnm_complements=True,
    ),
    CatalogType("imagem-cprm", "CPRM", "exames-imagem", PROFILE_SCHEDULING),
    CatalogType("imagem-usg", "USG", "exames-imagem", PROFILE_SCHEDULING),
    CatalogType("imagem-eco-tt", "ECO TT", "exames-imagem", PROFILE_SCHEDULING),
    CatalogType("imagem-eco-te", "ECO TE", "exames-imagem", PROFILE_SCHEDULING),
    CatalogType("chd-cpre", "CPRE", "chd", PROFILE_SCHEDULING),
    CatalogType("chd-ecoeda", "EcoEDA", "chd", PROFILE_SCHEDULING),
    CatalogType("chd-eda", "EDA", "chd", PROFILE_SCHEDULING),
    CatalogType(
        "chd-eda-dilatacao", "EDA + dilatação", "chd", PROFILE_SCHEDULING
    ),
    CatalogType(
        "chd-eda-troca-protese",
        "EDA + troca de prótese",
        "chd",
        PROFILE_SCHEDULING,
    ),
    CatalogType("chd-gtt", "GTT", "chd", PROFILE_SCHEDULING),
    CatalogType("chd-colonoscopia", "Colonoscopia", "chd", PROFILE_SCHEDULING),
    CatalogType(
        "chd-retossigmoidoscopia", "Retossigmoidoscopia", "chd", PROFILE_SCHEDULING
    ),
    CatalogType(
        "chd-rnm",
        "RNM",
        "chd",
        PROFILE_SCHEDULING,
        has_rnm_complements=True,
    ),
    CatalogType(
        "hemo-arteriografia", "Arteriografia", "hemodinamica", PROFILE_SCHEDULING
    ),
    CatalogType(
        "hemo-flebografia", "Flebografia", "hemodinamica", PROFILE_SCHEDULING
    ),
    CatalogType("hemo-cate", "CATE", "hemodinamica", PROFILE_SCHEDULING),
    CatalogType(
        "hemo-embolizacao", "Embolização", "hemodinamica", PROFILE_SCHEDULING
    ),
    CatalogType(
        "hemo-angioplastia", "Angioplastia", "hemodinamica", PROFILE_SCHEDULING
    ),
    CatalogType("radio-biopsia", "Biópsia", "radiointervencao", PROFILE_SCHEDULING),
    CatalogType(
        "radio-drenagem",
        "Drenagem de abscesso/coleção",
        "radiointervencao",
        PROFILE_SCHEDULING,
    ),
    CatalogType(
        "quadro-melhora-clinica", "Melhora clínica", "quadro-clinico", PROFILE_SIMPLE
    ),
    CatalogType(
        "quadro-risco-obito", "Risco de óbito", "quadro-clinico", PROFILE_SIMPLE
    ),
    CatalogType(
        "quadro-quimioterapia", "Quimioterapia", "quadro-clinico", PROFILE_SIMPLE
    ),
    CatalogType(
        "infeccioso-antibioticos",
        "Antibióticos",
        "controle-infeccioso",
        "tratamento-periodo",
    ),
    CatalogType(
        "infeccioso-antifungicos",
        "Antifúngicos",
        "controle-infeccioso",
        "tratamento-periodo",
    ),
    CatalogType(
        "infeccioso-cultura-antibiograma",
        "Cultura / Antibiograma",
        "controle-infeccioso",
        PROFILE_SIMPLE,
    ),
    CatalogType(
        "infeccioso-painel-viral",
        "Painel viral",
        "controle-infeccioso",
        PROFILE_SIMPLE,
    ),
    CatalogType(
        "regulacao-cirurgia-cardiaca",
        "Cirurgia cardíaca",
        "regulacao",
        PROFILE_SIMPLE,
    ),
    CatalogType("regulacao-ortopedia", "Ortopedia", "regulacao", PROFILE_SIMPLE),
    CatalogType("regulacao-paliacao", "Paliação", "regulacao", PROFILE_SIMPLE),
    CatalogType("regulacao-cronicos", "Crônicos", "regulacao", PROFILE_SIMPLE),
    CatalogType(
        "regulacao-contra-referencia",
        "Contra-referência",
        "regulacao",
        PROFILE_SIMPLE,
    ),
    CatalogType(
        "regulacao-outros",
        "Outros",
        "regulacao",
        PROFILE_SIMPLE,
        requires_description=True,
    ),
    CatalogType(
        "sumario-assinatura",
        "Assinatura do sumário de alta",
        "sumario-alta",
        "assinatura-documento",
    ),
    CatalogType(
        "outras-definicao-conduta",
        "Definição de conduta médica",
        CATEGORY_SLUG_OUTRAS_PENDENCIAS,
        PROFILE_SIMPLE,
    ),
    CatalogType(
        "outras-relatorio-ad",
        "Relatório para Atenção Domiciliar",
        CATEGORY_SLUG_OUTRAS_PENDENCIAS,
        PROFILE_SIMPLE,
    ),
    CatalogType(
        "outras-interconsultas",
        "Interconsultas",
        CATEGORY_SLUG_OUTRAS_PENDENCIAS,
        PROFILE_SIMPLE,
    ),
    CatalogType(
        "outras-agendamento-externo",
        "Agendamento de exames externos",
        CATEGORY_SLUG_OUTRAS_PENDENCIAS,
        PROFILE_SIMPLE,
    ),
    CatalogType(
        "outras-resultado-externo",
        "Resultado de exames externos",
        CATEGORY_SLUG_OUTRAS_PENDENCIAS,
        PROFILE_SIMPLE,
    ),
    CatalogType(
        "outras-aquisicao",
        "Aquisição de material/medicamento",
        CATEGORY_SLUG_OUTRAS_PENDENCIAS,
        PROFILE_SIMPLE,
    ),
    CatalogType(
        "outras-hemodialise-acesso",
        "Hemodiálise para teste de acesso",
        CATEGORY_SLUG_OUTRAS_PENDENCIAS,
        PROFILE_SIMPLE,
    ),
    CatalogType(
        OUTRO_SLUG,
        OUTRO_NAME,
        CATEGORY_SLUG_OUTRAS_PENDENCIAS,
        PROFILE_SIMPLE,
        requires_description=True,
    ),
)


def type_display_label(item_type: PendingItemType) -> str:
    """Category-qualified type label shared by every selector.

    Homonymous catalog types (``RNM`` under two categories) are only
    distinguishable by their category, so forms and the aggregate filter
    must render the exact same text; this function is the single source
    of that format.
    """
    return f"{item_type.category.name} > {item_type.name}"


class CatalogLoadError(Exception):
    """The catalog seed cannot be applied without an explicit decision."""


def load_pending_item_catalog(apps, *, initial: bool) -> None:
    """Create or validate the canonical catalog in the given context.

    ``initial=True`` is the single authorized initialization of the
    classification metadata of preexisting types; it adopts a type only
    on an exact slug and name match and aborts on any reserved-slug
    divergence. ``initial=False`` recognizes entries by slug only and
    never restores defaults over a legitimate customization.

    The whole operation is atomic: a collision aborts before any catalog
    entry is written, and the raised diagnostic contains catalog
    identifiers only.
    """
    Category = apps.get_model("pending_items", "PendingItemCategory")
    ItemType = apps.get_model("pending_items", "PendingItemType")
    with transaction.atomic():
        categories = _ensure_categories(Category, initial=initial)
        for entry in CATALOG_TYPES:
            _ensure_type(
                ItemType,
                entry,
                categories[entry.category],
                initial=initial,
            )
        if initial:
            _preserve_legacy_types(
                ItemType, categories[CATEGORY_SLUG_OUTRAS_PENDENCIAS]
            )
        _require_outro_contract(ItemType)


def _ensure_categories(Category, *, initial: bool) -> dict[str, object]:
    by_slug: dict[str, object] = {}
    for entry in CATALOG_CATEGORIES:
        existing = Category.objects.filter(slug=entry.slug).first()
        if existing is not None:
            if initial and existing.name != entry.name:
                raise CatalogLoadError(
                    f"categoria {entry.slug!r}: nome divergente "
                    f"({existing.name!r})"
                )
            by_slug[entry.slug] = existing
            continue
        if Category.objects.filter(name=entry.name).exists():
            raise CatalogLoadError(
                f"categoria {entry.name!r}: nome já usado por outro slug"
            )
        by_slug[entry.slug] = Category.objects.create(
            slug=entry.slug, name=entry.name
        )
    return by_slug


def _ensure_type(ItemType, entry: CatalogType, category, *, initial: bool) -> None:
    existing = ItemType.objects.filter(slug=entry.slug).first()
    if existing is not None:
        if not initial:
            return
        if existing.name != entry.name:
            raise CatalogLoadError(
                f"tipo {entry.slug!r}: adotado com nome divergente "
                f"({existing.name!r})"
            )
        ItemType.objects.filter(pk=existing.pk).update(
            category=category,
            profile=entry.profile,
            has_rnm_complements=entry.has_rnm_complements,
            requires_description=entry.requires_description,
        )
        return
    if ItemType.objects.filter(category=category, name=entry.name).exists():
        raise CatalogLoadError(
            f"tipo {entry.name!r}: nome já usado em {entry.category!r}"
        )
    ItemType.objects.create(
        slug=entry.slug,
        name=entry.name,
        category=category,
        profile=entry.profile,
        has_rnm_complements=entry.has_rnm_complements,
        requires_description=entry.requires_description,
    )


def _preserve_legacy_types(ItemType, outras_pendencias) -> None:
    legacy = list(
        ItemType.objects.filter(category__isnull=True).order_by("pk")
    )
    if not legacy:
        return
    taken = set(
        ItemType.objects.filter(category=outras_pendencias).values_list(
            "name", flat=True
        )
    )
    for legacy_type in legacy:
        if legacy_type.name in taken:
            raise CatalogLoadError(
                f"tipo {legacy_type.slug!r}: nome {legacy_type.name!r} "
                "colide em outras-pendencias"
            )
        taken.add(legacy_type.name)
    for legacy_type in legacy:
        ItemType.objects.filter(pk=legacy_type.pk).update(
            category=outras_pendencias,
            profile=PROFILE_SIMPLE,
            has_rnm_complements=False,
            requires_description=False,
        )


def _require_outro_contract(ItemType) -> None:
    outro = (
        ItemType.objects.filter(slug=OUTRO_SLUG)
        .values(
            "name",
            "profile",
            "has_rnm_complements",
            "requires_description",
            "category__slug",
        )
        .first()
    )
    if outro is None:
        raise CatalogLoadError("tipo 'outro': entrada canônica ausente")
    if (
        outro["name"] != OUTRO_NAME
        or outro["profile"] != PROFILE_SIMPLE
        or outro["has_rnm_complements"]
        or not outro["requires_description"]
        or outro["category__slug"] != CATEGORY_SLUG_OUTRAS_PENDENCIAS
    ):
        raise CatalogLoadError("tipo 'outro': contrato fixo inconsistente")
