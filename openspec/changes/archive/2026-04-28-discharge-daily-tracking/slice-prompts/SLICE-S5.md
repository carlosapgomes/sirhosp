# SLICE-S5: Página de gráfico — view + template Chart.js

## Handoff / Contexto de Entrada

**Change**: `discharge-daily-tracking` — rastreamento diário de altas.

**Slice S4 concluído**:

- Dashboard mostra "Altas no dia" com contagem do dia corrente
- Card é clicável e linka para `/painel/altas/`
- Rota `discharge_chart` já existe em `urls.py` (placeholder)
- `timezone.localdate()` usa `America/Bahia`

**Banco de dados disponível**:

- `DailyDischargeCount(date, count)` populado via
  `refresh_daily_discharge_counts`
- `Admission.discharge_date` populado pelo `extract_discharges`

**O que você vai construir neste slice**:

1. View `discharge_chart()` que consulta `DailyDischargeCount`, calcula
   médias móveis (3, 10, 30 dias) e renderiza template
2. Template `discharge_chart.html` com Chart.js 4.4.0 via CDN:
   - Bar chart para contagem diária
   - 3 linhas de média móvel sobrepostas
   - Seletor de período (30, 60, 90, 180, 365 dias)
   - Hoje NUNCA aparece no gráfico (série sempre até ontem)

**Último slice (S6)**: Quality gate e validação final.

## Arquivos que você vai tocar (limite: 3)

| Arquivo | Ação |
| --- | --- |
| `apps/services_portal/views.py` | **Modificar** — adicionar `discharge_chart()` + `_moving_average()` |
| `apps/services_portal/templates/services_portal/discharge_chart.html` | **Criar** — template com Chart.js |
| `tests/unit/test_services_portal_dashboard.py` | **Modificar** — adicionar testes da view |

**NÃO toque** em: models.py, management commands, dashboard.html, urls.py,
outros apps.

## TDD Workflow (RED → GREEN → REFACTOR)

### RED: Escreva os testes primeiro

Adicione ao final de `tests/unit/test_services_portal_dashboard.py`:

```python
from datetime import date, timedelta

from apps.discharges.models import DailyDischargeCount


@pytest.mark.django_db
class TestDischargeChartView:
    """Tests for /painel/altas/ discharge chart page."""

    def _create_counts(self, days: int, start_count: int = 5):
        """Helper: create DailyDischargeCount entries for last N days."""
        today = timezone.localdate()
        for i in range(days):
            day = today - timedelta(days=days - i)
            DailyDischargeCount.objects.create(date=day, count=start_count + i)

    def test_chart_requires_authentication(self, client):
        """Anonymous users are redirected to login."""
        url = reverse("services_portal:discharge_chart")
        response = client.get(url)
        assert response.status_code == 302

    def test_chart_accessible_when_authenticated(self, admin_client):
        """Authenticated users can access the chart page."""
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200

    def test_chart_default_90_days(self, admin_client):
        """Chart shows data for last 90 days by default (through yesterday)."""
        self._create_counts(120)  # more than 90
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        # Should have at most 90 entries (minus today if today has data)
        assert len(chart_data["labels"]) <= 90
        # Today's date should NOT be in labels
        today_str = timezone.localdate().strftime("%d/%m/%Y")
        assert today_str not in chart_data["labels"]

    def test_chart_respects_dias_parameter(self, admin_client):
        """?dias=30 shows only last 30 days."""
        self._create_counts(60)
        url = reverse("services_portal:discharge_chart") + "?dias=30"
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert len(chart_data["labels"]) <= 30

    def test_chart_invalid_dias_falls_back_to_90(self, admin_client):
        """Invalid ?dias=abc falls back to default 90."""
        self._create_counts(100)
        url = reverse("services_portal:discharge_chart") + "?dias=abc"
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert len(chart_data["labels"]) <= 90

    def test_chart_context_has_all_ma_keys(self, admin_client):
        """Context contains labels, counts, ma3, ma10, ma30."""
        self._create_counts(35)
        url = reverse("services_portal:discharge_chart") + "?dias=30"
        response = admin_client.get(url)
        chart_data = response.context["chart_data"]
        assert "labels" in chart_data
        assert "counts" in chart_data
        assert "ma3" in chart_data
        assert "ma10" in chart_data
        assert "ma30" in chart_data
        # All arrays same length
        n = len(chart_data["labels"])
        assert len(chart_data["counts"]) == n
        assert len(chart_data["ma3"]) == n
        assert len(chart_data["ma10"]) == n
        assert len(chart_data["ma30"]) == n

    def test_ma3_is_none_for_first_two_days(self, admin_client):
        """MA-3 is None for indices 0 and 1, value from index 2 onward."""
        self._create_counts(10)
        url = reverse("services_portal:discharge_chart") + "?dias=10"
        response = admin_client.get(url)
        ma3 = response.context["chart_data"]["ma3"]
        assert ma3[0] is None
        assert ma3[1] is None
        assert ma3[2] is not None  # day 3 has a value

    def test_chart_handles_empty_data(self, admin_client):
        """Page renders without error when no DailyDischargeCount exists."""
        url = reverse("services_portal:discharge_chart")
        response = admin_client.get(url)
        assert response.status_code == 200
        chart_data = response.context["chart_data"]
        assert chart_data["labels"] == []
        assert chart_data["counts"] == []
```

