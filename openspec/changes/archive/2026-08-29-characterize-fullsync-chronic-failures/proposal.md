# Change: Caracterizar as falhas crônicas de full-sync (coorte fail-only)

## Why

O health check do pipeline (RPAP-S5, em produção desde 2026-08-28) tornou
visível uma falha parcial crônica de `full_sync` distinta do incidente de
internações: ~10–12% dos runs terminais falham por dia (`timeout` e
`invalid_payload`), taxa estável há pelo menos 7 dias. Agregados de produção
(2026-08-28, somente leitura) mostram que o problema não é total nem
puramente pontual:

- ~700 documentos de evolução novos/dia fluem normalmente; 92,5% dos
  pacientes (233/252) tiveram full-sync bem-sucedido na semana;
- porém **19 pacientes (7,5%) falharam todas as 588 tentativas** da semana
  (`timeout`=372, `invalid_payload`=216), todas esgotadas em
  `FinalRunFailure` — as evoluções desses pacientes de fato não são
  baixadas;
- a taxa não mudou após o deploy do reparo das internações (RPAP), como
  esperado: o RPAP tornou as falhas observáveis, não as corrige.

A política do change RPAP é explícita: corrigir `timeout`/`invalid_payload`
por suposição é proibido; uma causa nova comprovada exige change próprio.
Este change é esse próximo passo: caracterizar a coorte fail-only com
evidência (agregados de produção read-only + reprodução sintética em
laboratório) e produzir a recomendação de correção com causa comprovada,
sem tocar nos runs desses pacientes em produção.

## What Changes

- Adicionar command read-only `characterize_fullsync_failures` que agrega,
  por janela configurável: detecção da coorte fail-only (pacientes com
  falha em 100% das tentativas), distribuição de reasons, contagem de
  tentativas por paciente, idade da primeira/última falha, padrões de
  duração por estágio (`IngestionRunStageMetric`), distribuição por hora do
  dia e reuso de mensagens sanitizadas existentes — saída estritamente
  agregada e sanitizada (nenhum identificador, parâmetro, texto clínico,
  URL ou erro bruto), no padrão do `check_ingestion_pipeline_health`.
- Adicionar harness de laboratório (em `automation/lab/playwright_experiments`,
  código claramente separado do operacional) que reproduz as hipóteses
  contra o código real do adapter/fluxo de evolução com fixtures sintéticas:
  listas de evolução grandes/estourando deadline (hipótese timeout) e
  padrões de conteúdo que violam validação (hipótese invalid_payload),
  confirmando ou refutando cada hipótese com métricas de duração e reason
  resultante.
- Produzir relatório de caracterização (formato padronizado, agregados) e
  ADR de decisão registrando causa(s) comprovada(s) e a correção
  recomendada para um change futuro — nenhuma correção é implementada aqui.
- Documentar o procedimento operacional: como rodar a caracterização em
  produção (read-only), como rodar a reprodução em laboratório e como o
  relatório alimenta a decisão.

## Capabilities

### New Capabilities

- `fullsync-failure-characterization`: diagnóstico agregado e sanitizado da
  coorte crônica de falhas de full-sync (detecção fail-only, distribuição
  de reasons/tentativas/durações por estágio/hora) e reprodução sintética
  em laboratório das hipóteses de causa, com relatório de evidência para
  decidir a correção.

### Modified Capabilities

Nenhuma. O worker, o adapter, a taxonomia de reasons e o health check não
mudam; a caracterização é camada adicional de diagnóstico.

## Scope

### Included

- Novo command read-only `characterize_fullsync_failures` com testes
  sintéticos (padrão TDD do projeto).
- Harness de laboratório com fixtures sintéticas para as duas hipóteses
  (timeout por volume/deadline; invalid_payload por conteúdo), executando
  o código real de extração de evolução em modo laboratório.
- Formato de relatório de caracterização (template + gerador a partir da
  saída do command) e ADR de decisão (template preenchido com as evidências
  coletadas na execução operacional).
- Runbook operacional em `deploy/README.md` (seção própria): como executar
  em produção (read-only) e em laboratório.

### Excluded

- Qualquer correção do worker/adapter/timeouts/validação (fica para change
  futuro com causa comprovada pela ADR).
- Mutação de qualquer run/paciente/batch em produção: nada de requeue,
  reopen, retry manual ou `--apply` de qualquer natureza.
- Impressão ou exportação de identificadores de pacientes, prontuários,
  conteúdo clínico, HTML, PDF ou erros brutos — inclusive em laboratório, o
  harness usa somente dados sintéticos.
- Provider de alerta, mudanças no health check existente ou na taxonomia
  de reasons.
- Reprocessar os 19 pacientes ou qualquer run histórico.

## Success Criteria

1. O command caracteriza a coorte fail-only em janela configurável com
   saída 100% agregada/sanitizada (testes scanner de sentinelas, no padrão
   RPAP-S5) e provadamente read-only (contagens de models antes/depois +
   spies de rede/subprocesso/playwright).
2. O harness de laboratório reproduz, com fixtures sintéticas, ao menos
   uma falha `timeout` e uma `invalid_payload` contra o código real,
   reportando durações e reason resultante — mecanismo de
   confirmação/refutação demonstrado em testes.
3. Executar a caracterização em produção não altera nenhuma linha (zero
   INSERT/UPDATE/DELETE) e não identifica pacientes na saída.
4. Relatório de caracterização + ADR de decisão documentam causa(s)
   comprovada(s) ou hipóteses refutadas, com a correção recomendada e a
   evidência que a suporta — prontos para abrir o change de correção.
5. Todos os gates oficiais em container passam (check, unit, integration,
   lint, typecheck, quality-gate), OpenSpec strict e markdown lint sem
   erros.

## Risks

- Agregados de produção não discriminarem a causa (ex.: `timeout` sem
  granularidade de estágio): mitigação via `IngestionRunStageMetric`
  (durações e status por estágio já indexados) e pela reprodução em
  laboratório, que isola variáveis.
- Hipóteses refutadas sem nova hipótese formada: o deliverable mínimo é a
  ADR registrando o que foi excluído e o próximo experimento — não uma
  correção às cegas.
- Vazamento de identidade na saída: mitigado pelo contrato de sanitização
  (scanner de sentinelas) herdado do padrão RPAP-S5 e pela revisão de diff
  sem PHI.
- Harness de laboratório escalar para infraestrutura de teste pesada:
  mitigado por fixtures sintéticas mínimas e reuso do modo laboratório
  existente (`automation/lab`), sem novos provedores ou dependências.
