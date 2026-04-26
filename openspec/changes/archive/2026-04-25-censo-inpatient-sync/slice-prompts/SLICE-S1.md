# SLICE-S1: App `census` + modelo `CensusSnapshot`

> **Handoff para executor com ZERO contexto adicional.**
> Este documento é autocontido — não requer leitura de outros arquivos do projeto.
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares.
Extrai dados clínicos do sistema fonte hospitalar via web scraping (Playwright),
persiste em banco PostgreSQL paralelo, e oferece portal web Django para consulta rápida
por diretoria, qualidade e jurídico.

**Stack**:

- Python 3.12
- Django 5.x
- PostgreSQL
- `uv` para gerenciamento de dependências e execução de comandos Python
- Playwright (Chromium) para scraping
- pytest para testes
- Bootstrap + HTMX no frontend

**Arquitetura**: monólito modular. Apps Django em `apps/`. Automações em `automation/`.

**Regras críticas**: sem Celery/Redis na fase 1, sem dados reais no código, TDD obrigatório.

---

## 2. O que este Slice faz

Criar o app Django `apps/census/` com o modelo `CensusSnapshot`.

Este modelo armazenará cada linha do **Censo Diário de Pacientes** extraído do sistema fonte —
uma "foto" de todos os pacientes internados num dado momento, com setor, leito, prontuário,
nome, especialidade e status do leito.

---

## 3. Estrutura atual do projeto (relevante para este slice)

```text
sirhosp/
├── config/
│   └── settings.py        ← INSTALLED_APPS está aqui
├── apps/
│   ├── patients/          ← modelos Patient, Admission, PatientIdentifierHistory
│   ├── clinical_docs/     ← modelo ClinicalEvent
│   ├── ingestion/         ← modelo IngestionRun (referenciado por CensusSnapshot)
│   ├── core/
│   ├── accounts/
│   ├── search/
│   ├── services_portal/
│   └── summaries/
├── automation/
│   └── source_system/
│       ├── medical_evolution/
│       ├── patient_demographics/
│       ├── current_inpatients/   ← destino do script do censo (Slice S2)
│       └── prescriptions/
├── tests/
│   ├── unit/
│   └── integration/
└── manage.py
```text

**INSTALLED_APPS atual** em `config/settings.py`:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "apps.core",
    "apps.accounts",
    "apps.patients",
    "apps.clinical_docs",
    "apps.ingestion",
    "apps.summaries",
    "apps.search",
    "apps.services_portal",
]
```text

---

## 4. Modelo de referência: `IngestionRun`

`CensusSnapshot` tem uma FK opcional para `IngestionRun` (`apps/ingestion/models.py`).
Você NÃO precisa criar nem modificar `IngestionRun` — ele já existe.
Apenas referencie-o como `"ingestion.IngestionRun"` na FK.

O modelo `IngestionRun` tem os campos principais:

```python
class IngestionRun(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    events_processed = models.PositiveIntegerField(default=0)
    events_created = models.PositiveIntegerField(default=0)
    # ... mais campos
```text

---

## 5. Convenções de código do projeto

### Modelos Django

- Usar `from __future__ import annotations` no topo de todo arquivo `.py`
- FK: usar string `"app_label.ModelName"` para evitar import circular
- `class Meta`: sempre definir `ordering` e constraints/índices com nomes explícitos
- `__str__`: sempre implementar com representação informativa
- Usar `models.TextChoices` para choices (não tuplas soltas)
- `max_length` explícito em todos os `CharField`

### Testes

- Usar `pytest` com `pytest-django`
- Fixtures via `@pytest.fixture` ou `@pytest.mark.django_db`
- Nome de arquivo: `test_<modulo>.py` dentro de `tests/unit/`
- Testar criação de modelo com todos os campos
- Testar choices e validações
- Testar queries (índices, filtros)

### Estrutura de app Django

Todo app em `apps/<nome>/` precisa de:

- `__init__.py`
- `apps.py` com classe `Config` herdando de `AppConfig`
- `models.py`
- `admin.py`

### Migrations

- Gerar com `uv run python manage.py makemigrations census`
- NUNCA criar migration manualmente — sempre usar `makemigrations`

---

## 6. O que EXATAMENTE criar

### 6.1 `apps/census/__init__.py`

Arquivo vazio.

### 6.2 `apps/census/apps.py`

```python
from __future__ import annotations

from django.apps import AppConfig


class CensusConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.census"
    verbose_name = "Census"
```text

### 6.3 `apps/census/models.py`

```python
from __future__ import annotations

from django.db import models


class BedStatus(models.TextChoices):
    OCCUPIED = "occupied", "Ocupado"
    EMPTY = "empty", "Vago"
    MAINTENANCE = "maintenance", "Em Manutenção"
    RESERVED = "reserved", "Reservado"
    ISOLATION = "isolation", "Isolamento"


class CensusSnapshot(models.Model):
    """Single row from a daily inpatient census extraction.

    Each row represents one bed in one sector at the moment of capture.
    Beds without a patient (empty, maintenance, reserved, isolation) have
    empty prontuario and a descriptive nome.
    """

    captured_at = models.DateTimeField(
        help_text="Timestamp when this census run was captured"
    )
    ingestion_run = models.ForeignKey(
        "ingestion.IngestionRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="census_snapshots",
        help_text="Optional link to the ingestion run that produced this snapshot",
    )

    setor = models.CharField(
        max_length=255,
        help_text="Sector/ward name as it appears in the source system",
    )
    leito = models.CharField(
        max_length=50,
        help_text="Bed identifier (e.g. I10CA, CV01A)",
    )
    prontuario = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Patient record number (empty for non-occupied beds)",
    )
    nome = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Patient name or bed status label (e.g. DESOCUPADO, RESERVA INTERNA)",
    )
    especialidade = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Medical specialty abbreviation (e.g. NEF, CIV, PED)",
    )
    bed_status = models.CharField(
        max_length=20,
        choices=BedStatus.choices,
        help_text="Classified bed status",
    )

    class Meta:
        ordering = ["-captured_at", "setor", "leito"]
        indexes = [
            models.Index(fields=["captured_at"], name="census_captured_idx"),
            models.Index(fields=["setor"], name="census_setor_idx"),
            models.Index(fields=["prontuario"], name="census_pront_idx"),
            models.Index(
                fields=["captured_at", "bed_status"],
                name="census_capt_bstat_idx",
            ),
        ]
        verbose_name = "Census Snapshot"
        verbose_name_plural = "Census Snapshots"

    def __str__(self) -> str:
        return (
            f"{self.setor} / {self.leito} "
            f"[{self.bed_status}] "
            f"{self.prontuario or '-'} "
            f"@ {self.captured_at:%Y-%m-%d %H:%M}"
        )
