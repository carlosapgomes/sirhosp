# hospital-flow-pressure-dashboard

## Why

Os painéis atuais (Censo, Leitos) mostram o hospital como **ponto no
tempo**: a fotografia de um instante. Mas o gestor local precisa enxergar a
**pressão** que a rede exerce sobre o hospital e a **efetividade** com que o
hospital libera leitos — algo que só aparece na evolução temporal do
estoque (pacientes internados) confrontado com o fluxo (admissões vs.
altas+óbitos).

O censo oficial diário exclui salas de observação de emergência (pediátrica,
adulta, ginecológica) — justamente onde a pressão se manifesta primeiro.
Por isso a base de estoque deste painel é o `CensusSnapshot` (extração
global, sem filtro), não o censo oficial. Já o fluxo vem das extrações
dedicadas (`admissions`, `discharges`, `deaths`), que são mais completas e
estáveis que o mirror `Admission`.

Validação empírica (06/2026): a identidade conservativa
`ΔADC ≈ admissões − altas − óbitos` fecha com resíduo de ~1% usando as
fontes dedicadas (vs. ~5% com o mirror), o que valida a viabilidade do
conceito.

## What Changes

- Criar **serviço de domínio puro** que agrega, por dia, o estoque (ADC =
  média dos `CensusSnapshot` ocupados), o inflow (`admissions`) e o outflow
  (`discharges` + `deaths`), com cálculo de fluxo líquido e **resíduo de
  qualidade (QC)**.
- Expor **página "Fluxo Hospitalar"** no portal com gráfico de **barras
  divergentes** (admissões ↑ / altas+óbitos ↓) e **linha de ADC** sobreposta,
  evidenciando simultaneamente pressão da rede, efetividade de alta e
  resultado no estoque.
- Adicionar **drill-down por setor** (filtro), permitindo localizar onde a
  pressão se concentra.
- Expor **painel de resíduo QC visível ao admin**, como monitor de
  integridade dos pipelines de extração.
- Adicionar **entrada "Fluxo Hospitalar" no sidebar**, após "Leitos".
- **Não** introduzir faixa cinza de "dado preliminar" (YAGNI): o modelo
  operacional extrai cada dia uma única vez na madrugada de D+1; o resíduo
  QC já sinaliza se o fonte desenvolver lag no futuro.

## Scope / Non-Goals / Risks

### Scope

- Visualização temporal de estoque vs. fluxo hospitalar no portal.
- Serviço de agregação reutilizável (parametrizável por período e setor).
- Leitura exclusiva de tabelas existentes (sem novas migrations).

### Non-Goals

- Não criar painel paralelo baseado no censo oficial (change futuro).
- Não introduzir faixa de "dado preliminar" / backfill warning.
- Não alterar schema, pipelines de extração nem agregar dados em novas
  tabelas materializadas.
- Não agregar persistência de séries calculadas (cálculo é on-demand).

### Main Risks

- Confusão semântica entre "ADC do snapshot" e contagem do censo oficial.
- Drill-down por setor pode gerar consulta pesada para 82 setores em janela
  longa (mitigado por índices existentes em `captured_at` e `setor`).
- Resíduo QC pode confundir usuário não-técnico (mitigado: visível só ao
  admin, com legenda curta).

## Capabilities

### New Capabilities

- `hospital-flow-visualization`: visão temporal de pressão hospitalar no
  portal, confrontando estoque (ADC do snapshot) com fluxo (admissões vs.
  altas+óbitos), com drill-down por setor e monitor de resíduo para admin.

## Impact

- `apps/census/flow_service.py` (novo): agregação de estoque/fluxo/resíduo.
- `apps/census/views.py` (edição): view do painel.
- `apps/census/urls.py` (edição): rota `hospital_flow`.
- `templates/census/hospital_flow.html` (novo): template + Chart.js.
- `templates/includes/sidebar.html` (edição): entrada de menu.
- `tests/unit/test_hospital_flow_service.py` (novo): TDD do serviço.
- `tests/unit/test_hospital_flow_view.py` (novo): TDD da view/menu.
