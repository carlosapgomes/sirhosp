# FX-S2 — Orçamento de tempo por volume nas janelas de evolução

## Handoff para implementador LLM com contexto zero

Leia integralmente:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. `docs/adr/ADR-0008-fullsync-failure-characterization-decision.md`
   (H1 confirmado: orçamento fixo estoura em listas longas legítimas);
3. o change atual: `proposal.md`, `design.md` (seção **D2**), spec delta,
   `tasks.md`;
4. `apps/ingestion/extractors/persistent_evolution_pdf.py`:
   `EvolutionPdfFlow.extract` (deadline monotônico D14, `_deadline_s`,
   `_remaining_ms`, `_bound_ms`), `EvolutionPdfError`,
   `EvolutionPdfTimeoutError`, `_format_br_date`;
5. no worker persistente
   (`apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`),
   o laço `for window in plan["windows"]:` que chama
   `adapter.extract_evolutions(..., timeout=120)` (Step 3, extração de
   evoluções por janela de gap);
6. `tests/unit/test_fullsync_failure_lab.py` e os testes existentes do
   fluxo PDF (padrão de fakes duck-typed — nenhum browser).

Estado atual: cada janela de gap recebe orçamento fixo de 120s
compartilhado por todas as fases; produção mostra `evolution_extraction`
p90=124s — a maioria das falhas fica pouco acima do teto. Este slice
escala o orçamento pelo span da janela, com teto, **sem** mudar a
semântica bounded do fluxo (D14 intacto) e **sem** tocar o worker
clássico.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Idêntico ao FX-S1 (plano/matriz, BASE_REF, baseline unit oficial, RED
real, GREEN mínimo, inspeções `rg`, gates completos com unit final
`passed >= baseline`, relatório com evidência). **Qualquer item falho =
INCOMPLETO**: sem marcar `tasks.md`, sem commit/push.

## Objetivo do slice (fluxo end-to-end)

O worker persistente, ao extrair evoluções para cada janela de gap, passa
um orçamento de tempo proporcional ao span da janela (função pura
determinística com teto), em vez do `timeout=120` fixo. Janelas curtas
mantêm o comportamento atual; janelas longas legítimas ganham tempo
proporcional; volume acima do teto continua falhando `timeout`.

## Contexto técnico atual

- A função de orçamento deve viver no módulo do fluxo
  (`persistent_evolution_pdf.py`) ao lado das primitivas de deadline — é
  pura (sem Django), determinística e reutilizável.
- `plan["windows"]` carrega dicts com `start_date`/`end_date` em
  `YYYY-MM-DD` (mesmo formato que `_format_br_date` valida).
- O worker persistente é o caminho de produção (10 réplicas); o worker
  clássico fica **intocado** neste slice (backlog documentado no design).

## Escopo funcional

- **R1 — Função pura de orçamento:** `evolution_window_budget_seconds(
  start_date: str, end_date: str, *, base_seconds: int = 120,
  seconds_per_day: int = 2, cap_seconds: int = 600) -> int` em
  `persistent_evolution_pdf.py`:
  - mesmo dia (span 0) → `base_seconds`;
  - span N dias → `min(cap, base + seconds_per_day × N)`;
  - datas inválidas/invertidas → `EvolutionPdfError` com mensagem
    sanitizada constante (sem ecoar valores);
  - determinística para mesmas entradas; argumentos positivos (validar).
- **R2 — Call site do worker persistente:** o laço de evoluções usa
  `timeout=evolution_window_budget_seconds(window["start_date"],
  window["end_date"])`; nenhum literal `120` permanece nesse laço.
- **R3 — Bounded preservado:** nenhum comportamento do
  `EvolutionPdfFlow` muda internamente (deadline único D14, tipos de erro,
  classificações); teste de regressão: deadline curto experimental
  continua produzindo `EvolutionPdfTimeoutError` → `timeout`.

## Arquivos esperados (limite 3, além de `tasks.md`)