```text

### 6.4 `apps/census/admin.py`

```python
from __future__ import annotations

from django.contrib import admin

from apps.census.models import CensusSnapshot


@admin.register(CensusSnapshot)
class CensusSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        "captured_at",
        "setor",
        "leito",
        "prontuario",
        "nome",
        "especialidade",
        "bed_status",
    ]
    list_filter = [
        "bed_status",
        "captured_at",
        "setor",
    ]
    search_fields = [
        "prontuario",
        "nome",
        "setor",
        "leito",
    ]
    date_hierarchy = "captured_at"
    ordering = ["-captured_at", "setor", "leito"]
```text

### 6.5 `apps/census/migrations/0001_initial.py`

NÃO criar manualmente. Rodar:

```bash
uv run python manage.py makemigrations census
```text

### 6.6 Registrar em `config/settings.py`

Adicionar `"apps.census.CensusConfig"` ao final da lista `INSTALLED_APPS`.

**IMPORTANTE**: usar o caminho completo com `.CensusConfig`, igual aos outros apps do projeto.

### 6.7 Testes: `tests/unit/test_census_models.py`

```python
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot


@pytest.mark.django_db
class TestBedStatus:
    def test_choices_exist(self):
        """All five bed status choices are defined."""
        assert BedStatus.OCCUPIED == "occupied"
        assert BedStatus.EMPTY == "empty"
        assert BedStatus.MAINTENANCE == "maintenance"
        assert BedStatus.RESERVED == "reserved"
        assert BedStatus.ISOLATION == "isolation"

    def test_labels(self):
        """Labels are in Portuguese."""
        assert BedStatus.OCCUPIED.label == "Ocupado"
        assert BedStatus.EMPTY.label == "Vago"
        assert BedStatus.MAINTENANCE.label == "Em Manutenção"
        assert BedStatus.RESERVED.label == "Reservado"
        assert BedStatus.ISOLATION.label == "Isolamento"


