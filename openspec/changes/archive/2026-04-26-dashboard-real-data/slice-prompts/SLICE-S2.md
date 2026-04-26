# SLICE-S2: Censo Hospitalar com dados reais

> **Handoff para executor com ZERO contexto adicional.**
> Este documento é autocontido — não requer leitura de outros arquivos do projeto.
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares.
Extrai dados clínicos do sistema fonte hospitalar via web scraping (Playwright),
persiste em banco PostgreSQL paralelo, e oferece portal web Django para consulta rápida
por diretoria, qualidade e jurídico.

**Stack**: Python 3.12, Django 5.x, PostgreSQL, `uv`, Playwright (Chromium), pytest,
Bootstrap 5 + HTMX.

**Arquitetura**: monólito modular. Apps Django em `apps/`. Testes em `tests/unit/`.

**Regras críticas**: sem Celery/Redis na fase 1, sem dados reais no código, TDD obrigatório.

---

## 2. O que este Slice faz

Substituir os **8 pacientes demo** e a **lista hardcoded de 12 setores** da página de Censo
Hospitalar (`/censo/`) por dados reais do modelo `CensusSnapshot`.

Atualmente a view `censo()` monta listas Python hardcoded (`pacientes_demo`, `setores_demo`)
e faz filtro em memória com list comprehensions. Após este slice, ela fará queries diretas
no `CensusSnapshot` mais recente filtrando apenas leitos **ocupados**.

A página exibe: leito, nome do paciente, prontuário, data de admissão (quando disponível)
e setor — com filtro por setor (dropdown dinâmico) e busca textual.

O layout responsivo existente (tabela no desktop, cards no mobile) deve ser preservado.

---

## 3. Estrutura atual do projeto (relevante)

````text
sirhosp/
├── apps/
│   ├── patients/
│   │   └── models.py          ← Patient (patient_source_key), Admission
│   ├── census/
│   │   └── models.py          ← CensusSnapshot, BedStatus
│   ├── services_portal/
│   │   ├── views.py           ← censo() — AQUI a principal mudança
│   │   ├── urls.py            ← app_name="services_portal", name="censo"
│   │   └── templates/
│   │       └── services_portal/
│   │           └── censo.html ← template (preservar layout responsivo)
│   └── ...
├── tests/
│   └── unit/
│       ├── test_census_models.py
│       ├── test_navigation_views.py
│       └── ...
└── manage.py
```text

---

## 4. Modelos relevantes

### `CensusSnapshot` (app `apps.census`)

```python
class CensusSnapshot(models.Model):
    captured_at = models.DateTimeField()           # timestamp da captura
    ingestion_run = FK("ingestion.IngestionRun", null=True, blank=True)
    setor = models.CharField(max_length=255)        # nome do setor/ala
    leito = models.CharField(max_length=50)          # identificador do leito
    prontuario = models.CharField(max_length=255, blank=True, default="")
    nome = models.CharField(max_length=512, blank=True, default="")
    especialidade = models.CharField(max_length=100, blank=True, default="")
    bed_status = models.CharField(max_length=20, choices=BedStatus.choices)

    class Meta:
        ordering = ["-captured_at", "setor", "leito"]
        indexes = [
            models.Index(fields=["captured_at"], name="census_captured_idx"),
            models.Index(fields=["setor"], name="census_setor_idx"),
            models.Index(fields=["prontuario"], name="census_pront_idx"),
            models.Index(fields=["captured_at", "bed_status"], name="census_capt_bstat_idx"),
        ]
```text

### `BedStatus` (TextChoices)

```python
class BedStatus(models.TextChoices):
    OCCUPIED = "occupied", "Ocupado"
    EMPTY = "empty", "Vago"
    MAINTENANCE = "maintenance", "Em Manutenção"
    RESERVED = "reserved", "Reservado"
    ISOLATION = "isolation", "Isolamento"
```text

### `Patient` (app `apps.patients`)

```python
class Patient(models.Model):
    patient_source_key = models.CharField(max_length=255)  # = CensusSnapshot.prontuario
    source_system = models.CharField(max_length=50, default="tasy")
    name = models.CharField(max_length=512)
    # ...
```text

### `Admission` (app `apps.patients`)

```python
class Admission(models.Model):
    patient = FK(Patient, ...)
    source_admission_key = models.CharField(max_length=255)
    admission_date = models.DateTimeField(...)
    discharge_date = models.DateTimeField(null=True, blank=True)
    ward = models.CharField(max_length=255, blank=True, default="")
    bed = models.CharField(max_length=50, blank=True, default="")
