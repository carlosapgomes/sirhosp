# SLICE-PMT-S5: Página Setores > Indicadores

## Handoff para executor LLM (contexto zero)

Você está recebendo este arquivo como única fonte de instrução. Antes de
codificar, leia **obrigatoriamente** nesta ordem:

1. `/projects/dev/sirhosp/AGENTS.md` — stack, comandos, política de testes
2. `/projects/dev/sirhosp/PROJECT_CONTEXT.md` — visão geral do sistema
3. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/proposal.md`
4. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/design.md`
5. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/tasks.md`
6. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/specs/sector-indicators-page/spec.md`

**Implemente SOMENTE o Slice PMT-S5 e PARE.**

**Pré-requisito:** Slice PMT-S4 concluído (sidebar com menu Setores já existe
e o link "Indicadores" no sidebar pode estar apontando para `#` ou rota dummy).

---

## Objetivo

Criar a página **Setores > Indicadores** (`/setores/indicadores/`) com 4 cards
analíticos baseados nos dados de `PatientMovement`.

---

## Escopo máximo de arquivos

Você pode alterar **no máximo 5 arquivos**:

| Arquivo | Ação |
| --- | --- |
| `apps/services_portal/views.py` | Adicionar view `sector_indicators` |
| `apps/services_portal/urls.py` | Adicionar rota `/setores/indicadores/` |
| `apps/services_portal/templates/services_portal/sector_indicators.html` | NOVO — template |
| `apps/services_portal/templates/base_sidebar.html` | Corrigir link Indicadores se ainda aponta para `#` |
| `tests/unit/test_services_portal_sectors.py` | Adicionar testes de indicadores |

Se precisar alterar qualquer outro arquivo, **pare e reporte bloqueio**.

---

## Especificação

### 1. View `sector_indicators`

Arquivo: `apps/services_portal/views.py`

```python
@login_required
def sector_indicators(request: HttpRequest) -> HttpResponse:
```

**Parâmetros GET:**
- `dias` — período (7, 30, 90, 180). Default: 30.
- `origem` — setor de origem para filtrar o card de fluxo (opcional).

**A view deve calcular 4 indicadores e passá-los no contexto:**

#### Card 1: Permanência média por setor

```python
from django.db.models import Avg, F, ExpressionWrapper, DurationField

avg_stay = (
    PatientMovement.objects
    .filter(first_seen_at__gte=cutoff)
    .values("sector")
    .annotate(
        avg_days=Avg(
            ExpressionWrapper(
                F("last_seen_at") - F("first_seen_at"),
                output_field=DurationField(),
            )
        )
    )
    .order_by("-avg_days")
)
# Converter timedelta para dias
for entry in avg_stay:
    entry["avg_days"] = round(entry["avg_days"].total_seconds() / 86400, 1)
```

Estrutura do contexto: lista de `{"sector": str, "avg_days": float}`.

#### Card 2: Setores que mais recebem de origem X

Se `origem` foi passado:

```python
top_destinations = (
    PatientMovement.objects
    .filter(origin__icontains=origem, first_seen_at__gte=cutoff)
    .values("sector")
    .annotate(count=Count("id"))
    .order_by("-count")[:10]
)
```

Se `origem` não foi passado, mostra os top 10 setores de destino globalmente.

Contexto: `{"origin_filter": origem or "", "origin_options": [...], "destinations": [...]}`.
`origin_options` deve ser a lista de setores disponíveis (mesma query do S4).

#### Card 3: Pacientes > 15 dias no mesmo setor

```python
from datetime import timedelta

long_stay_threshold = timezone.now() - timedelta(days=15)

long_stay = (
    PatientMovement.objects
    .filter(
        discharge_type="",
        first_seen_at__lte=long_stay_threshold,
    )
    .values("sector")
    .annotate(count=Count("patient_id", distinct=True))
    .order_by("-count")
)
```

Contexto: `{"long_stay": [{"sector": str, "count": int}, ...]}`.

#### Card 4: Gargalos (entradas > saídas)

Comparar entradas vs saídas por setor no período:

```python
entries = (
    PatientMovement.objects
    .filter(first_seen_at__gte=cutoff)
    .values("sector")
    .annotate(entry_count=Count("id"))
)

exits = (
    PatientMovement.objects
    .filter(last_seen_at__gte=cutoff)
    .exclude(discharge_type="")
    .values("sector")
    .annotate(exit_count=Count("id"))
)
```

Depois combine em Python: para cada setor, calcule `net = entry_count - exit_count`.
Filtre apenas setores com `net > 0`, ordenado por `net` decrescente.

Contexto: `{"bottlenecks": [{"sector": str, "entries": int, "exits": int, "net": int}, ...]}`.

### 2. Template `sector_indicators.html`

Siga o mesmo padrão visual de `sector_occupation.html`.