Rode e confirme que **falham** (view não implementada):

```bash
uv run pytest tests/unit/test_services_portal_dashboard.py -q -k "DischargeChart"
```

### GREEN: Implementação

**1. `apps/services_portal/views.py`** — adicione no final do arquivo:

```python
from __future__ import annotations

import json
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.discharges.models import DailyDischargeCount


def _moving_average(values: list[int], window: int) -> list[float | None]:
    """Calculate simple moving average over `window` days.

    First (window-1) positions are None (insufficient history).
    """
    result: list[float | None] = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(None)
        else:
            window_slice = values[i - window + 1 : i + 1]
            result.append(round(sum(window_slice) / window, 1))
    return result


@login_required
def discharge_chart(request: HttpRequest) -> HttpResponse:
    """Discharge chart page with daily bars and moving averages.

    Query parameter:
        ?dias=N  — number of days to display (default: 90)

    The chart always shows data through YESTERDAY (today is excluded
    because it is still in progress).
    """
    # Parse ?dias parameter
    dias_str = request.GET.get("dias", "90").strip()
    try:
        dias = int(dias_str)
        if dias < 1:
            dias = 90
    except (ValueError, TypeError):
        dias = 90

    today = timezone.localdate()

    # Query: exclude today, limit to requested period
    entries = (
        DailyDischargeCount.objects
        .filter(date__lt=today)
        .order_by("date")
    )

    # Apply limit after ordering (descending + reverse for correct window)
    # We want the LAST `dias` days, so we get the most recent first,
    # slice, then reverse for chronological order.
    entries_recent = list(
        DailyDischargeCount.objects
        .filter(date__lt=today)
        .order_by("-date")[:dias]
    )
    entries_recent.reverse()  # chronological order

    labels = [e.date.strftime("%d/%m/%Y") for e in entries_recent]
    counts = [e.count for e in entries_recent]

    chart_data = {
        "labels": labels,
        "counts": counts,
        "ma3": _moving_average(counts, 3),
        "ma10": _moving_average(counts, 10),
        "ma30": _moving_average(counts, 30),
    }

    context = {
        "page_title": "Altas por Dia",
        "chart_data": json.dumps(chart_data),
        "dias": dias,
        "period_options": [30, 60, 90, 180, 365],
    }
    return render(request, "services_portal/discharge_chart.html", context)
```

**Nota**: A função `discharge_chart` deve ser adicionada ao arquivo
`views.py` existente. Os imports `json`, `DailyDischargeCount` precisam
ser adicionados ao topo. O import `date` já pode existir.

**2. Template** `apps/services_portal/templates/services_portal/discharge_chart.html`:

```html
{% extends "base_sidebar.html" %}

{% block title %}Altas por Dia — SIRHOSP{% endblock %}

{% block content %}
<div class="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-4">
  <div>
    <h2 class="h5 fw-bold mb-1" style="color: var(--sirhosp-sidebar-bg);">Altas por Dia</h2>
    <p class="text-muted small mb-0">Contagem diária de altas com médias móveis</p>
  </div>
</div>

<!-- Period selector -->
<div class="d-flex gap-2 mb-4 flex-wrap">
  <span class="text-muted small align-self-center me-2">Período:</span>
  {% for option in period_options %}
    <a href="?dias={{ option }}"
       class="btn btn-sm {% if option == dias %}btn-primary{% else %}btn-outline-primary{% endif %}">
      {{ option }} dias
    </a>
  {% endfor %}
</div>

<!-- Chart -->
<div class="card border-0 shadow-sm mb-4">
  <div class="card-body">
    {% if chart_data.counts %}
    <canvas id="dischargeChart" style="max-height: 400px;"></canvas>
    {% else %}
    <div class="text-center py-5 text-muted">
      <i class="bi bi-bar-chart" style="font-size: 3rem;"></i>
      <p class="mt-3">Nenhum dado de alta disponível.</p>
      <p class="small">Os dados começarão a aparecer após a primeira extração de altas.</p>
    </div>
    {% endif %}
  </div>
</div>

<!-- Legend -->
<div class="d-flex gap-4 flex-wrap small text-muted mb-4">
  <div class="d-flex align-items-center gap-2">
    <span style="display:inline-block;width:12px;height:12px;background:#0D6EFD;border-radius:2px;"></span>
    Barras: altas diárias
  </div>
  <div class="d-flex align-items-center gap-2">
    <span style="display:inline-block;width:20px;height:2px;background:#0D6EFD;"></span>
    MM 3 dias
  </div>
  <div class="d-flex align-items-center gap-2">
    <span style="display:inline-block;width:20px;height:2px;background:#F59E0B;"></span>
    MM 10 dias
  </div>
  <div class="d-flex align-items-center gap-2">
    <span style="display:inline-block;width:20px;height:2px;background:#DC2626;"></span>
    MM 30 dias
  </div>
</div>
{% endblock %}

{% block extra_js %}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
  const rawData = {{ chart_data|safe }};

  const ctx = document.getElementById('dischargeChart').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: rawData.labels,
      datasets: [
        {
          label: 'Altas',
          data: rawData.counts,
          backgroundColor: '#0D6EFD33',
          borderColor: '#0D6EFD',
          borderWidth: 1,
          order: 2,
        },
        {
          label: 'MM 3 dias',
          data: rawData.ma3,
          type: 'line',
          borderColor: '#0D6EFD',
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          spanGaps: false,
          order: 1,
        },
        {
          label: 'MM 10 dias',
          data: rawData.ma10,
          type: 'line',
          borderColor: '#F59E0B',
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          spanGaps: false,
          order: 1,
        },
        {
          label: 'MM 30 dias',
          data: rawData.ma30,
          type: 'line',
          borderColor: '#DC2626',
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          spanGaps: false,
          order: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      plugins: {
        legend: {
          display: false,
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            stepSize: 1,
          },
        },
      },
    },
  });
</script>
{% endblock %}
```