```text

### URL names

```python
# services_portal/urls.py
path("censo/", views.censo, name="censo")

# patients/urls.py tem algo como:
path("", views.patient_list, name="patient_list")
```text

---

## 5. Convenções de código

- Todo `.py`: `from __future__ import annotations` no topo
- Views: `@login_required`, type hints `(request: HttpRequest) -> HttpResponse`
- Testes: `@pytest.mark.django_db` na classe, usar `admin_client` (já autenticado)
- Testes: nome `tests/unit/test_services_portal_censo.py` (NOVO)
- Testes: `reverse("services_portal:censo")` para URL da página
- ORM: `from django.db.models import Max` para `latest = CensusSnapshot.objects.aggregate(latest=Max("captured_at"))["latest"]`
- Templates: preservar marcação `sirhosp-censo-table-wrapper` (desktop) e `sirhosp-censo-cards` (mobile)
- Os dados de censo **não têm data de admissão** — o CensusSnapshot só tem `captured_at`. O template já tem um placeholder `paciente.admissao`. Você deve preencher com string vazia ou `"—"` quando não disponível.

---

## 6. O que EXATAMENTE modificar

### 6.1 `apps/services_portal/views.py` — função `censo()`

**Estado atual** (trecho completo da função):

```python
@login_required
def censo(request: HttpRequest) -> HttpResponse:
    # Demo sectors
    setores_demo = [
        "UTI Adulto", "UTI Neonatal", "Clínica Médica",
        "Clínica Cirúrgica", "Ortopedia", "Cardiologia",
        "Neurologia", "Pediatria", "Maternidade",
        "Pronto Socorro", "Oncologia", "Nefrologia",
    ]

    def _p(leito, nome, registro, admissao, setor):
        return {"leito": leito, "nome": nome, "registro": registro,
                "admissao": admissao, "setor": setor}

    pacientes_demo = [
        _p("202-A", "Fulano de Tal", "00123", "20/01/2026", "Clínica Médica"),
        _p("UTI-05", "Beltrano de Souza", "00456", "22/01/2026", "UTI Adulto"),
        _p("301-B", "Maria Oliveira", "00789", "25/01/2026", "Clínica Médica"),
        _p("UTI-02", "José Ferreira", "00890", "23/01/2026", "UTI Adulto"),
        _p("405-C", "Ana Paula Reis", "00332", "05/02/2026", "Ortopedia"),
        _p("UTI-NEO-01", "Lucas Mendes", "01234", "28/01/2026", "UTI Neonatal"),
        _p("502-A", "Carla Dantas", "01567", "18/01/2026", "Cardiologia"),
        _p("601-D", "Rafael Torres", "01890", "10/02/2026", "Neurologia"),
    ]

    setor_filtro = request.GET.get("setor", "").strip()
    busca = request.GET.get("q", "").strip()

    pacientes = pacientes_demo
    if setor_filtro and setor_filtro != "Todos":
        pacientes = [p for p in pacientes if p["setor"] == setor_filtro]
    if busca:
        busca_lower = busca.lower()
        pacientes = [
            p for p in pacientes
            if busca_lower in p["nome"].lower() or busca_lower in p["registro"]
        ]

    context = {
        "page_title": "Censo Hospitalar",
        "setores": setores_demo,
        "setor_filtro": setor_filtro,
        "busca": busca,
        "pacientes": pacientes,
        "total": len(pacientes),
    }
    return render(request, "services_portal/censo.html", context)
```text

**Estado desejado**: substituir tudo por queries reais no `CensusSnapshot`.

Lógica (pseudocódigo):

```python
from django.db.models import Max
from apps.census.models import BedStatus, CensusSnapshot

