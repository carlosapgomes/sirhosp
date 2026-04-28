# Change Proposal: discharge-daily-tracking

## Why

O dashboard do SIRHOSP exibe "Altas (24h)" com uma sliding window sobre
`Admission.discharge_date`. Embora a extração de altas (`extract_discharges`)
já popule esse campo corretamente, a métrica de janela deslizante é inadequada
para gestão hospitalar: não permite acompanhamento de tendências, comparação
entre dias, nem cálculo de médias móveis — ferramentas essenciais para a
diretoria monitorar o fluxo de saída de pacientes.

O sistema fonte hospitalar fornece altas **do dia corrente** (sem data
explícita no PDF), e a extração roda 3x/dia (última às 23:55). Isso permite
que o SIRHOSP compute e armazene contagens diárias de altas, criando uma
série temporal auditável que viabiliza gráficos e análises de tendência.

## What Changes

### 1. Nova tabela de tracking diário

- Modelo `DailyDischargeCount` no app `discharges` com campos `date` (único) e
  `count`
- Management command `refresh_daily_discharge_counts` que agrupa
  `Admission.discharge_date` por dia e faz upsert na tabela de tracking
- Executado automaticamente ao final de `extract_discharges` quando bem-sucedido

### 2. Dashboard: de "Altas (24h)" para "Altas no dia"

- Query do dashboard alterada para contar altas com `discharge_date` no dia
  corrente (data do servidor), em vez da janela deslizante de 24h
- Label do card alterada de "Altas (24h)" para "Altas no dia"
- Card torna-se **clicável** e navega para `/painel/altas/`

### 3. Nova página de gráfico de altas

- URL `/painel/altas/` dentro do `services_portal`
- Gráfico de barras diárias com linhas de média móvel (3, 10 e 30 dias)
- Período padrão de 90 dias, customizável via parâmetro `?dias=N`
- O gráfico sempre exibe dados até o **dia anterior** (hoje está em andamento e
  não aparece na série)
- Visualização com Chart.js carregado via CDN (zero dependências Python novas)

### 4. Timezone

- `TIME_ZONE = "America/Sao_Paulo"` existente no projeto (mesmo offset UTC-3
  de America/Bahia). Nenhuma alteração necessária.

## Non-Goals

- **Não** alterar o código de extração (`extract_discharges.py` ou
  `process_discharges()`). A extração continua igual.
- **Não** popular dados retroativos — o sistema não foi implantado.
- **Não** criar granularidade por setor/ala (apenas total diário).
- **Não** introduzir Celery, Redis ou microserviços.
- **Não** modificar modelos `Patient` ou `Admission`.

## Capabilities

### New Capabilities

- `daily-discharge-tracking`: contagem diária de altas armazenada em tabela
  dedicada, populada por management command, exposta via gráfico interativo
  com médias móveis no portal

### Modified Capabilities

- `services-portal-navigation`: nova rota `/painel/altas/` acessível a partir
  do card de altas no dashboard (Requisito: navegação hierárquica a partir do
  dashboard com link clicável no card de altas)

## Impact

- **Dashboard**: card "Altas (24h)" substituído por "Altas no dia", agora
  clicável
- **Novo endpoint**: `/painel/altas/` com gráfico de barras + médias móveis
- **Modelo novo**: `DailyDischargeCount` no app `discharges`
- **Management command novo**: `refresh_daily_discharge_counts`
- **Management command modificado**: `extract_discharges` chama
  `refresh_daily_discharge_counts` ao final
- **Template novo**: `services_portal/discharge_chart.html`
- **Dependência frontend**: Chart.js via CDN (jsdelivr)
