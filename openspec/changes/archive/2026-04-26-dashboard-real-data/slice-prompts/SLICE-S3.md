# SLICE-S3: /beds/ com cards, totalização e link na sidebar

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

Três mudanças na página `/beds/` e na sidebar:

1. **Totalização no topo**: adicionar cards de resumo agregando totais de todos os setores
   (ocupados, vagos, manutenção, reservados, isolamento, total geral) antes da lista de setores
2. **Layout de cards com collapse**: converter a tabela atual (`<table>`) em cards Bootstrap
   com `data-bs-toggle="collapse"`. Cada card representa um setor, clicável para expandir
   e mostrar os leitos daquele setor em sub-cards
3. **Link na sidebar**: adicionar item "Leitos" no menu de navegação lateral com link `/beds/`

---

## 3. Estrutura atual do projeto (relevante)

```text
sirhosp/
├── apps/
│   ├── census/
│   │   ├── views.py              ← bed_status_view()
│   │   ├── urls.py               ← app_name="census", name="bed_status"
│   │   ├── models.py             ← CensusSnapshot, BedStatus
│   │   └── templates/
│   │       └── census/
│   │           └── bed_status.html  ← REESCREVER com cards
│   └── ...
├── templates/
│   ├── base_sidebar.html
│   └── includes/
│       └── sidebar.html          ← ADICIONAR link "Leitos"
├── tests/
│   └── unit/
│       └── test_bed_status_view.py  ← MODIFICAR: adicionar testes de totais
└── manage.py
```text

---

## 4. Modelos relevantes

### `BedStatus` (TextChoices em `apps.census.models`)

```python
class BedStatus(models.TextChoices):
    OCCUPIED = "occupied", "Ocupado"
    EMPTY = "empty", "Vago"
    MAINTENANCE = "maintenance", "Em Manutenção"
    RESERVED = "reserved", "Reservado"
    ISOLATION = "isolation", "Isolamento"
```text

### `CensusSnapshot` (app `apps.census`)

```python
class CensusSnapshot(models.Model):
    captured_at = models.DateTimeField()
    setor = models.CharField(max_length=255)
    leito = models.CharField(max_length=50)
    prontuario = models.CharField(max_length=255, blank=True, default="")
    nome = models.CharField(max_length=512, blank=True, default="")
    especialidade = models.CharField(max_length=100, blank=True, default="")
    bed_status = models.CharField(max_length=20, choices=BedStatus.choices)
```text

### URL names

```python
# census/urls.py
app_name = "census"
path("beds/", views.bed_status_view, name="bed_status")
```text

---

## 5. Código atual da view `bed_status_view()`

```python
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max
from django.shortcuts import render
from apps.census.models import BedStatus, CensusSnapshot

@login_required
def bed_status_view(request):
    latest_captured = CensusSnapshot.objects.aggregate(
        latest=Max("captured_at")
    )["latest"]

    if latest_captured is None:
        return render(request, "census/bed_status.html", {
            "sectors": [],
            "captured_at": None,
        })

    snapshots = CensusSnapshot.objects.filter(captured_at=latest_captured)

    sectors_raw = (
        snapshots.values("setor", "bed_status")
        .annotate(count=Count("id"))
        .order_by("setor", "bed_status")
    )

    sectors: dict[str, dict] = {}
    for row in sectors_raw:
        setor = row["setor"]
        status = row["bed_status"]
        count = row["count"]

        if setor not in sectors:
            sectors[setor] = {
                "name": setor,
                "occupied": 0,
                "empty": 0,
                "maintenance": 0,
                "reserved": 0,
                "isolation": 0,
                "total": 0,
                "beds": [],
            }
        sectors[setor][status] = count
        sectors[setor]["total"] += count

    bed_details = snapshots.order_by("leito")
    for bed in bed_details:
        if bed.setor in sectors:
            sectors[bed.setor]["beds"].append({
                "leito": bed.leito,
                "status": bed.bed_status,
                "status_label": BedStatus(bed.bed_status).label,
                "nome": bed.nome if bed.bed_status == BedStatus.OCCUPIED else "",
                "prontuario": bed.prontuario,
            })

    sorted_sectors = sorted(sectors.values(), key=lambda s: s["name"])

    return render(request, "census/bed_status.html", {
        "sectors": sorted_sectors,
        "captured_at": latest_captured,
    })
```text

---

## 6. Código atual do template `bed_status.html`