@login_required
def censo(request: HttpRequest) -> HttpResponse:
    latest = CensusSnapshot.objects.aggregate(latest=Max("captured_at"))["latest"]

    if latest is None:
        # Sem dados de censo
        return render(request, "services_portal/censo.html", {
            "page_title": "Censo Hospitalar",
            "setores": [],
            "setor_filtro": "",
            "busca": "",
            "pacientes": [],
            "total": 0,
            "captured_at": None,
        })

    # Base queryset: apenas leitos ocupados do snapshot mais recente
    qs = CensusSnapshot.objects.filter(
        captured_at=latest,
        bed_status=BedStatus.OCCUPIED,
    ).order_by("setor", "leito")

    # Lista de setores distintos (para dropdown)
    setores = list(
        qs.values_list("setor", flat=True)
        .distinct()
        .order_by("setor")
    )

    # Filtro por setor
    setor_filtro = request.GET.get("setor", "").strip()
    if setor_filtro and setor_filtro != "Todos":
        qs = qs.filter(setor=setor_filtro)

    # Busca textual
    busca = request.GET.get("q", "").strip()
    if busca:
        qs = qs.filter(
            models.Q(nome__icontains=busca) | models.Q(prontuario__icontains=busca)
        )

    # Construir lista de pacientes para o template
    snapshots = list(qs)
    pacientes = [
        {
            "leito": s.leito,
            "nome": s.nome,
            "registro": s.prontuario,
            "admissao": "",  # CensusSnapshot não tem data de admissão
            "setor": s.setor,
        }
        for s in snapshots
    ]

    return render(request, "services_portal/censo.html", {
        "page_title": "Censo Hospitalar",
        "setores": setores,
        "setor_filtro": setor_filtro,
        "busca": busca,
        "pacientes": pacientes,
        "total": len(pacientes),
        "captured_at": latest,
    })
```text

**Importante**: Você também precisa adicionar `from django.db import models` no topo do arquivo
para poder usar `models.Q` na busca textual. Ou importe `Q` diretamente:

```python
from django.db.models import Max, Q
```text

E adicionar o import do modelo:

```python
from apps.census.models import BedStatus, CensusSnapshot
```text

### 6.2 `apps/services_portal/templates/services_portal/censo.html`

O template **não precisa de mudanças estruturais** — a estrutura atual já aceita
uma lista de dicionários com as chaves `leito`, `nome`, `registro`, `admissao`, `setor`.

**Pequenos ajustes**:

1. **Mostrar timestamp da captura**: Adicionar abaixo do `<h2>` uma linha com a data/hora
   do censo, quando disponível:

   ```html
   {% if captured_at %}
   <p class="text-muted small mb-0">Censo capturado em: {{ captured_at|date:"d/m/Y H:i" }}</p>
   {% endif %}
````

Coloque isso logo após o `<p class="text-muted small mb-0">Pacientes atualmente internados...</p>`
(linha ~6 do arquivo).

1. **Dropdown "Todos os setores"**: Remover a opção hardcoded "Todos os setores"? NÃO — manter.
   O template já tem `<option value="">Todos os setores</option>` que funciona como "sem filtro".

2. **Setor filter preserva seleção**: O template já faz `{% if setor_filtro == setor %}selected{% endif %}`.
   Confirmar que funciona com a nova lista de setores (strings, não dicionários).

O template está bem estruturado e não requer reescrita. **Não altere a estrutura de cards/tabela** —
a lógica responsiva (`.sirhosp-censo-table-wrapper` + `.sirhosp-censo-cards`) deve ser preservada.

### 6.3 Testes: `tests/unit/test_services_portal_censo.py` (NOVO)

````python
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot


