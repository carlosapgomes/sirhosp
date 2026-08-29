# Design: Caracterizar as falhas crônicas de full-sync (coorte fail-only)

## Context

O pipeline reparado (RPAP, 2026-08-28) restaurou capturas de internações e
follow-ups. O health check agregado agora expõe `full_sync_failure_reasons`
(`timeout`, `invalid_payload`) como taxa crônica de ~10–12% ao dia. Evidência
de produção (somente agregados, 2026-08-28): 19 pacientes com 100% de falha
em 7 dias (588 tentativas esgotadas; `timeout`=372, `invalid_payload`=216),
enquanto 233/252 pacientes succeed e ~700 evoluções/dia fluem.

A base de diagnóstico já existe e é rica:

- `IngestionRun`: `intent`, `status`, `failure_reason`, `admissions_seen`,
  `events_created`, `queued_at`, `finished_at`, tentativas via
  `IngestionRunAttempt`, `parameters_json` (chave `patient_record` — uso
  efêmero interno, nunca em saída);
- `IngestionRunStageMetric`: `stage_name`, `status`, `started_at`,
  `details_json` (durações e falhas por estágio do fluxo de evolução);
- `FinalRunFailure`: runs esgotados (`failed_at`, `attempts_exhausted`);
- taxonomia sanitizada em `apps/ingestion/run_lifecycle.py` (família
  `invalid_payload` = falhas de dado; timeouts tipados em
  `apps/ingestion/extractors/persistent_evolution_pdf.py` com deadline
  compartilhado);
- modo laboratório existente em `automation/lab/playwright_experiments`
  (separado do código operacional por política do projeto).

O que falta: agregação da coorte fail-only, correlação com duração de
estágios/hora do dia, e reprodução controlada das hipóteses contra o código
real — para decidir a correção com causa comprovada, não por suposição.

## Goals / Non-Goals

### Goals

- Command read-only e sanitizado que responde, por janela: quem é a coorte
  fail-only (contagem e faixas de tentativas, sem identificadores), quais
  reasons dominam, quando (hora do dia) e em qual estágio/duração as
  falhas ocorrem.
- Harness de laboratório com fixtures sintéticas que reproduce as duas
  hipóteses contra o código real de extração de evolução, reportando
  duração medida e reason resultante (confirmação/refutação).
- Relatório de caracterização + ADR de decisão com a correção recomendada
  (ou hipóteses refutadas + próximo experimento).

### Non-Goals

- Corrigir qualquer coisa no worker, adapter, timeouts ou validação.
- Tocar em runs/pacientes de produção (nada de requeue/reopen/retry).
- Mudar o health check existente ou a taxonomia de reasons.
- Identificar pacientes em qualquer saída ou artefato.

## Decisions

### 1. Characterização é um command fino sobre um serviço de consulta agregada

Padrão RPAP-S5: serviço puro (`apps/ingestion/fullsync_failure_characterization.py`)
com value objects congelados (`CharacterizationConfig`, `FailOnlyCohort`,
`ReasonDistribution`, `StageTimingProfile`, `HourlyDistribution`,
`CharacterizationResult`) e um ponto de entrada
`characterize_fullsync_failures(config, *, now=None)`; command fino
`characterize_fullsync_failures` que valida args, renderiza allowlist e
decide exit (0 sempre que a caracterização completa — não há noção de
"unhealthy" aqui; o command é diagnóstico, não gate).

Agrupamento por paciente usa `parameters_json__patient_record` apenas em
memória efêmera (sets/dicts locais); nenhuma chave atravessa a fronteira do
serviço — mesmo contrato de privacidade do health check.

### 2. Métricas de caracterização (o que o command responde)

- **Cohorte fail-only**: pacientes com ≥ N tentativas terminais na janela e
  0 sucessos (`--min-attempts`, default 3, exclui ruído de paciente que
  recebeu alta/entrou há pouco). Saída: contagem de pacientes, total de
  runs, mediana/máximo de tentativas por paciente, idade da primeira e da
  última falha da coorte (agregadas).
- **Reasons**: distribuição de `failure_reason` dos runs da coorte (e, para
  contraste, dos runs fail-then-ok).