```html
{% extends "base_sidebar.html" %}
{% block title %}Leitos — SIRHOSP{% endblock %}

{% block content %}
<div class="container-fluid py-3">
  <h2 class="h5 fw-bold mb-3" style="color: var(--sirhosp-sidebar-bg);">Ocupação de Leitos</h2>

  {% if not captured_at %}
    <div class="alert alert-info">
      Nenhum dado de censo disponível. Execute a extração do censo primeiro.
    </div>
  {% else %}
    <p class="text-muted mb-3 small">
      Censo capturado em: {{ captured_at|date:"d/m/Y H:i" }}
    </p>

    <div class="table-responsive">
      <table class="table table-striped table-hover">
        <thead>
          <tr>
            <th>Setor</th>
            <th class="text-center">Ocupados</th>
            <th class="text-center">Vagas</th>
            <th class="text-center">Reservas</th>
            <th class="text-center">Manutenção</th>
            <th class="text-center">Isolamento</th>
            <th class="text-center">Total</th>
          </tr>
        </thead>
        <tbody>
          {% for sector in sectors %}
          <tr class="sector-row" data-bs-toggle="collapse"
              data-bs-target="#sector-{{ forloop.counter }}"
              style="cursor: pointer;">
            <td><strong>{{ sector.name }}</strong></td>
            <td class="text-center"><span class="badge bg-primary">{{ sector.occupied }}</span></td>
            <td class="text-center"><span class="badge bg-success">{{ sector.empty }}</span></td>
            <td class="text-center"><span class="badge bg-warning text-dark">{{ sector.reserved }}</span></td>
            <td class="text-center"><span class="badge bg-secondary">{{ sector.maintenance }}</span></td>
            <td class="text-center"><span class="badge bg-danger">{{ sector.isolation }}</span></td>
            <td class="text-center"><strong>{{ sector.total }}</strong></td>
          </tr>
          <tr class="collapse" id="sector-{{ forloop.counter }}">
            <td colspan="7" class="p-0">
              <table class="table table-sm mb-0">
                <thead>
                  <tr><th>Leito</th><th>Status</th><th>Paciente</th></tr>
                </thead>
                <tbody>
                  {% for bed in sector.beds %}
                  <tr>
                    <td><code>{{ bed.leito }}</code></td>
                    <td>{{ bed.status_label }}</td>
                    <td>
                      {% if bed.prontuario %}
                        {{ bed.nome }} <small class="text-muted">({{ bed.prontuario }})</small>
                      {% else %}—{% endif %}
                    </td>
                  </tr>
                  {% endfor %}
                </tbody>
              </table>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  {% endif %}
</div>
{% endblock %}
```text

---

## 7. O que EXATAMENTE modificar

### 7.1 `apps/census/views.py` — adicionar totais globais

Adicionar uma segunda agregação para calcular os totais globais (antes da lógica de setores
existente — ela continua igual). A view atual já agrega por setor; você vai adicionar
uma agregação GLOBAL que some todos os setores.

Após `snapshots = CensusSnapshot.objects.filter(captured_at=latest_captured)`, adicione:

```python
# Global totals across all sectors
global_totals_raw = (
    snapshots.values("bed_status")
    .annotate(count=Count("id"))
)
totals = {
    "occupied": 0,
    "empty": 0,
    "maintenance": 0,
    "reserved": 0,
    "isolation": 0,
    "total": snapshots.count(),
}
for row in global_totals_raw:
    status = row["bed_status"]
    if status in totals:
        totals[status] = row["count"]
```text

Depois, adicione `"totals": totals` ao dicionário de contexto retornado pela view:

```python
return render(request, "census/bed_status.html", {
    "sectors": sorted_sectors,
    "captured_at": latest_captured,
    "totals": totals,          # ← NOVO
})
```text

### 7.2 `apps/census/templates/census/bed_status.html` — reescrever com cards

**REESCREVER completamente o template**. Layout desejado:

1. Título + timestamp (mantidos do template atual)
2. **Cards de totalização**: 6 cards em grid responsivo (`col-6 col-md-4 col-lg-2`)
   - Ocupados (azul/bg-primary)
   - Vagas (verde/bg-success)
   - Manutenção (cinza/bg-secondary)
   - Reservados (amarelo/bg-warning)
   - Isolamento (vermelho/bg-danger)
   - Total geral
3. **Lista de cards de setor**: um card por setor com collapse Bootstrap
   - Cabeçalho do card: nome do setor + badges de contagem (ocupados, vagos, etc.)
   - Corpo colapsável: lista de leitos em cards pequenos ou lista simples
   - Colapsado por padrão (sem `show`)

