# SLICE-S1: Dashboard com indicadores reais

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

Substituir os dados **hardcoded/demo** do dashboard da aplicação por queries reais contra
o banco de dados. O dashboard atualmente mostra números fixos (`internados: 142`,
`cadastrados: 5230`, `altas_24h: 12`, `setores: 18`, `ultima_varredura: "há 4 minutos"`).

Após este slice, o dashboard exibirá:

- **Internados**: contagem de leitos ocupados no `CensusSnapshot` mais recente
- **Cadastrados**: `Patient.objects.count()`
- **Altas (24h)**: Admissions com `discharge_date` nas últimas 24 horas
- **Setores monitorados**: setores distintos no `CensusSnapshot` mais recente
- **Última varredura**: timestamp do `captured_at` do snapshot mais recente
- **Card "Leitos"**: novo card na seção de ações rápidas do dashboard com link para `/beds/`

---

## 3. Estrutura atual do projeto (relevante)

````text
sirhosp/
├── config/
│   └── settings.py
├── apps/
│   ├── patients/
│   │   └── models.py          ← Patient, Admission
│   ├── census/
│   │   └── models.py          ← CensusSnapshot, BedStatus
│   ├── ingestion/
│   │   └── models.py          ← IngestionRun
│   ├── services_portal/
│   │   ├── views.py           ← dashboard(), censo(), monitor_risco()
│   │   ├── urls.py            ← app_name="services_portal"
│   │   └── templates/
│   │       └── services_portal/
│   │           └── dashboard.html
│   └── ...
├── templates/
│   ├── base_sidebar.html
│   └── includes/
│       └── sidebar.html
├── tests/
│   └── unit/
│       ├── test_bed_status_view.py
│       ├── test_census_models.py
│       ├── test_navigation_views.py
│       └── ...
└── manage.py
```text

---

## 4. Modelos e campos que você vai queryar

### `CensusSnapshot` (app `apps.census`)

```python
class CensusSnapshot(models.Model):
    captured_at = models.DateTimeField(...)      # timestamp da captura
    ingestion_run = FK("ingestion.IngestionRun", null=True, blank=True)
    setor = models.CharField(max_length=255)     # nome do setor
    leito = models.CharField(max_length=50)       # identificador do leito
    prontuario = models.CharField(max_length=255, blank=True, default="")
    nome = models.CharField(max_length=512, blank=True, default="")
    especialidade = models.CharField(max_length=100, blank=True, default="")
    bed_status = models.CharField(max_length=20, choices=BedStatus.choices)
```text

### `BedStatus` (TextChoices em `apps.census.models`)

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
    patient_source_key = models.CharField(max_length=255)  # prontuário
    source_system = models.CharField(max_length=50)
    name = models.CharField(max_length=512)
    date_of_birth = models.DateField(null=True, blank=True)
    # ... outros campos demográficos
```text

### `Admission` (app `apps.patients`)

```python
class Admission(models.Model):
    patient = FK(Patient, ...)
    source_admission_key = models.CharField(max_length=255)
    source_system = models.CharField(max_length=50)
    admission_date = models.DateTimeField(...)
    discharge_date = models.DateTimeField(null=True, blank=True)  # null = ainda internado
    ward = models.CharField(max_length=255, blank=True, default="")
    bed = models.CharField(max_length=50, blank=True, default="")
```text

### URL names existentes

```python
# services_portal/urls.py
path("painel/", views.dashboard, name="dashboard")
path("censo/", views.censo, name="censo")

# census/urls.py
path("beds/", views.bed_status_view, name="bed_status")
```text

URL reversa para `/beds/` = `reverse("census:bed_status")` ou `{% url 'census:bed_status' %}`.

---

## 5. Convenções de código

- Todo `.py`: `from __future__ import annotations` no topo
- Views: `@login_required`, type hints `(request: HttpRequest) -> HttpResponse`
- Testes: `@pytest.mark.django_db` na classe, usar `admin_client` fixture do pytest-django
- Testes: nome de arquivo `tests/unit/test_<modulo>.py`
- Testes: usar `reverse()` para URLs, não strings hardcoded
- ORM: `from django.db.models import Count, Max` para agregações
- Templates: usar `{% url %}` para links, nunca hardcoded
- Sempre rodar quality gate no container: `./scripts/test-in-container.sh`

---

## 6. O que EXATAMENTE modificar

### 6.1 `apps/services_portal/views.py` — função `dashboard()`

**Estado atual** (trecho relevante):

```python
@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    context = {
        "page_title": "Dashboard",
        "stats": {
            "internados": 142,
            "cadastrados": 5230,
            "altas_24h": 12,
        },
        "coleta": {
            "setores": 18,
            "ultima_varredura": "há 4 minutos",
        },
    }
    return render(request, "services_portal/dashboard.html", context)
```text