- **Timing por estágio**: para os runs falhos da coorte, distribuição de
  duração por `stage_name` (mediana/p90 em segundos, de
  `IngestionRunStageMetric`) e estágio onde a falha terminal ocorre —
  distingue "timeout no download do PDF" de "timeout na navegação" etc.
- **Hora do dia**: histograma agregado por hora (UTC) dos
  `queued_at`/`finished_at` falhos — correlaciona com janelas de
  lentidão do legado.
- **Contraste**: mesmas métricas para runs bem-sucedidos do mesmo período
  (baseline de duração por estágio), sem identificar paciente.

### 3. Reprodução em laboratório: fixtures sintéticas contra código real

Harness em `automation/lab/playwright_experiments/fullsync_failure_lab.py`
(claramente laboratorial, nunca importado por código operacional). Duas
famílias de fixtures, derivadas das formas agregadas observadas (nunca de
dados reais):

- **H1 (timeout por volume/deadline)**: página sintética de evoluções com
  lista longa (parâmetro: nº de itens) + deadline curto configurável,
  exercitando o fluxo real de leitura/paginação do
  `persistent_evolution_pdf` — mede duração até o deadline e confirma o
  reason `timeout`.
- **H2 (invalid_payload por conteúdo)**: fixtures de conteúdo sintético que
  violam cada validação conhecida da família (ex.: atributos vazios,
  estrutura inesperada), exercitando o classificador real — confirma o
  mapeamento para `invalid_payload` e identifica qual validação dispara.

Cada experimento registra: hipótese, fixture, parâmetros, duração medida,
reason resultante, veredito (confirmada/refutada/inconclusiva) em JSON
sintético; o relatório consolidado interpreta esses artefatos. O harness
não acessa produção nem rede externa além do Playwright local
(headless, dados 100% sintéticos).

### 4. Decisão por ADR, correção em change futuro

A ADR (via skill `adr-generator`) registra: evidência de caracterização
(agregados), veredito(s) de laboratório, causa(s) comprovada(s) e a
correção recomendada (ex.: deadline progressivo por volume; relaxar/
corrigir validação específica; retry com backoff diferenciado) — aberta
como novo change. Se todas as hipóteses forem refutadas, a ADR registra o
que foi excluído e o próximo experimento; não há correção às cegas.

### 5. Sem mutação, sem identidade, mesma disciplina de saída

- Serviço/command: somente SELECT; provado por testes de contagem de models
  e spies (padrão RPAP-S5).
- Saída/scanner: sentinelas de patient_record/nome/conteúdo/URL/erro bruto
  nunca aparecem em stdout/stderr; relatórios e ADR carregam somente
  agregados.
- Laboratório: fixtures sintéticas versionadas no repo (sem HTML/PDF
  reais).

**Alternativas rejeitadas:**

- estender o health check existente com subcomandos: mistura gate
  operacional com investigação pontual e infla o contrato do S5;
- investigar paciente a paciente em produção: viola a política de
  privacidade e não isola variáveis;
- corrigir o timeout "por precaution" (ex.: só aumentar deadline):
  exatamente o anti-pattern que o RPAP proíbe (correção por suposição).

## Risks / Trade-offs

- Agregado pode mascarar multimodalidade (duas causas no mesmo reason):
  mitigado pelas dimensões de corte (estágio, hora, duração) e pelo
  laboratório controlado.
- Fixtures sintéticas podem não reproduzir o caso real: a ADR exige
  explicitar o que foi reproduzido e o que permanece hipótese; inconclusivo
  é um veredito válido com próximo experimento definido.
- Custo do Playwright em CI: experimentos do harness rodam como testes
  marcados/skippables sem browser real onde possível (validação de
  classificação é pura); o laboratório com browser roda sob demanda.

## Migration Plan

Sem migrations, sem mudança de schema, sem dependência nova. Deploy é
code-only; o command e o harness são aditivos e não afetam o fluxo
operacional. A execução em produção é um one-shot read-only documentado no
runbook.

## Open Questions

- A mediana de tentativas da coorte (≈31/paciente na janela de 7d)
  justifica `--min-attempts` default 3? (sim — exclui altas recentes; o
  parâmetro fica explícito na saída).
- `details_json` dos stage metrics tem granularidade suficiente de duração?
  (a ser confirmado no S1 com dados sintéticos; se não, a caracterização
  usa started/finished dos stages.)