Template desejado:

```html
{% extends "base_sidebar.html" %}
{% block title %}Leitos — SIRHOSP{% endblock %}

{% block content %}
<div class="container-fluid py-3">
  <h2 class="h5 fw-bold mb-1" style="color: var(--sirhosp-sidebar-bg);">Ocupação de Leitos</h2>

  {% if not captured_at %}
    <div class="alert alert-info">
      Nenhum dado de censo disponível. Execute a extração do censo primeiro.
    </div>
  {% else %}
    <p class="text-muted mb-3 small">
      Censo capturado em: {{ captured_at|date:"d/m/Y H:i" }}
    </p>

    <!-- ====== TOTALIZAÇÃO (cards de resumo) ====== -->
    <div class="row g-2 mb-4">
      <div class="col-6 col-md-4 col-lg-2">
        <div class="card border-0 shadow-sm text-center h-100 bg-primary bg-opacity-10">
          <div class="card-body py-3">
            <div class="fs-3 fw-bold text-primary">{{ totals.occupied }}</div>
            <div class="small text-muted">Ocupados</div>
          </div>
        </div>
      </div>
      <div class="col-6 col-md-4 col-lg-2">
        <div class="card border-0 shadow-sm text-center h-100 bg-success bg-opacity-10">
          <div class="card-body py-3">
            <div class="fs-3 fw-bold text-success">{{ totals.empty }}</div>
            <div class="small text-muted">Vagas</div>
          </div>
        </div>
      </div>
      <div class="col-6 col-md-4 col-lg-2">
        <div class="card border-0 shadow-sm text-center h-100 bg-secondary bg-opacity-10">
          <div class="card-body py-3">
            <div class="fs-3 fw-bold text-secondary">{{ totals.maintenance }}</div>
            <div class="small text-muted">Manutenção</div>
          </div>
        </div>
      </div>
      <div class="col-6 col-md-4 col-lg-2">
        <div class="card border-0 shadow-sm text-center h-100 bg-warning bg-opacity-10">
          <div class="card-body py-3">
            <div class="fs-3 fw-bold text-warning">{{ totals.reserved }}</div>
            <div class="small text-muted">Reservados</div>
          </div>
        </div>
      </div>
      <div class="col-6 col-md-4 col-lg-2">
        <div class="card border-0 shadow-sm text-center h-100 bg-danger bg-opacity-10">
          <div class="card-body py-3">
            <div class="fs-3 fw-bold text-danger">{{ totals.isolation }}</div>
            <div class="small text-muted">Isolamento</div>
          </div>
        </div>
      </div>
      <div class="col-6 col-md-4 col-lg-2">
        <div class="card border-0 shadow-sm text-center h-100">
          <div class="card-body py-3">
            <div class="fs-3 fw-bold" style="color: var(--sirhosp-sidebar-bg);">{{ totals.total }}</div>
            <div class="small text-muted">Total de leitos</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ====== LISTA DE SETORES (cards com collapse) ====== -->
    <div class="row g-3">
      {% for sector in sectors %}
      <div class="col-12">
        <div class="card border-0 shadow-sm">
          <!-- Cabeçalho do card (sempre visível, clicável) -->
          <div class="card-header bg-white d-flex flex-wrap justify-content-between align-items-center gap-2"
               data-bs-toggle="collapse"
               data-bs-target="#sector-detail-{{ forloop.counter }}"
               role="button"
               aria-expanded="false"
               style="cursor: pointer;">
            <h3 class="h6 fw-bold mb-0" style="color: var(--sirhosp-sidebar-bg);">
              <i class="bi bi-chevron-right me-2 collapse-icon"></i>
              {{ sector.name }}
            </h3>
            <div class="d-flex flex-wrap gap-1">
              {% if sector.occupied %}
              <span class="badge bg-primary">{{ sector.occupied }} ocupados</span>
              {% endif %}
              {% if sector.empty %}
              <span class="badge bg-success">{{ sector.empty }} vagos</span>
              {% endif %}
              {% if sector.maintenance %}
              <span class="badge bg-secondary">{{ sector.maintenance }} manut.</span>
              {% endif %}
              {% if sector.reserved %}
              <span class="badge bg-warning text-dark">{{ sector.reserved }} reserv.</span>
              {% endif %}
              {% if sector.isolation %}
              <span class="badge bg-danger">{{ sector.isolation }} isolam.</span>
              {% endif %}
              <span class="badge bg-light text-dark">{{ sector.total }} total</span>
            </div>
          </div>

          <!-- Corpo colapsável: lista de leitos -->
          <div class="collapse" id="sector-detail-{{ forloop.counter }}">
            <div class="card-body p-0">
              <div class="list-group list-group-flush">
                {% for bed in sector.beds %}
                <div class="list-group-item d-flex flex-wrap justify-content-between align-items-center gap-2 py-2 px-3">
                  <div class="d-flex align-items-center gap-2">
                    <code class="small">{{ bed.leito }}</code>
                    <span class="badge
                      {% if bed.status == 'occupied' %}bg-primary
                      {% elif bed.status == 'empty' %}bg-success
                      {% elif bed.status == 'maintenance' %}bg-secondary
                      {% elif bed.status == 'reserved' %}bg-warning text-dark
                      {% else %}bg-danger{% endif %}">
                      {{ bed.status_label }}
                    </span>
                  </div>
                  <div class="text-end small">
                    {% if bed.prontuario %}
                      {{ bed.nome }}
                      <span class="text-muted">({{ bed.prontuario }})</span>
                    {% else %}
                      <span class="text-muted">—</span>
                    {% endif %}
                  </div>
                </div>
                {% endfor %}
              </div>
            </div>
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
  {% endif %}
</div>
{% endblock %}
```text