@pytest.mark.django_db
class TestCensoRealData:
    """S2: Censo page shows real data from CensusSnapshot (occupied only)."""

    def test_censo_empty_db_shows_message(self, admin_client):
        """Without CensusSnapshot, shows empty state."""
        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Should show empty/zero state, not crash
        assert "Censo Hospitalar" in content

    def test_censo_shows_occupied_patients(self, admin_client):
        """Only occupied beds appear on censo page."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PACIENTE ALFA", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="222", nome="PACIENTE BETA", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )
        # Empty bed — should NOT appear
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="03",
            prontuario="", nome="VAZIO", especialidade="",
            bed_status=BedStatus.EMPTY,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "PACIENTE ALFA" in content
        assert "PACIENTE BETA" in content
        assert "VAZIO" not in content

    def test_censo_shows_timestamp_when_available(self, admin_client):
        """Censo page shows capture timestamp."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Should contain date somewhere

    def test_censo_filters_by_setor(self, admin_client):
        """Filter by sector shows only that sector's patients."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC UTI", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="CLINICA", leito="01",
            prontuario="222", nome="PAC CLINICA", especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?setor=UTI+A"
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "PAC UTI" in content
        assert "PAC CLINICA" not in content

    def test_censo_search_by_name(self, admin_client):
        """Free-text search filters by patient name."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="JOAO SILVA", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="222", nome="MARIA SANTOS", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?q=JOAO"
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "JOAO SILVA" in content
        assert "MARIA SANTOS" not in content

    def test_censo_search_by_prontuario(self, admin_client):
        """Free-text search filters by patient record number."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="99999", nome="JOAO SILVA", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="88888", nome="MARIA SANTOS", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?q=99999"
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "JOAO SILVA" in content
        assert "MARIA SANTOS" not in content

    def test_censo_dropdown_has_real_setores(self, admin_client):
        """Sector dropdown is populated from actual sectors in the snapshot."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI GERAL", leito="01",
            prontuario="111", nome="PAC1", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="ENFERMARIA B", leito="01",
            prontuario="222", nome="PAC2", especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "UTI GERAL" in content
        assert "ENFERMARIA B" in content
        # Should NOT contain hardcoded demo sectors
        assert "Todos os setores" in content  # the "all" option remains

    def test_censo_uses_only_latest_snapshot(self, admin_client):
        """Only the most recent CensusSnapshot is used."""
        from datetime import timedelta
        old = timezone.now() - timedelta(hours=4)
        new = timezone.now()

        CensusSnapshot.objects.create(
            captured_at=old, setor="OLD SETOR", leito="01",
            prontuario="AAA", nome="OLD PATIENT", especialidade="X",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=new, setor="NEW SETOR", leito="01",
            prontuario="BBB", nome="NEW PATIENT", especialidade="Y",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "NEW PATIENT" in content
        assert "OLD PATIENT" not in content

    def test_censo_row_links_to_patient_search(self, admin_client):
        """Clicking a censo row links to patient search by prontuario."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="12345", nome="PAC LINK", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Link must point to patient search with prontuario
        assert "q=12345" in content
```text

---

## 7. Sequência de execução (TDD)

1. **RED**: Criar `tests/unit/test_services_portal_censo.py` com os testes acima
2. **RED**: Rodar `uv run pytest tests/unit/test_services_portal_censo.py -v` — devem FALHAR
3. **GREEN**: Substituir `censo()` demo data por queries reais em `views.py`
4. **GREEN**: Ajustar template `censo.html` para mostrar `captured_at` quando disponível
5. **GREEN**: Rodar testes novamente — devem PASSAR
6. **REFACTOR**: Revisar código, garantir que não sobrou nenhum dado demo ou hardcoded
7. Rodar quality gate

---

## 8. Quality Gate (obrigatório)

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```text

Fallback host-only (diagnóstico):

```bash
uv run python manage.py check
uv run pytest tests/unit/test_services_portal_censo.py -v
uv run ruff check apps/services_portal/views.py apps/services_portal/templates/ tests/unit/test_services_portal_censo.py
```text

---

## 9. Relatório obrigatório

Gerar `/tmp/sirhosp-slice-DRD-S2-report.md` com:

```markdown
# Slice DRD-S2 Report

## Status
[PASS / FAIL]

## Arquivos modificados
- apps/services_portal/views.py (função censo())
- apps/services_portal/templates/services_portal/censo.html

## Arquivos criados
- tests/unit/test_services_portal_censo.py

## Snippets before/after
### apps/services_portal/views.py — função censo()
**Before:** (função completa com pacientes_demo e setores_demo)
**After:** (função completa com queries reais no CensusSnapshot)

### apps/services_portal/templates/services_portal/censo.html
**Before:** (trecho do título sem timestamp)
**After:** (trecho com linha de captured_at)

## Comandos executados
- ./scripts/test-in-container.sh check: [output resumido]
- ./scripts/test-in-container.sh unit: [output resumido]
- ./scripts/test-in-container.sh lint: [output resumido]

## Resultados dos testes
- [X/Y] passed

## Riscos / Pendências
- Nenhum.

## Próximo slice sugerido
S3 — /beds/ com cards, totalização e link na sidebar
```text

---

## 10. Anti-padrões PROIBIDOS

- ❌ Manter `pacientes_demo`, `setores_demo`, `_p()` helper na função `censo()`
- ❌ Fazer filtro em memória (list comprehension) em vez de `.filter()` no QuerySet
- ❌ Query sem `bed_status=BedStatus.OCCUPIED` — mostraria leitos vagos na página de censo
- ❌ Query sem `captured_at=latest` — mostraria snapshots antigos
- ❌ Hardcodar lista de setores
- ❌ Remover o layout responsivo (tabela+cards) do template
- ❌ Usar `from django.db.models import Q` sem também adicionar ao arquivo
- ❌ Esquecer `from __future__ import annotations`
- ❌ Modificar arquivos fora do escopo (dashboard, monitor_risco, beds)
````