**Estado desejado**: substituir os valores hardcoded por queries reais.

Lógica:

1. Obter `captured_at` do CensusSnapshot mais recente:

   ```python
   from django.db.models import Count, Max
   from django.utils import timezone
   from datetime import timedelta

   latest = CensusSnapshot.objects.aggregate(latest=Max("captured_at"))["latest"]
```text

2. Se `latest` não for `None`:
   - `internados` = `CensusSnapshot.objects.filter(captured_at=latest, bed_status=BedStatus.OCCUPIED).count()`
   - `setores` = `CensusSnapshot.objects.filter(captured_at=latest).values("setor").distinct().count()`
   - `ultima_varredura` = `latest.strftime("%d/%m/%Y %H:%M")`
   - Se `latest` for `None`: `internados=0`, `setores=0`, `ultima_varredura="Nenhum dado disponível"`

3. `cadastrados` = `Patient.objects.count()`

4. `altas_24h` = `Admission.objects.filter(discharge_date__gte=timezone.now() - timedelta(hours=24)).count()`

Imports necessários no topo do `views.py`:

```python
from datetime import timedelta

from django.db.models import Count, Max
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.patients.models import Admission, Patient
```text

### 6.2 `apps/services_portal/templates/services_portal/dashboard.html`

Adicionar um **quarto card** na seção "Quick actions" (linhas ~78-110 do arquivo atual),
com link para `/beds/`. Inserir entre o card "Censo" e o card "Pacientes":

```html
<div class="col-sm-6 col-lg-3">
  <a href="{% url 'census:bed_status' %}" class="card border-0 shadow-sm text-decoration-none h-100">
    <div class="card-body d-flex align-items-center gap-3">
      <i class="bi bi-door-open fs-3" style="color: var(--bs-primary);"></i>
      <div>
        <h4 class="h6 fw-semibold mb-0" style="color: var(--sirhosp-sidebar-bg);">Leitos</h4>
        <p class="small text-muted mb-0">Ocupação e vagas por setor</p>
      </div>
    </div>
  </a>
</div>
```text

**Ajuste de grid**: como agora são 4 cards na seção quick actions, mudar `col-lg-4` para `col-lg-3`
nos 4 cards. O grid Bootstrap 3×4=12 colunas fica 4×3=12 colunas.

### 6.3 Testes: `tests/unit/test_services_portal_dashboard.py` (NOVO)

Criar este arquivo com testes que cobrem:

```python
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from apps.census.models import BedStatus, CensusSnapshot
from apps.patients.models import Admission, Patient


@pytest.mark.django_db
class TestDashboardRealStats:
    """S1: Dashboard shows real data from CensusSnapshot, Patient, Admission."""

    def test_dashboard_empty_db_shows_zeros(self, admin_client):
        """When DB is empty, all counts are zero."""
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Check internados=0 rendered somewhere in the page
        assert "0" in content
        # Should not crash
        assert "Dashboard" in content

    def test_dashboard_shows_occupied_count(self, admin_client):
        """Dashboard shows count of occupied beds from latest snapshot."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC A", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="222", nome="PAC B", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="03",
            prontuario="", nome="VAZIO", especialidade="",
            bed_status=BedStatus.EMPTY,
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # internados should be 2
        assert "internados-val" not in content  # we check rendered number

    def test_dashboard_shows_patient_count(self, admin_client):
        """Dashboard shows total Patient count."""
        Patient.objects.create(patient_source_key="P1", source_system="tasy", name="A")
        Patient.objects.create(patient_source_key="P2", source_system="tasy", name="B")

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # 2 patients should be reflected

    def test_dashboard_shows_discharges_24h(self, admin_client):
        """Dashboard counts admissions discharged in last 24h."""
        patient = Patient.objects.create(
            patient_source_key="P1", source_system="tasy", name="A"
        )
        now = timezone.now()
        # Discharged 1 hour ago
        Admission.objects.create(
            patient=patient, source_admission_key="ADM1", source_system="tasy",
            admission_date=now - timedelta(days=5),
            discharge_date=now - timedelta(hours=1),
        )
        # Discharged 48 hours ago (should NOT be counted)
        Admission.objects.create(
            patient=patient, source_admission_key="ADM2", source_system="tasy",
            admission_date=now - timedelta(days=10),
            discharge_date=now - timedelta(hours=48),
        )
        # Not discharged yet
        Admission.objects.create(
            patient=patient, source_admission_key="ADM3", source_system="tasy",
            admission_date=now - timedelta(days=2),
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200

    def test_dashboard_shows_sectors_and_timestamp(self, admin_client):
        """Dashboard shows sector count and last capture time."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="CLINICA", leito="01",
            prontuario="222", nome="PAC2", especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200

    def test_dashboard_no_census_shows_fallback(self, admin_client):
        """Without CensusSnapshot, shows informative message."""
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200

    def test_dashboard_uses_only_latest_snapshot(self, admin_client):
        """Dashboard uses only the most recent CensusSnapshot."""
        old = timezone.now() - timedelta(hours=4)
        new = timezone.now()

        CensusSnapshot.objects.create(
            captured_at=old, setor="OLD", leito="01",
            prontuario="A", nome="OLD", especialidade="X",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=new, setor="NEW", leito="01",
            prontuario="B", nome="NEW", especialidade="Y",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=new, setor="NEW", leito="02",
            prontuario="C", nome="NEW2", especialidade="Z",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Should count 2 occupied from "new" snapshot, not 1 from "old"

    def test_dashboard_has_leitos_card(self, admin_client):
        """Dashboard quick actions include Leitos card linking to /beds/."""
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "/beds/" in content or "Leitos" in content
        # Check link points to correct URL
        assert 'census:bed_status' in content or '/beds/' in content
```text