**Nota**: O block `extra_js` precisa existir no `base_sidebar.html`. Se não
existir, use `{% block scripts %}` ou o bloco equivalente do projeto.
**Verifique no `base_sidebar.html` qual bloco é usado para scripts
adicionais e ajuste.**

Confirme **verde**:

```bash
uv run pytest tests/unit/test_services_portal_dashboard.py -q
```

### REFACTOR

- Verifique o nome correto do block para scripts em `base_sidebar.html`
- `json.dumps` no context x `|safe` no template: ok, `chart_data` é sempre
  gerado server-side com dados controlados
- A legenda HTML duplica a do Chart.js (que está `display: false`) — é
  intencional para controle visual
- Confirme que `_moving_average([])` retorna `[]` sem erro

## Critérios de Sucesso (Auto-Avaliação Obrigatória)

- [ ] View `discharge_chart` implementada com `@login_required`
- [ ] Parâmetro `?dias=N` funcional com fallback para 90
- [ ] Query exclui hoje: `date__lt=today`
- [ ] `_moving_average` calcula corretamente com `None` nos primeiros
  `window-1` elementos
- [ ] Template renderiza Chart.js com 4 datasets (1 bar + 3 line)
- [ ] `spanGaps: false` para linhas quebrarem nos `None`
- [ ] Seletor de período com links e destaque visual
- [ ] Fallback "Nenhum dado disponível" quando `counts` vazio
- [ ] 8 testes passando (auth, acesso, default 90, ?dias=30, inválido,
  keys, ma3 None, vazio)
- [ ] `./scripts/test-in-container.sh check` sem erro
- [ ] `./scripts/test-in-container.sh unit` passando
- [ ] `./scripts/test-in-container.sh lint` sem erro

## Anti-Alucinação / Stop Rules

1. **NÃO modifique** a query do dashboard (já feita no S4).
2. **NÃO modifique** `DailyDischargeCount` ou `Admission`.
3. **NÃO use** outras bibliotecas de gráfico (Plotly, ApexCharts, etc).
   Apenas Chart.js 4.4.0 via CDN.
4. **Verifique** o nome do block de scripts no `base_sidebar.html` ANTES
   de escrever o template. Não assuma `extra_js`.
5. **Limite**: 3 arquivos. Se precisar de mais → PARE.
6. Se Chart.js não carregar do CDN → use fallback estático (tabela HTML).
   Documente no relatório.
7. Se `_moving_average` com `round` causar surpresa (ex: `round(2.5)` = 2
   em Python) → use `round(sum/win, 1)` mesmo; precisão de 1 casa decimal
   é suficiente.
8. Se não souber resolver em 30 minutos → PARE, documente, entregue
   relatório.

## Relatório Obrigatório

Gere `/tmp/sirhosp-slice-S5-report.md`:

```markdown
# Slice S5 Report: Gráfico view + template Chart.js

## Resumo
...

## Checklist de Aceite
- [ ] View discharge_chart com @login_required
- [ ] ?dias=N funcional
- [ ] date__lt=today (hoje excluído)
- [ ] _moving_average com None nos primeiros
- [ ] Template Chart.js com 4 datasets
- [ ] spanGaps: false
- [ ] Seletor de período
- [ ] Fallback vazio
- [ ] 8/8 testes passando
- [ ] check + unit + lint verdes

## Arquivos Alterados
- apps/services_portal/views.py (adicionadas ~60 linhas)
- apps/services_portal/templates/services_portal/discharge_chart.html (NOVO)
- tests/unit/test_services_portal_dashboard.py (adicionados ~100 linhas)

## Fragmentos Antes/Depois
(Colar trechos relevantes de cada arquivo)

## Comandos Executados
(Colar outputs)

## Riscos e Pendências
...

## Próximo Slice
S6: Quality gate e validação final
```

**Após gerar o relatório, PARE.**
