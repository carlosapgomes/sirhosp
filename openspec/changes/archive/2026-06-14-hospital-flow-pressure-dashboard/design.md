# Design: hospital-flow-pressure-dashboard

## Context

Os painéis atuais (`Censo`, `Leitos`) são ponto-no-tempo. Falta uma visão
**temporal de fluxo** que confronte o estoque de pacientes internados com o
movimento de admissão/alta/óbito, permitindo ao gestor distinguir "pressão
da rede" (inflow alto) de "gargalo de alta" (outflow baixo).

Validação empírica realizada (período 10–14/06/2026):

- **ADC (estoque)** via `CensusSnapshot` é estável (~670 leitos, ~79%
  ocupação) independente da frequência de snapshot (1 a 5 por dia).
- **Escopo** do snapshot casou com 98% dos `Patient` e 93% das admissões
  ativas — mesma população, não diferença estrutural.
- **Fluxo** via fontes dedicadas (`admissions`, `discharges`, `deaths`) é
  2–6× mais completo que o mirror `patients_admission.discharge_date`.
- **Identidade conservativa** `ΔADC ≈ admissões − altas − óbitos` fechou com
  resíduo de **~1%** (média 11–13/06), estável no tempo — assinatura de
  contabilidade que fecha de verdade.

Decisão de escopo de estoque: o snapshot cobre **todos** os setores
(incluindo observação de emergência), ao contrário do censo oficial. Esta
diferença é **característica desejada**, não defeito.

Restrições da fase 1: monólito Django + PostgreSQL; sem Celery/Redis; sem
stack externa de BI.

## Goals / Non-Goals

**Goals:**

- Serviço de domínio testável que agrega estoque/fluxo/resíduo por dia.
- Página no portal com gráfico de pressão (barras divergentes + linha ADC).
- Drill-down por setor via filtro.
- Monitor de resíduo QC visível apenas ao admin.
- Zero mudança de schema (leitura de tabelas existentes).

**Non-Goals:**

- Painel paralelo baseado em censo oficial (change futuro).
- Faixa de "dado preliminar" (YAGNI — extração é única por dia).
- Persistência de séries calculadas (on-demand).
- Agregação por especialidade (futuro, se demandado).

## Decisions

### D1) Estoque = ADC (média dos snapshots ocupados do dia)

**Decisão**: `ADC(dia) = Σ ocupados em cada snapshot / nº de snapshots do
dia`. Considera todos os setores, sem exclusão de emergência/observação.

**Justificativa**: validação mostrou ADC estável independente da
frequência; média suaviza variação intra-diurna. Inclui setores que o
censo oficial omite (alinhado à necessidade do gestor local).

**Alternativa**: usar contagem do snapshot mais recente do dia.
**Por que não**: dependente do horário da extração; média é mais robusta.

### D2) Fluxo = fontes dedicadas (não o mirror `Admission`)

**Decisão**:

- Inflow = `admissions_dailyadmissioncount.count` por `date`.
- Outflow = `discharges_dailydischargecount.count` +
  `deaths_dailydeathcount.count` por `date`.

**Justificativa**: validação mostrou que `patients_admission.discharge_date`
sub-captura 2–6× comparado à fonte dedicada. Óbitos somam às altas porque
ambos liberam leito.

**Alternativa**: usar `Admission.admission_date` / `discharge_date`.
**Por que não**: incompleto; aumenta resíduo da identidade para ~5%.

### D3) Identidade conservativa e resíduo QC

**Decisão**: calcular, por dia:

```text
líquido(dia)   = admissões − altas − óbitos
delta_adc(dia) = ADC(dia) − ADC(dia−1)
resíduo(dia)   = delta_adc − líquido
```

Resíduo ≈ 0 indica que as fontes estão consistentes; resíduo crescente
sinaliza problema de extração. Validado empiricamente em ~1% (11–13/06).

**Aplicação**: exibido apenas ao admin (não ao gestor clínico), como
monitor de integridade dos pipelines.

### D4) Sem faixa de "dado preliminar" (YAGNI)

**Decisão**: não implementar faixa cinza nem warning de backfill.

**Justificativa**: o modelo operacional extrai cada dia uma única vez (na
madrugada de D+1); não há re-extração deslizante, portanto não há número
revisável para sinalizar. O resíduo QC (D3) já fornece o sinal se o fonte
desenvolver lag no futuro. Se houver migração futura para re-extração
deslizante, a faixa cinza entra como feature separada, com evidência
própria.

### D5) Janela temporal: 90 dias default, seletor 30/90/180, gap honesto

**Decisão**: default 90 dias; seletor 30/90/180. ADC ausente em dias sem
snapshot é exibido como **gap** (ponto nulo na linha), não projetado.

**Justificativa**: histórico de fluxo tem 74–82 dias; snapshot tem poucos
dias por enquanto. Projetar ADC retroativo introduziria estimativa,
contradizendo o princípio de fotografia.

### D6) Visualização: barras divergentes + linha ADC sobreposta

**Decisão**: para cada dia, barra de admissões para cima e barra de
altas+óbitos para baixo (divergentes), com linha de ADC sobreposta em eixo
secundário. Chart.js 4.4.0 via CDN (já usado no projeto).

**Justificativa**: mostra simultaneamente pressão da rede (inflow),
efetividade de liberação (outflow) e resultado (estoque) — materializa o
conceito motivador do painel.

### D7) Drill-down por setor (filtro, não 82 séries)

**Decisão**: visão default = hospital-total. Seletor de setor recalcula o
mesmo painel para um setor. Não exibir 82 séries simultâneas.

**Justificativa**: small-multiples ou heatmap de 82 setores é caro e de
leitura difícil; filtro entrega localização sem custo visual.

### D8) Serviço de domínio isolado e puro

**Decisão**: toda a lógica de agregação fica em `apps/census/flow_service.py`
como função(s) pura(s) parametrizadas por `(start, end, sector=None)`,
sem acoplamento a HTTP/templates. A view é fina (chama o serviço,
serializa para o template).

**Justificativa**: testabilidade máxima (TDD no serviço sem Django
Request), reuso futuro (censo oficial, BI), aderência ao AGENTS.md §8
(lógica de negócio fora de views/templates).

## Risks / Trade-offs

- **[Consulta pesada em janela longa com drill-down]** → mitigar com índices
  existentes (`captured_at`, `setor`) e limite de janela em 180 dias.
- **[Resíduo QC confunde usuário não-técnico]** → mitigar exibindo só ao
  admin, com legenda curta "indicador de qualidade dos dados".
- **[Confusão ADC vs. censo oficial]** → mitigar com legenda no template
  esclarecendo que o estoque vem do snapshot (todos os setores).
- **[Snapshots esparsos em dias antigos]** → mitigar exibindo gap honesto
  (null), sem projeção.

## Migration Plan

1. S1: serviço de domínio + testes (sem web).
2. S2: view/URL/template-tabela + entrada no sidebar.
3. S3: Chart.js (barras divergentes + linha ADC).
4. S4: drill-down por setor.
5. S5: painel de resíduo QC para admin.

Sem migrations de banco. Sem backfill. Rollback = remover rota/template/entry
de menu; serviço pode permanecer (inócuo se não referenciado).

## Open Questions

1. O drill-down por setor (S4) deve oferecer atalhos para os N setores de
   maior ocupação, ou apenas um dropdown alfabético completo?
   Resposta: dropdown alfabético no S4; atalhos como melhoria futura.
2. O painel de resíduo QC (S5) deve ter limiar visual (ex.: cor vermelha
   se resíduo > 5%)?
   Resposta: sim, cor amarela > 3% e vermelha > 5%.