Os testes usam `admin_client` (fixture do pytest-django que já vem autenticado como superuser).
Não é necessário criar usuário manualmente — `admin_client` já faz login automático.

**IMPORTANTE**: Após implementar as queries reais, os asserts `"0" in content` e similares
devem ser ajustados para verificar que os números renderizados no HTML estão corretos.
Por exemplo, verificar que o número `2` aparece no contexto certo. Use asserts como:

```python
assert "UTI A" in content  # setor aparece na página
```text

Ou extraia números específicos do contexto da view testando diretamente se necessário.

---

## 7. Sequência de execução (TDD)

1. **RED**: Criar `tests/unit/test_services_portal_dashboard.py` com os testes acima
2. **RED**: Rodar `uv run pytest tests/unit/test_services_portal_dashboard.py -v` e ver falhar
3. **GREEN**: Substituir dados demo por queries reais em `apps/services_portal/views.py`
4. **GREEN**: Adicionar card "Leitos" em `apps/services_portal/templates/services_portal/dashboard.html`
5. **GREEN**: Rodar testes novamente — devem passar
6. **REFACTOR**: Ajustar asserts nos testes conforme necessário, limpar código
7. Rodar quality gate completo

---

## 8. Quality Gate (obrigatório)

Rodar no container:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```text

Se Docker não estiver disponível, fallback host-only (resultados são **diagnósticos**, não oficiais):

```bash
uv run python manage.py check
uv run pytest tests/unit/test_services_portal_dashboard.py -v
uv run ruff check apps/services_portal/views.py apps/services_portal/templates/ tests/unit/test_services_portal_dashboard.py
```text

---

## 9. Relatório obrigatório

Gerar `/tmp/sirhosp-slice-DRD-S1-report.md` com:

```markdown
# Slice DRD-S1 Report

## Status
[PASS / FAIL]

## Arquivos modificados
- apps/services_portal/views.py
- apps/services_portal/templates/services_portal/dashboard.html

## Arquivos criados
- tests/unit/test_services_portal_dashboard.py

## Snippets before/after
### apps/services_portal/views.py — função dashboard()
**Before:** (trecho com dados hardcoded)
**After:** (trecho com queries reais)

### apps/services_portal/templates/services_portal/dashboard.html
**Before:** (seção quick actions com 3 cards)
**After:** (seção quick actions com 4 cards, incluindo Leitos)

## Comandos executados
- ./scripts/test-in-container.sh check: [output resumido]
- ./scripts/test-in-container.sh unit: [output resumido]
- ./scripts/test-in-container.sh lint: [output resumido]

## Resultados dos testes
- [X/Y] passed

## Riscos / Pendências
- Nenhum.

## Próximo slice sugerido
S2 — Censo Hospitalar com dados reais
```text

---

## 10. Anti-padrões PROIBIDOS

- ❌ Manter qualquer número hardcoded no dicionário `stats` ou `coleta`
- ❌ Esquecer `BedStatus.OCCUPIED` — usar `"occupied"` como string solta
- ❌ Query no CensusSnapshot sem filtrar por `captured_at=latest` (pegaria snapshots antigos)
- ❌ Contar altas sem `discharge_date__isnull=False` implícito no `__gte`
- ❌ Esquecer `from __future__ import annotations` no arquivo de teste
- ❌ Hardcodar URL `/beds/` no template — usar `{% url 'census:bed_status' %}`
- ❌ Não rodar os gates de qualidade
- ❌ Modificar arquivos fora do escopo (ex.: mexer em `censo()` ou `monitor_risco()`)
````