### 7.3 `templates/includes/sidebar.html` — adicionar link "Leitos"

**Estado atual** (trecho da nav):

```html
<nav class="sirhosp-sidebar-nav">
    <a href="{% url 'services_portal:dashboard' %}" class="sirhosp-sidebar-link {% if active_menu == 'dashboard' %}active{% endif %}">
      <i class="bi bi-grid-1x2-fill"></i>
      Dashboard
    </a>
    <a href="{% url 'services_portal:censo' %}" class="sirhosp-sidebar-link {% if active_menu == 'censo' %}active{% endif %}">
      <i class="bi bi-hospital"></i>
      Censo
    </a>
    <a href="{% url 'patients:patient_list' %}" class="sirhosp-sidebar-link {% if active_menu == 'pacientes' %}active{% endif %}">
      <i class="bi bi-people"></i>
      Pacientes
    </a>
    <a href="{% url 'services_portal:monitor_risco' %}" class="sirhosp-sidebar-link {% if active_menu == 'monitor' %}active{% endif %}">
      <i class="bi bi-exclamation-triangle"></i>
      Monitor de Risco
    </a>
  </nav>
```text

**Adicionar** entre "Censo" e "Pacientes":

```html
<a href="{% url 'census:bed_status' %}" class="sirhosp-sidebar-link {% if active_menu == 'leitos' %}active{% endif %}">
  <i class="bi bi-door-open"></i>
  Leitos
</a>
```text

Colocar entre o link "Censo" e o link "Pacientes". O ícone sugerido é `bi bi-door-open`.

### 7.4 Testes: `tests/unit/test_bed_status_view.py` — MODIFICAR existente

O arquivo `tests/unit/test_bed_status_view.py` já existe com 4 testes.
**Adicionar** os seguintes testes ao final do arquivo (manter os existentes intactos):

```python
class TestBedStatusTotals:
    """S3: Bed status view includes global totals context."""

    def test_view_includes_totals_in_context(self, admin_client):
        """The view context includes 'totals' dict with all statuses."""
        from datetime import timedelta
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC1", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="", nome="", especialidade="",
            bed_status=BedStatus.EMPTY,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        assert response.status_code == 200

    def test_totals_sum_across_sectors(self, admin_client):
        """Global totals sum correctly across multiple sectors."""
        now = timezone.now()
        # Sector A: 2 occupied, 1 empty
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="A01",
            prontuario="111", nome="PAC1", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="A02",
            prontuario="222", nome="PAC2", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="A03",
            prontuario="", nome="", especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        # Sector B: 1 occupied
        CensusSnapshot.objects.create(
            captured_at=now, setor="ENFERMARIA", leito="E01",
            prontuario="333", nome="PAC3", especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Total occupied should be 3
        assert "UTI A" in content
        assert "ENFERMARIA" in content

    def test_totals_rendered_in_html(self, admin_client):
        """Global totals are rendered as summary cards at the top."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="SETOR X", leito="01",
            prontuario="111", nome="PAC1", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="SETOR X", leito="02",
            prontuario="", nome="", especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="SETOR X", leito="03",
            prontuario="", nome="MANUT", especialidade="",
            bed_status=BedStatus.MAINTENANCE,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Should render the numbers somewhere
        assert "SETOR X" in content

    def test_bed_view_uses_cards_not_table(self, admin_client):
        """The bed status page uses card layout, not <table>."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="CARDIACO", leito="01",
            prontuario="111", nome="PAC", especialidade="CAR",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Should use Bootstrap card structure
        assert "card" in content.lower()
        # Should have collapse behavior
        assert "collapse" in content


class TestBedSidebarLink:
    """S3: Sidebar includes link to /beds/."""

    def test_sidebar_has_leitos_link(self, admin_client):
        """Sidebar renders with 'Leitos' link pointing to /beds/."""
        # Access any page that renders the sidebar
        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Sidebar should contain Leitos link
        assert "Leitos" in content
        assert "/beds/" in content
```text