1. `apps/ingestion/extractors/persistent_evolution_pdf.py` (função pura);
2. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`
   (call site);
3. `tests/unit/test_evolution_window_budget.py` (novo — função pura +
   call site com fake adapter).

Proibido: `EvolutionPdfFlow` internals, worker clássico, adapter,
models/migrations, health check/characterization.

## TDD obrigatório

### RED mínimo

1. mesma data → 120; 1 dia → 122; 31 dias → 182; span grande (ex. 400
   dias) → teto 600 (capped);
2. defaults nomeados sobrescrevíveis (base/per_day/cap customizados);
3. datas inválidas (`"xx"`, invertidas) → `EvolutionPdfError` sanitizado
   (mensagem constante; sem eco dos inputs — teste com sentinelas);
4. determinismo: duas chamadas iguais → mesmo valor;
5. call site: com fake adapter capturando kwargs, janela de span 60 dias
   recebe `timeout = base + 2×60` (não 120); janela de 1 dia recebe 120;
6. regressão bounded: fluxo real com fake page/request lenta e orçamento
   curto continua levantando `EvolutionPdfTimeoutError` (técnica dos
   fakes do CFC — sem browser);
7. argumentos inválidos da função (base/cap não positivos) → erro
   sanitizado antes de qualquer cálculo.

### GREEN / REFACTOR

Função pura sem I/O; parsing de datas via `datetime.date.fromisoformat`
com wrap sanitizado; call site de uma linha; sem config/setting novo
(YAGNI — defaults nomeados bastam).

## Checks de inspeção obrigatórios

```bash
rg -n "def evolution_window_budget_seconds" apps/ingestion/extractors/persistent_evolution_pdf.py
rg -n "evolution_window_budget_seconds|timeout=120" apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "timeout=120|timeout = 120" apps/ingestion/management/commands/process_ingestion_runs.py
rg -n "class EvolutionPdfFlow" -A 3 apps/ingestion/extractors/persistent_evolution_pdf.py | head -5
```

Interprete: o laço de evoluções do worker persistente usa a função (nenhum
`timeout=120` no Step 3); o worker clássico permanece intocado (presença
de 120 lá é esperada e justificada); `EvolutionPdfFlow` sem mudança de
comportamento interno.

## Gates de autoavaliação

1. Qual teste prova que janela longa recebe orçamento escalado no call
   site (e não só na função pura)?
2. Qual teste prova o teto e a sanitização de datas inválidas?
3. O que prova que o comportamento bounded do fluxo foi preservado?
4. Por que a função vive no módulo do extrator e não no worker?
5. Por que cada arquivo é necessário?

## Critérios de sucesso binários

- [ ] R1–R3 cobertos RED/GREEN.
- [ ] Função pura determinística com teto e erros sanitizados.
- [ ] Call site persistente sem literal 120 no laço de evoluções.
- [ ] Bounded/timeout tipado preservado (regressão).
- [ ] Máximo 3 arquivos; worker clássico e fluxo intocados.
- [ ] Gates exit 0; unit final >= baseline.

### Condições automáticas de INCOMPLETO

- baseline/RED ausente ou falho;
- função impura/indeterminística ou com I/O;
- erro sanitizado ecoa valores de entrada;
- call site persistente ainda com literal 120 no laço de evoluções;
- qualquer mudança de comportamento interno do `EvolutionPdfFlow`;
- worker clássico/adapter/models/migrations tocados;
- arquivo extra; gate falho; relatório ausente; task prematura.

## Relatório obrigatório

`/tmp/sirhosp-slice-FX-S2-report.md` (padrão FX-S1): Status, BASE_REF,
matriz, RED/GREEN, snippets, inspeções interpretadas, baseline vs final,
gates, justificativas, riscos, `Handoff para verificador` R1–R3.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, docs/adr/ADR-0008-fullsync-failure-characterization-decision.md and the full fix-fullsync-failure-exhaustion change (proposal.md, design.md section D2, specs delta, tasks.md, slice-prompts/SLICE-FX-S2.md). Implement ONLY FX-S2. Follow the DeepSeek4-Flash protocol in the slice: plan matrix, clean BASE_REF, official unit baseline, real RED for the pure evolution_window_budget_seconds function (base/per-day/cap, invalid-date sanitized errors, determinism, capped) and for the persistent worker call site (fake adapter captures the scaled timeout; no literal 120 left in the evolution loop; short window keeps base), regression proving the typed timeout still fires under a short experimental budget, minimal GREEN, local REFACTOR, mandatory rg inspections, all official gates with final unit exit 0 and passed >= baseline. Do not change EvolutionPdfFlow internals, the classic worker, adapter, models or migrations. Touch only the 3 listed files. Create /tmp/sirhosp-slice-FX-S2-report.md with full evidence and verifier handoff. Any missing/failing item is INCOMPLETE with no task update/commit. If complete, mark only 2.x, commit, push, reply REPORT_PATH=..., then STOP.
```
