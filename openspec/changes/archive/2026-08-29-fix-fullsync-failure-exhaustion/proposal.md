# Change: Corrigir o esgotamento de tentativas da coorte fail-only de full-sync

## Why

A ADR-0008 (`docs/adr/ADR-0008-fullsync-failure-characterization-decision.md`,
Accepted) registrou causa comprovada para a coorte crônica de falhas de
full-sync, com evidência de laboratório (fixtures 100% sintéticas contra o
código real de extração e classificação) e de produção:

- **Produção 2026-08-28 (agregados read-only):** 19 pacientes fail-only
  (7,5% de 252), 588 tentativas esgotadas em 7d (`timeout`=372,
  `invalid_payload`=216), contraste 233/252 com sucesso.
- **Produção 2026-08-29, one-shot `characterize_fullsync_failures` na
  v0.1.0-rc.14 (janela 7d):** coorte de **23 pacientes**, 453 runs falhos,
  mediana de 15 tentativas/paciente, máximo **112**; `timeout`=382 (84%),
  `invalid_payload`=71 (16%); **estágio terminal falho =
  `evolution_extraction` em 100% dos runs**; `evolution_extraction`
  p90=124s contra `admissions_capture` p90=14,1s; histograma horário
  achatado (sem correlação com pico de carga); contraste fail-then-ok com
  as mesmas classes de falha (1.477 falhas recuperadas).

Vereditos de laboratório (reproduzíveis via
`automation/lab/playwright_experiments/fullsync_failure_lab.py`):

- **H1 (confirmed)** — o orçamento fixo de tempo (`timeout=120`s,
  compartilhado por todas as fases do fluxo de evoluções via deadline
  monotônico D14) é estourado por listas longas legítimas; p90 de 124s em
  produção confirma que a maioria das falhas fica logo acima do teto fixo.
- **H2 (confirmed)** — conteúdos que violam validações conhecidas mapeiam
  para `invalid_payload` de forma determinística.

O sintoma operacional mais caro é o **esgotamento de tentativas**: a
política de retry atual reenfileira qualquer falha enquanto
`attempt_count < max_attempts` (+60s fixo), sem distinguir falha
determinística de transitória — queimando centenas de execuções por semana
(cada uma com sessão Playwright + download + parse contra o legado) sem
nunca convergir para os pacientes da coorte.

## What Changes

- **H2 — retry por classe de falha (fail-fast):** função pura em
  `run_lifecycle.py` decide reprocessabilidade pelo `failure_reason`
  (`invalid_payload` = determinístico → não reenfileira); os dois workers
  (`process_ingestion_runs` e `process_ingestion_runs_persistent_session`)
  consultam a mesma função em `_mark_run_failed`; `timeout` e demais
  reasons mantêm o retry com backoff existente.
- **H1 — deadline por volume:** função pura de orçamento por janela
  (`base + fator × dias da janela`, com teto configurável) no módulo do
  fluxo de evoluções; o worker persistente passa o orçamento escalado por
  janela de gap em vez do `timeout=120` fixo; listas acima do teto
  continuam falhando `timeout` (comportamento bounded preservado).
- **H2b — caracterização das validações:** suíte de regressão/caracterização
  das validações de payload contra o código real (incluindo o resgate por
  viewer frame quando o atributo `data` do objeto PDF está vazio),
  distinguindo conteúdo genuinamente inválido de lacuna de parsing; correção
  estritamente limitada a gap comprovado por teste.
- **Operação:** nota no `deploy/README.md` sobre o novo comportamento e como
  observá-lo (health check e caracterização, sem contrato novo).

## Capabilities

### New Capabilities

- `fullsync-failure-exhaustion-fix`: correção do esgotamento de tentativas
  da coorte fail-only — fail-fast de payload determinístico, orçamento de
  tempo por volume com teto e caracterização das validações de payload.

### Modified Capabilities

Nenhuma. Os contratos de `ingestion-pipeline-health` e
`fullsync-failure-characterization` permanecem inalterados (mesma taxonomia
de reasons, mesmas saídas agregadas).

## Scope

### Incluído

- `apps/ingestion/run_lifecycle.py` (política de retry por reason);
- `apps/ingestion/management/commands/process_ingestion_runs.py` e
  `.../process_ingestion_runs_persistent_session.py` (`_mark_run_failed`);
- `apps/ingestion/extractors/persistent_evolution_pdf.py` (função de
  orçamento por janela; caracterização de validações);
- worker persistente: chamada de `extract_evolutions` com orçamento
  escalado;
- testes unitários novos (política, orçamento, caracterização, regressão
  dos workers);
- `deploy/README.md` (nota operacional).

### Excluído (non-goals)

- Sem mudança de taxonomia de `failure_reason` nem dos contratos do health
  check/characterização;
- sem paginação do relatório legado (invasiva; ver design — decisão D3);
- sem alterar o worker clássico no orçamento por volume (fora da topologia
  de produção; a função pura fica reutilizável);
- sem provider de alerta novo (o fail-fast emite log sanitizado e é
  observável pelos agregados existentes);
- sem reprocessar/reabrir runs históricos da coorte;
- sem migration, model ou dependência nova.

## Success Criteria

- Run com falha `invalid_payload` (validação determinística) termina
  fail-fast na primeira tentativa, registra `FinalRunFailure` coerente e
  fecha o batch; run com `timeout` continua reenfileirando com backoff
  (testes + inspeção).
- Janela longa legítima recebe orçamento escalado (função pura
  determinística, teto aplicado) e o worker persistente usa o orçamento por
  janela (teste + inspeção `rg` do call site).
- Cada validação de payload do laboratório CFC (H2) coberta por teste de
  caracterização contra código real; resgate por viewer frame preservado;
  decisão inválido-genuíno vs ausência documentada por testes.
- Gates oficiais exit 0; unit final >= baseline; zero regressões nos
  contratos existentes (health check, characterization, workers).
- Laboratório CFC re-executado sem alteração de vereditos (H1/H2 ainda
  reproduzem com deadlines curtos experimentais; controles passam).
