# Design: fix-fullsync-failure-exhaustion

## Contexto e evidência

Toda a causalidade está comprovada na ADR-0008 e nos artefatos do change
`characterize-fullsync-chronic-failures` (arquivado em
`openspec/changes/archive/2026-08-29-characterize-fullsync-chronic-failures/`).
Este change **não investiga** — implementa a correção recomendada. Os pontos
de código relevantes, mapeados na investigação:

| Mecanismo | Arquivo | Ponto atual |
| --- | --- | --- |
| Orçamento fixo compartilhado (D14) | `apps/ingestion/extractors/persistent_evolution_pdf.py` | `EvolutionPdfFlow.extract(timeout=120)` cria deadline monotônico único para todas as fases |
| Chamada com timeout fixo (produção) | `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py` | laço `for window in plan["windows"]` chama `adapter.extract_evolutions(..., timeout=120)` |
| Chamada com default (worker clássico) | `apps/ingestion/management/commands/process_ingestion_runs.py` | laço equivalente sem `timeout` (default 120 do adapter) |
| Retry cego por tentativas | ambos os workers, `_mark_run_failed` | `if run.attempt_count < run.max_attempts:` → requeue `+60s`; senão terminal + `record_final_run_failure` |
| Classificação de reasons | `apps/ingestion/run_lifecycle.py` | `classify_failure_reason(exc) -> (reason, timed_out)` (taxonomia sanitizada; não muda) |
| Resgate de URL de PDF | `persistent_evolution_pdf.py` | `_resolve_pdf_url`: `<object data>` → fallback viewer frames → ausência |

## D1 — Retry por classe de falha (fail-fast determinístico)

**Decisão:** função pura em `run_lifecycle.py`:

```python
_DETERMINISTIC_FAILURE_REASONS: frozenset[str] = frozenset({"invalid_payload"})

def should_retry_failure_reason(failure_reason: str) -> bool:
    """Deterministic payload failures must not burn retry attempts."""
    return failure_reason not in _DETERMINISTIC_FAILURE_REASONS
```

Os dois `_mark_run_failed` passam a decidir:

```python
retryable = should_retry_failure_reason(failure_reason)
if run.attempt_count < run.max_attempts and retryable:
    ...  # requeue +60s (inalterado)
else:
    ...  # terminal + FinalRunFailure + close batch (inalterado)
```

- O ramo fail-fast reutiliza o ramo terminal existente (mesma persistência,
  mesmo `record_final_run_failure`, mesmo fechamento de batch) — sem
  duplicar lógica; a única mudança é a guarda.
- Log sanitizado distinto no fail-fast (ex.: `failed deterministically
  (reason=invalid_payload), fail-fast`) — sem alerta externo (non-goal).
- Efeito colateral positivo: captura vazia batch-bound (RPAP-S2, reason
  `invalid_payload`) também deixa de queimar 3 tentativas — correto, pois
  vazio determinístico não cicatriza com retry.
- `FinalRunFailure.attempts_exhausted` passa a registrar 1 nesses casos
  (fato coerente; `record_final_run_failure` já lê `attempt_count`).

**Alternativas rejeitadas:** retry-policy por modelo novo (YAGNI — a guarda
por reason resolve); mover a decisão para o adapter (o ciclo de vida do run
é dos workers; `run_lifecycle` é o lar DRY da taxonomia/política).

## D2 — Orçamento de tempo por volume (H1)

**Decisão:** função pura no módulo do fluxo (importável sem Django):

```python
def evolution_window_budget_seconds(
    start_date: str, end_date: str, *,
    base_seconds: int = 120, seconds_per_day: int = 2,
    cap_seconds: int = 600,
) -> int:
    """Bounded budget scaled by the window span (days)."""
```

- `budget = min(cap, base + seconds_per_day × dias)`; mesma data → base;
  datas inválidas/invertidas → `EvolutionPdfError` sanitizado.
- Worker persistente: `timeout=evolution_window_budget_seconds(
  window["start_date"], window["end_date"])` no laço de janelas de gap.
- Parâmetros nomeados com defaults: 120s base (valor atual — janelas
  curtas inalteradas), +2s/dia, teto 600s. A evidência orienta: p90 atual
  = 124s (maioria fica pouco acima do fixo); janelas de primeiro sync de
  longa permanência têm semanas/meses de span.
- **Bounded preservado:** volume acima do teto continua falhando
  `EvolutionPdfTimeoutError` → `timeout` (contrato D14 intacto; o
  laboratório CFC com deadline curto experimental continua reproduzindo).
- Orçamento é por **janela**; o total do run cresce com o nº de janelas do
  plano de gaps (como hoje), cada janela permanece limitada.

