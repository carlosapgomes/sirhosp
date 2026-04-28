# Design: discharge-daily-tracking

## Context

O SIRHOSP já extrai altas 3x/dia via `extract_discharges` (management command
que executa Playwright → PyMuPDF → `process_discharges()`). O campo
`Admission.discharge_date` é populado com `timezone.now()` no momento da
extração, refletindo a data em que a alta foi registrada no sistema fonte.

O dashboard atual exibe "Altas (24h)" com sliding window:

```python
altas_24h = Admission.objects.filter(
    discharge_date__gte=timezone.now() - timedelta(hours=24),
).count()
```

Essa métrica é volátil (muda ao longo do dia conforme a janela desliza) e
impossibilita comparação entre dias ou análise de tendências.

**Este change** adiciona tracking diário, muda o dashboard para "altas no dia"
e introduz um gráfico com médias móveis — sem alterar o pipeline de extração.

## Goals / Non-Goals

**Goals:**

- Rastrear contagem diária de altas em tabela dedicada (`DailyDischargeCount`)
- Exibir "Altas no dia" (contagem do dia corrente) no dashboard
- Oferecer gráfico de barras diárias + médias móveis (3, 10, 30 dias) em
  `/painel/altas/`
- Período do gráfico customizável via `?dias=N`, default 90 dias
- Management command `refresh_daily_discharge_counts` executável standalone
  e também chamado automaticamente ao final de `extract_discharges`

**Non-Goals:**

- Alterar `extract_discharges.py` (Playwright/PyMuPDF) ou `process_discharges()`
- Popular dados retroativos (sistema não implantado)
- Granularidade por setor/ala (apenas total diário)
- Introduzir Celery/Redis ou novas dependências Python
- Modificar modelos `Patient` ou `Admission`

## Decisions

### 1. Modelo `DailyDischargeCount` no app `discharges`

**Decisão**: Adicionar `apps/discharges/models.py` com um modelo simples.

**Alternativas consideradas**:

- Colocar em `apps/patients/` — rejeitado: polui o domínio de pacientes com
  dados agregados operacionais
- Criar app separado — rejeitado: overkill para um modelo só

**Estrutura**:

```python
class DailyDischargeCount(models.Model):
    date = models.DateField(unique=True)
    count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### 2. Management command `refresh_daily_discharge_counts`

**Decisão**: Comando standalone que pode ser executado manualmente ou chamado
via `call_command()` ao final de `extract_discharges`.

**Algoritmo**:

```python
# 1. Agrupa Admission.discharge_date por dia (timezone America/Sao_Paulo)
from django.db.models import Count
from django.db.models.functions import TruncDate

counts = (
    Admission.objects
    .filter(discharge_date__isnull=False)
    .annotate(day=TruncDate("discharge_date"))
    .values("day")
    .annotate(count=Count("id"))
    .order_by("day")
)

# 2. Upsert: update_or_create para cada (day, count)
for entry in counts:
    DailyDischargeCount.objects.update_or_create(
        date=entry["day"],
        defaults={"count": entry["count"]},
    )
```

**Alternativas consideradas**:

- Trigger de banco (PostgreSQL) — rejeitado: lógica fica invisível no ORM,
  difícil de testar e dar manutenção
- Sinal Django (`post_save` no `Admission`) — rejeitado: processamento batch
  é mais simples e evita problemas de concorrência em múltiplas extrações
- Contar direto na view do gráfico — rejeitado: query agregada em tabela
  potencialmente grande a cada request, sem cache

**Acionamento**: Ao final do `handle()` do `extract_discharges`, após
`run.status = "succeeded"`:

```python
from django.core.management import call_command
call_command("refresh_daily_discharge_counts")
```

### 3. Query do dashboard: de sliding window para dia corrente

**Decisão**:

```python
from django.utils import timezone

altas_hoje = Admission.objects.filter(
    discharge_date__date=timezone.localdate(),
).count()
```

`timezone.localdate()` retorna a data de hoje no timezone configurado
(`America/Sao_Paulo`, UTC-3, mesmo offset de America/Bahia). O lookup
`__date` extrai a data do campo `discharge_date` no timezone da conexão.

**Alternativas consideradas**:

- `discharge_date__gte=hoje_midnight` com cálculo manual de midnight —
  rejeitado: verboso e propenso a erro de timezone
- `discharge_date__date=date.today()` sem timezone — rejeitado: `date.today()`
  usa timezone do sistema operacional, não do Django

### 4. Gráfico: Chart.js via CDN

**Decisão**: Chart.js carregado de `cdn.jsdelivr.net`, renderizado client-side
com dados passados como JSON no template.

**Alternativas consideradas**:

- Plotly (Python) — rejeitado: adiciona dependência pesada, renderização
  server-side desnecessária para ~365 pontos
- `django-chartjs` — rejeitado: abstração desnecessária, acoplamento extra
- Matplotlib com imagem estática — rejeitado: sem interatividade

**Template approach**:

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js">
</script>
<script>
  const data = {{ chart_data|safe }};
  // Render bar chart + 3 MA line datasets
</script>
```

### 5. Cálculo de médias móveis: server-side (Python)

**Decisão**: Calcular MAs na view Python e serializar para o template.