@pytest.mark.django_db
class TestCensusSnapshot:
    def test_create_occupied_bed(self):
        """Can create a snapshot row for an occupied bed."""
        snap = CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="UTI GERAL ADULTO 1 - HGRS",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        assert snap.pk is not None
        assert snap.bed_status == BedStatus.OCCUPIED
        assert "14160147" in str(snap)
        assert "UTI" in str(snap)

    def test_create_empty_bed(self):
        """Can create a snapshot row for an empty bed."""
        snap = CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="UTI GERAL ADULTO 1 - HGRS",
            leito="UG09I",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        assert snap.prontuario == ""
        assert snap.bed_status == BedStatus.EMPTY

    def test_create_all_statuses(self):
        """Can create snapshots with all five statuses."""
        statuses = list(BedStatus.values)
        for status in statuses:
            snap = CensusSnapshot.objects.create(
                captured_at=timezone.now(),
                setor="TEST",
                leito=f"BED-{status}",
                prontuario="123" if status == "occupied" else "",
                nome="TEST" if status == "occupied" else status.upper(),
                especialidade="TST",
                bed_status=status,
            )
            assert snap.bed_status == status

    def test_ordering_by_captured_at_desc(self):
        """Default ordering is by captured_at descending."""
        old = CensusSnapshot.objects.create(
            captured_at=timezone.now() - timezone.timedelta(hours=1),
            setor="A",
            leito="01",
            prontuario="",
            nome="",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        new = CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="A",
            leito="01",
            prontuario="",
            nome="",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        qs = CensusSnapshot.objects.all()
        assert qs[0].pk == new.pk

    def test_filter_by_setor(self):
        """Can filter by setor."""
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="UTI A",
            leito="01",
            prontuario="",
            nome="",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="ENFARIA B",
            leito="01",
            prontuario="",
            nome="",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        assert CensusSnapshot.objects.filter(setor="UTI A").count() == 1

    def test_filter_by_prontuario(self):
        """Can filter by prontuario."""
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="A",
            leito="01",
            prontuario="99999",
            nome="FULANO",
            especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="A",
            leito="02",
            prontuario="",
            nome="VAZIO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        assert CensusSnapshot.objects.filter(prontuario="99999").count() == 1

    def test_fk_to_ingestion_run_nullable(self):
        """ingestion_run FK can be null."""
        snap = CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="A",
            leito="01",
            prontuario="",
            nome="",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        assert snap.ingestion_run is None
```text

---

## 7. Sequência de execução

1. Criar os 4 arquivos (`__init__.py`, `apps.py`, `models.py`, `admin.py`)
2. Adicionar `"apps.census.CensusConfig"` ao `INSTALLED_APPS` em `config/settings.py`
3. Rodar `uv run python manage.py makemigrations census` para gerar `0001_initial.py`
4. Criar `tests/unit/test_census_models.py` com os testes acima
5. Executar validação

---

## 8. Quality Gate (obrigatório)

Rodar **todos** estes comandos e garantir que passam sem erro:

```bash
# Django system check
./scripts/test-in-container.sh check

# Unit tests
./scripts/test-in-container.sh unit

# Lint (ruff)
./scripts/test-in-container.sh lint
```text

Se `./scripts/test-in-container.sh` não funcionar (ex.: Docker não disponível), usar fallback:

```bash
uv run python manage.py check
uv run pytest tests/unit/test_census_models.py -v
uv run ruff check apps/census tests/unit/test_census_models.py
```text

---

## 9. Relatório obrigatório

Gerar `/tmp/sirhosp-slice-CIS-S1-report.md` com:

```markdown
# Slice CIS-S1 Report

## Status
[PASS / FAIL]

## Arquivos criados
- apps/census/__init__.py
- apps/census/apps.py
- apps/census/models.py
- apps/census/admin.py
- apps/census/migrations/0001_initial.py
- tests/unit/test_census_models.py

## Arquivos modificados
- config/settings.py (adicionado apps.census.CensusConfig ao INSTALLED_APPS)

## Snippets before/after
### config/settings.py
**Before:** (últimas 3 linhas do INSTALLED_APPS)
**After:** (últimas 3 linhas + nova entrada)

### apps/census/models.py
(conteúdo completo criado)

## Comandos executados
- ./scripts/test-in-container.sh check: [output resumido]
- ./scripts/test-in-container.sh unit: [output resumido]
- ./scripts/test-in-container.sh lint: [output resumido]

## Riscos / Pendências
- Nenhum.

## Próximo slice sugerido
S2 — Script de extração do censo integrado
```text

---

## 10. Anti-padrões PROIBIDOS

- ❌ Criar migration manualmente (sempre usar `makemigrations`)
- ❌ Usar `from apps.ingestion.models import IngestionRun` no `models.py` (use `"ingestion.IngestionRun"`)
- ❌ Esquecer `from __future__ import annotations` em cada `.py`
- ❌ Criar modelos sem `__str__`
- ❌ Deixar `max_length` sem valor explícito em `CharField`
- ❌ Criar índices sem nome explícito
- ❌ Não rodar os gates de qualidade
- ❌ Modificar arquivos fora do escopo (ex.: mexer em `apps/patients/`)