**Alternativas rejeitadas:** paginação com continuação (mudança invasiva no
fluxo/UI do legado, sem evidência de necessidade além do orçamento);
escalar pelo nº de itens (desconhecido antes do download — o span da janela
é o proxy disponível e gratuito); elevar só o default fixo (não distingue
volume; já refutado pela ADR como correção por suposição).

## D3 — Caracterização das validações de payload (H2b)

**Decisão:** suíte de caracterização contra o código real, sem relaxar
taxonomia:

1. `object` com `data` vazio **+ viewer frame com URL `.pdf`/`file=`** →
   resolve pelo viewer (resgate existe hoje; ganha teste de regressão);
2. `object` ausente/`data` vazio **sem viewer** → `EvolutionPdfError`
   ("could not be located") → `invalid_payload` (ausência genuína);
3. resposta com `content-type: text/html` onde se espera PDF →
   `assert_pdf_response_signature` → `invalid_payload`;
4. corpo sem assinatura `%PDF-` → idem;
5. `_parse_evolutions_json` com raiz não-lista/JSON inválido →
   `InvalidJsonError` → `invalid_payload`;
6. `_extract_json_from_container` sem container →
   `SnapshotContainerMissingError` → `invalid_payload`.

Regra do slice: testes descrevem o comportamento **correto** documentado.
Se algum teste falhar (RED), o gap é real e a correção é estritamente
local ao gap comprovado; se todos passarem (verde), o veredito é "sem
lacuna de parsing" — a suíte permanece como regressão permanente. Em
qualquer outcome, o slice tem veredito binário registrável (ver protocolo
de sensibilidade no prompt do slice — mutação temporária para provar que a
suíte detecta regressão).

**Alternativas rejeitadas:** criar reasons novos para "ausência" vs
"inválido" (mudaria taxonomia — non-goal); alertar por validação
disparada (observável via stage metrics existentes).

## D4 — Observabilidade preservada

Health check (`check_ingestion_pipeline_health`) e caracterização
(`characterize_fullsync_failures`) leem reasons/estágios dos mesmos campos;
nenhum contrato muda. Efeitos esperados pós-correção (documentados no
runbook, §6.3): `attempts` médios por paciente da coorte caem (fail-fast);
`timeout` torna-se mais raro em janelas longas; `invalid_payload` permanece
visível com menos queima. Nenhum limiar do health check é alterado.

## Estratégia de testes

- **Unit puro** (sem Django/browser): `should_retry_failure_reason`;
  `evolution_window_budget_seconds` (datas, cap, erros).
- **Unit com banco** (padrão dos workers existentes): `_mark_run_failed`
  de cada worker com exc tipadas (`InvalidJsonError` → terminal 1ª
  tentativa; `EvolutionPdfTimeoutError` → requeue com backoff) — inclui
  regressão do caminho retryável inalterado.
- **Unit com fakes duck-typed** (padrão CFC/laboratório): orçamento por
  janela no call site do worker persistente; caracterização D3.
- **Sensibilidade**: no slice de caracterização, prova de mutação
  temporária (quebrar o fallback do viewer → teste falha → reverter).
- Gates oficiais do repo em todos os slices; laboratório CFC re-executado
  no slice final (vereditos H1/H2 inalterados com deadlines
  experimentais).

## Riscos e mitigações

| Risco | Mitigação |
| --- | --- |
| Fail-fast esconde falha transitória mal classificada como `invalid_payload` | Taxonomia PSW-S17 é conservadora por construção; slice de caracterização D3 pinna os mapeamentos; health check continua expondo reasons |
| Orçamento escalado aumenta tempo de execução por run | Teto 600s/janela; janelas curtas inalteradas (base 120s); monitorável via stage metrics (median/p90) |
| Worker clássico diverge do persistente | Retry-policy compartilhada (D1) nos dois workers; orçamento por volume documentado como backlog do worker clássico (fora da topologia de produção) |
| Falso "sem lacuna" na caracterização | Prova de sensibilidade por mutação temporária obrigatória no slice |

## Dimensionamento dos slices

4 slices verticais, ordem de valor operacional:

1. **FX-S1** — fail-fast determinístico (para a queima imediatamente).
2. **FX-S2** — orçamento por volume (recupera as extrações longas).
3. **FX-S3** — caracterização das validações (trava H2b com evidência).
4. **FX-S4** — regressão laboratório + nota operacional + verificação
   final do change.

Cada slice: handoff com contexto zero, protocolo DeepSeek4-Flash, TDD
RED→GREEN→REFACTOR, inspeções `rg`, condições automáticas de INCOMPLETO,
relatório em `/tmp/sirhosp-slice-FX-S<n>-report.md` com handoff para
verificador terceiro.