```python
def _moving_average(values: list[int], window: int) -> list[float | None]:
    """Returns MA values; first (window-1) positions are None."""
    result: list[float | None] = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(None)
        else:
            window_slice = values[i - window + 1 : i + 1]
            result.append(round(sum(window_slice) / window, 1))
    return result
```

**Alternativas consideradas**:

- Calcular no frontend (JS) — rejeitado: mais código JS, mais difícil de
  testar, sem ganho real já que os dados são pequenos
- Calcular no banco (window functions) — rejeitado: complexidade desnecessária,
  a tabela `DailyDischargeCount` terá poucos registros

### 6. Período do gráfico: sempre até dia anterior

**Decisão**: O gráfico sempre exibe dados do primeiro dia disponível até
**ontem** (`date < today`). O dia corrente nunca aparece na série porque está
em andamento (extrações ainda podem ocorrer).

```python
today = timezone.localdate()
entries = DailyDischargeCount.objects.filter(
    date__lt=today,  # exclusivo: não inclui hoje
).order_by("date")[:dias]  # LIMIT para período customizado
```

### 7. Card do dashboard clicável

**Decisão**: O card "Altas no dia" no dashboard será envolvido em um `<a>` com
classes Bootstrap preservando a aparência visual.

```html
<a href="{% url 'services_portal:discharge_chart' %}"
   class="text-decoration-none">
  <div class="sirhosp-stat-card d-flex align-items-center gap-3">
    <!-- ícone, valor, label -->
  </div>
</a>
```

## Data Flow

```text
┌──────────────────────────────────────────────────────────────┐
│ systemd timer: 11:00, 19:00, 23:55                           │
│   │                                                          │
│   ▼                                                          │
│ extract_discharges (management command)                      │
│   │                                                          │
│   ├─▶ Playwright → PyMuPDF → process_discharges()            │
│   │   └─▶ Admission.discharge_date = timezone.now()          │
│   │                                                          │
│   └─▶ call_command("refresh_daily_discharge_counts")  ← NOVO │
│           │                                                  │
│           ├─▶ SELECT date(discharge_date), COUNT(*)          │
│           │    FROM admissions                                │
│           │    WHERE discharge_date IS NOT NULL               │
│           │    GROUP BY date(discharge_date)                  │
│           │                                                  │
│           └─▶ UPSERT INTO daily_discharge_counts             │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ Dashboard ("/painel/")                                       │
│   │                                                          │
│   ├─▶ altas_hoje = Admission.objects.filter(                │
│   │       discharge_date__date=timezone.localdate()          │
│   │   ).count()                                              │
│   │                                                          │
│   └─▶ Card "Altas no dia": {{ stats.altas_hoje }}           │
│        [clicável] → /painel/altas/                           │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ Gráfico ("/painel/altas/")                                   │
│   │                                                          │
│   ├─▶ Query DailyDischargeCount (date < today, LIMIT ?dias) │
│   ├─▶ Calcula MAs (3, 10, 30) server-side                   │
│   │                                                          │
│   └─▶ Template renderiza Chart.js:                           │
│        - Bar dataset: contagem diária                        │
│        - Line dataset 1: MA-3                                │
│        - Line dataset 2: MA-10                               │
│        - Line dataset 3: MA-30                               │
└──────────────────────────────────────────────────────────────┘
```

## Risks / Trade-offs

### Risco: `refresh_daily_discharge_counts` faz full scan da tabela `admissions`

**Mitigação**: A tabela `admissions` é pequena (hospital de porte médio).
Índice em `discharge_date` já existe ou será criado automaticamente pela
migration. Se no futuro a tabela crescer, o comando pode ser otimizado com
`filter(discharge_date__gte=ultimo_dia_processado)`.

### Risco: Falha na extração deixa `DailyDischargeCount` desatualizado

Se `extract_discharges` falhar, o `refresh_daily_discharge_counts` não é
chamado. No dia seguinte, a primeira extração bem-sucedida atualiza o contador
do dia anterior (pois o comando faz full recálculo de todos os dias).

**Mitigação**: O comando faz full recálculo (não incremental), então dias
passados são corrigidos retroativamente na próxima execução bem-sucedida.

### Risco: Extração das 23:55 com término após meia-noite

Se a extração iniciar às 23:55 e terminar às 00:02, o `discharge_date` terá
data do dia seguinte (via `timezone.now()`), não do dia da alta.

**Mitigação**: O timeout de 10 minutos garante que a extração termine antes
da virada. O `RandomizedDelaySec=120` no systemd timer adiciona pequena
variação, mas o script é rápido (~30-60 segundos típicos). Risco baixo.

### Risco: Duas extrações consecutivas processam o mesmo paciente

**Mitigação**: `process_discharges()` já é idempotente — pacientes com
`discharge_date` preenchido são contados como `already_discharged` e não são
alterados.

### Risco: Chart.js indisponível (CDN offline)

**Mitigação**: Degradação graciosa — sem Chart.js, a página mostra uma tabela
simples com os dados (fallback HTML). O SIRHOSP é uma aplicação interna, não
pública; dependência de CDN é aceitável na fase 1.

## Open Questions

- Nenhuma pendente. Todas as decisões foram tomadas com base nas respostas do
  usuário durante a fase de esclarecimento.