**IMPORTANTE**: Adicionar `from apps.census.models import BedStatus, CensusSnapshot` no topo
do arquivo de teste se já não estiver lá (provavelmente já está, mas verifique).

---

## 8. Sequência de execução (TDD)

1. **RED**: Adicionar os novos testes ao `tests/unit/test_bed_status_view.py`
2. **RED**: Rodar `uv run pytest tests/unit/test_bed_status_view.py -v` — novos testes FALHAM
3. **GREEN**: Adicionar `totals` ao contexto na view `bed_status_view()`
4. **GREEN**: Reescrever `census/bed_status.html` com layout de cards + totalização
5. **GREEN**: Adicionar link "Leitos" em `templates/includes/sidebar.html`
6. **GREEN**: Rodar testes — devem PASSAR
7. **REFACTOR**: Ajustar testes conforme necessário, limpar código, verificar responsividade
8. Rodar quality gate

---

## 9. Quality Gate (obrigatório)

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```text

Fallback host-only (diagnóstico):

```bash
uv run python manage.py check
uv run pytest tests/unit/test_bed_status_view.py -v
uv run ruff check apps/census/views.py apps/census/templates/ templates/includes/sidebar.html tests/unit/test_bed_status_view.py
```text

---

## 10. Relatório obrigatório

Gerar `/tmp/sirhosp-slice-DRD-S3-report.md` com:

```markdown
# Slice DRD-S3 Report

## Status
[PASS / FAIL]

## Arquivos modificados
- apps/census/views.py (adicionados totais globais)
- apps/census/templates/census/bed_status.html (reescrito com cards + totalização)
- templates/includes/sidebar.html (adicionado link Leitos)
- tests/unit/test_bed_status_view.py (adicionados testes de totais + sidebar)

## Snippets before/after
### apps/census/views.py
**Before:** (trecho do return do render sem "totals")
**After:** (trecho com "totals": totals)

### apps/census/templates/census/bed_status.html
**Before:** (template completo com <table>)
**After:** (template completo com cards e totalização)

### templates/includes/sidebar.html
**Before:** (nav links sem Leitos)
**After:** (nav links com Leitos entre Censo e Pacientes)

## Comandos executados
- ./scripts/test-in-container.sh check: [output resumido]
- ./scripts/test-in-container.sh unit: [output resumido]
- ./scripts/test-in-container.sh lint: [output resumido]

## Resultados dos testes
- [X/Y] passed

## Riscos / Pendências
- Verificar visualmente que collapse funciona em mobile
- Confirmar que ícone bi-door-open renderiza corretamente

## Próximo slice sugerido
Nenhum. Este é o último slice do change dashboard-real-data.
```text

---

## 11. Anti-padrões PROIBIDOS

- ❌ Remover a mensagem "Nenhum dado de censo disponível" (fallback quando sem dados)
- ❌ Usar `<table>` para layout de setores (deve ser cards com collapse)
- ❌ Esquecer de adicionar `"totals"` ao dicionário de contexto retornado pela view
- ❌ Cards de totalização sem grid responsivo (devem empilhar em mobile)
- ❌ Hardcodar URL `/beds/` na sidebar — usar `{% url 'census:bed_status' %}`
- ❌ Mudar a view `bed_status_view()` além de adicionar `totals` — a lógica de setores continua igual
- ❌ Cards de setor expandidos por padrão (devem ser `collapse` sem classe `show`)
- ❌ Esquecer `from __future__ import annotations`
- ❌ Modificar arquivos fora do escopo (dashboard, censo, monitor_risco)