```text
┌─ Breadcrumb: Dashboard > Setores > Indicadores
├─ Título + descrição
├─ Seletor de período: [7d] [30d] [90d] [180d]
├─ Grid 2x2 de cards:
│   ┌─────────────────────┐ ┌──────────────────────┐
│   │ ⏱️ Permanência Média │ │ 🔀 Fluxo entre Setores │
│   │    por Setor         │ │                        │
│   │                      │ │ Origem: [dropdown ▾]   │
│   │ UTI ADULTO   8.2d    │ │ 1. ENF ADULTO   142   │
│   │ ENF ADULTO   5.1d    │ │ 2. UTI ADULTO    89   │
│   │ PS ADULTO    0.8d    │ │ 3. CIR ADULTO    34   │
│   └─────────────────────┘ └──────────────────────┘
│   ┌─────────────────────┐ ┌──────────────────────┐
│   │ 🚨 Longa Permanência │ │ ⚠️ Gargalos           │
│   │    (>15 dias)        │ │                      │
│   │                      │ │ ENF ADULTO  +8       │
│   │ ENF ADULTO     12    │ │ UTI ADULTO  +3       │
│   │ UTI ADULTO      5    │ │ PS ADULTO   +2       │
│   └─────────────────────┘ └──────────────────────┘
└─
```

Cada card deve ter:
- Título com ícone
- Lista de setores com valores (top 5-10)
- Estado vazio: "Nenhum dado no período" quando a lista for vazia

### 3. URL

```python
path("setores/indicadores/", views.sector_indicators, name="sector_indicators"),
```

### 4. Sidebar

Se o link "Indicadores" no sidebar do PMT-S4 ainda estiver apontando para
`#`, corrija para `{% url 'services_portal:sector_indicators' %}`.

---

## Metodologia TDD

### 1. RED — Escreva testes que falham

Adicione ao arquivo `tests/unit/test_services_portal_sectors.py`:

| Teste | O que verifica |
| --- | --- |
| `test_indicators_page_requires_auth` | Anônimo → redirect. |
| `test_indicators_page_renders_authenticated` | HTTP 200. |
| `test_indicators_avg_stay_by_sector` | Contexto contém `avg_stay` com dados corretos. Cria 2 movimentos com first_seen/last_seen com 5 dias de diferença. |
| `test_indicators_avg_stay_empty_period` | Sem dados no período → lista vazia, sem erro. |
| `test_indicators_top_destinations_from_origin` | Cria 3 movimentos com origin="PS", 2 vão para ENF, 1 para UTI. `destinations` = [{"sector": "ENF", "count": 2}, {"sector": "UTI", "count": 1}]. |
| `test_indicators_top_destinations_no_origin_filter` | Sem `?origem=`, mostra todos os destinos. |
| `test_indicators_long_stay_patients` | Cria movimento com first_seen_at = 20 dias atrás, discharge_type="". `long_stay` inclui esse setor. |
| `test_indicators_long_stay_excludes_discharged` | Movimento antigo mas com discharge_type="A" → não aparece. |
| `test_indicators_bottlenecks` | 5 entradas, 2 saídas no setor ENF → `net=3`. |
| `test_indicators_bottlenecks_no_positive_net` | Entradas ≤ saídas → lista vazia. |
| `test_indicators_empty_state_all_cards` | Sem PatientMovement no banco → todas as listas vazias, HTTP 200. |

### 2. GREEN — Implemente o mínimo

- Adicione a view e os 4 cálculos.
- Crie o template com grid 2x2.
- Corrija o link no sidebar.
- **Não adicione gráficos, JavaScript ou animações.**

### 3. REFACTOR

- Se alguma query for muito complexa, extraia para um helper privado na view
  ou para um método no manager de `PatientMovement`.
- Verifique que `select_related`/`prefetch_related` são usados onde necessário.

---

## Gates de validação

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

---

## Relatório obrigatório

Gere `/tmp/sirhosp-slice-PMT-S5-report.md`:

```markdown
# Relatório SLICE-PMT-S5

## 1. Resumo

## 2. Checklist de aceite
- [ ] Testes RED escritos e falharam
- [ ] View sector_indicators implementada
- [ ] 4 indicadores calculados corretamente
- [ ] Template com grid 2x2
- [ ] Sidebar link corrigido
- [ ] Todos os testes passam
- [ ] Lint sem erros

## 3. Arquivos alterados

## 4. Fragmentos antes/depois

## 5. Comandos executados e resultados

## 6. Riscos e pendências
- Cálculos de agregação podem ser pesados com volume real de dados
- Se necessário, adicionar índices ou cache em change futuro

## 7. Próximo passo sugerido
Change concluída. Considerar: reprocessamento de snapshots históricos,
adição de gráficos nas páginas de setor, exportação CSV.
```

---

## Stop Rule

- **Não** implemente features além dos 4 indicadores.
- **Não** altere modelos, migrations ou serviços.
- Ao terminar, **pare**. A change está concluída.
