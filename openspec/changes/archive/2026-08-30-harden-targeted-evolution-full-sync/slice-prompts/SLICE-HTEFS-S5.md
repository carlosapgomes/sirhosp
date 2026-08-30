# HTEFS-S5 — Subetapas e progresso sanitizados

## Handoff para implementador LLM com contexto zero

Leia integralmente, nesta ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. todo o change, com foco em `design.md` D6,
   `specs/ingestion-run-observability/spec.md`, demais deltas e `tasks.md`;
3. relatórios verificados S1–S4 em `/tmp`, tasks e commits; ausência bloqueia;
4. `apps/ingestion/models.py`: `IngestionRunStageMetric` e choices de status
   (somente leitura; não criar migration);
5. `_record_stage`, `_stage_error_details` e `_process_full_sync` no worker
   persistente já incremental de S3;
6. dispatch de `extract_evolutions` no adapter entregue por S2;
7. fluxo completo `extract_evolutions_via_legacy_actions` no bridge, incluindo
   helpers obrigatórios, downloads, parse, vazio explícito e catches;
8. `safe_error_message`, `safe_error_type` e taxonomia em
   `run_lifecycle.py` (somente leitura);
9. specs e testes atuais de sanitização/observability/stage metrics para seguir
   sentinelas e padrões.

Estado atual: uma falha aparece genericamente em `evolution_extraction`. Após
S1–S3, o fluxo tem alvo e chunks seguros, mas o operador ainda não distingue
seleção, detalhe, ativação, geração, download e parse. Este slice adiciona um
protocolo opcional de eventos com enum fechado e métricas agregadas, sem novo
sistema de logs nem contexto sensível.

## Protocolo obrigatório para DeepSeek4-Flash

Qualquer item não comprovado implica `Status: INCOMPLETE`, sem tasks/commit/push.

1. Capture BASE_REF, árvore limpa, S1–S4 verificados.
2. Matriz requisito→arquivo→teste antes de editar.
3. Baseline unit oficial; falha bloqueia.
4. RED real primeiro, incluindo sentinelas e falha do callback.
5. GREEN mínimo e REFACTOR local clean/DRY/YAGNI; não mudar taxonomia/model.
6. Inspeções obrigatórias e revisão integral do diff do change.
7. Todos os gates,
   `openspec validate harden-targeted-evolution-full-sync --strict` e markdown
   lint exit 0;
   unit final >= baseline.
8. Relatório final com handoff para terceiro LLM; não arquivar automaticamente.

## Objetivo end-to-end

Durante uma sync alvo, bridge emite started/terminal para subetapas de enum
fechado; adapter apenas repassa callback opcional; worker materializa stage
metrics sanitizadas e mantém counters agregados de chunks planejados,
confirmados e falhos mesmo em partial failure. Falha de telemetria não muda o
resultado/taxonomia da extração. Nenhuma métrica/log inclui identidade, datas,
selector, URL, conteúdo ou raw exception.

## Requisitos funcionais

- **R1 — Enum fechado:** definir uma única coleção/enum com exatamente os nomes
  necessários (máximo): `evolution_search_navigation`,
  `evolution_admissions_capture`, `evolution_target_selection`,
  `evolution_detail_open`, `evolution_action_activation`,
  `evolution_report_generation`, `evolution_pdf_download`,
  `evolution_pdf_parse`, `evolution_chunk_commit`. Não aceitar nome dinâmico.
- **R2 — Protocolo mínimo:** callback opcional recebe somente nome enum e estado
  `started`/`succeeded`/`failed` (ou objeto tipado equivalente sem payload).
  Adapter o repassa apenas ao action method real; stub sem callback permanece.
- **R3 — Pares corretos:** cada subetapa instrumentada emite started antes da
  ação e um único terminal. Exception em ação emite failed antes de propagar o
  mesmo erro tipado; sucesso emite succeeded. Vazio explícito é sucesso das
  ações que o alcançaram.
- **R4 — Materialização:** worker closure associa started a monotonic/timezone
  start e cria `IngestionRunStageMetric` terminal com timestamps/status. Não
  persiste status `started` porque model não o suporta. Stage name vem do enum.
- **R5 — Telemetria best-effort:** exception do callback/ORM é engolida em
  boundary sanitizada ou registrada por constante; nunca mascara ação, muda
  retorno ou reclassifica failure reason. Não usar `except` para engolir a ação
  clínica.
- **R6 — Agregados de chunk:** stage agregado de extraction/persistence inclui
  somente inteiros `chunks_planned`, `chunks_committed`, `chunks_failed`,
  `events_processed`; atualizar também no ramo de falha posterior.
- **R7 — Commit observável:** `evolution_chunk_commit` sucede somente após a
  transação de S3 confirmar. Se transação falha, stage terminal é failed e
  `chunks_committed` não incrementa.
- **R8 — Contadores coerentes:** ao final, agregados concordam com cumulative
  run counters e ledger; em partial failure, committed preservado e failed >=1.
- **R9 — Sanitização estrita:** callback, details e novas linhas de log não têm
  patient/admission/source ids, datas/bounds, clinical text, profissão, URL,
  selector, HTML/PDF, cookie/credential, exception class/text ou sentinelas.
- **R10 — Contratos preservados:** taxonomy, `safe_error_*`, choices do model,
  stub path e caller sem callback não mudam. Sem model/migration/dependência.

## TDD obrigatório

### RED mínimo

No novo arquivo consolidado, prove:

1. enum é fechado, nomes estáveis e <=50 caracteres;
2. fluxo alvo bem-sucedido emite ordem started→succeeded para seleção, detalhe,
   ativação, geração, download e parse (instrumente search/admissions também);
3. timeout na ativação emite `evolution_action_activation: failed` e propaga o
   mesmo tipo timeout para classificação `timeout`;
4. parse failure emite parse failed e mantém `invalid_payload`/tipo existente;
5. callback ausente não muda resultado e stub dispatch não recebe argumento
   incompatível;
6. callback que lança sentinela não impede extração nem substitui a exception
   original de ação;
7. worker cria stage metric com enum/status/timestamps, sem payload dinâmico;
8. dois chunks commitados: planned=2, committed=2, failed=0 e counters coerentes;
9. primeiro commit e segundo falha: committed=1, failed=1, eventos do primeiro
   preservados e parent run segue retry/failure;
10. falha dentro da transação emite chunk_commit failed e não incrementa
    committed;
11. sem callback, suites anteriores de adapter/bridge continuam verdes;
12. injete sentinelas distintas em patient record, admission key, datas, URL,
    selector, cookie e raw exception; serialize stdout/stderr + todos os novos
    `details_json` e prove ausência literal de cada uma.

Fakes somente; sem browser/rede. Não faça teste que passa por apenas procurar
strings no source; outcomes e rows DB devem ser exercitados.

### GREEN

Implementar R1–R10 nos quatro arquivos permitidos.

### REFACTOR

- helper/contexto pequeno no bridge para pares started/terminal, sem decorar
  dezenas de funções globais;
- uma coleção enum, sem strings duplicadas no worker;
- closure/protocol opcional, não framework de events;
- detalhes somente ints permitidos;
- nenhum `str(exc)`, data, id ou kwargs da ação no callback.

## Arquivos permitidos

Limite de **4 arquivos**, além de `tasks.md`:

1. `apps/ingestion/extractors/real_handle_bridge.py`;
2. `apps/ingestion/extractors/persistent_extraction_adapter.py`;
3. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`;
4. `tests/unit/test_evolution_substep_observability.py` (novo).

Proibido: models/migrations, run_lifecycle, navigation, worker clássico, services,
views/templates, settings, docs/specs/design, dependências. Arquivo extra =
bloqueio.

## Inspeções obrigatórias

```bash
rg -n "evolution_(search_navigation|admissions_capture|target_selection|detail_open|action_activation|report_generation|pdf_download|pdf_parse|chunk_commit)" \
  apps/ingestion/extractors/real_handle_bridge.py \
  apps/ingestion/extractors/persistent_extraction_adapter.py \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "progress|callback|started|succeeded|failed" \
  apps/ingestion/extractors/real_handle_bridge.py \
  apps/ingestion/extractors/persistent_extraction_adapter.py
rg -n "chunks_planned|chunks_committed|chunks_failed|events_processed" \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "str\(exc\)|details_json|patient_record|admission_key|start_date|end_date" \
  apps/ingestion/extractors/real_handle_bridge.py \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "SENTINEL|callback.*fail|partial|chunks_committed" \
  tests/unit/test_evolution_substep_observability.py
git diff --check
git diff --stat "$BASE_REF"
git diff "$BASE_REF" -- apps/ingestion/models.py apps/ingestion/run_lifecycle.py \
  apps/ingestion/management/commands/process_ingestion_runs.py
```

Último diff deve estar vazio. O `rg` de campos sensíveis pode encontrar código
preexistente necessário; interprete **cada ocorrência nova** e prove que não
entra em callback/details/log. Não aceite grep vazio como única prova.

## Revisão integral obrigatória

Antes dos gates finais:

```bash
git diff --name-status <BASE_ANTERIOR_A_S1>..HEAD
rg -n "markdownlint-disable" \
  openspec/changes/harden-targeted-evolution-full-sync
openspec validate harden-targeted-evolution-full-sync --strict
```

Obtenha o base anterior a S1 dos relatórios. Mapeie no relatório cada
requirement dos quatro delta specs para ao menos um teste. Confirme ausência de
dados reais, credenciais, dependências, Celery/Redis, upload PDF e mudanças fora
dos cinco slices. Não edite artefatos para esconder inconsistência; se houver,
pare como bloqueio para planejamento.

## Critérios binários de aceite

- [ ] R1–R10 têm RED/GREEN.
- [ ] Enum único/fechado e pares started→terminal corretos.
- [ ] Falha localizada preserva tipo/taxonomia original.
- [ ] Callback ausente/stub e callback quebrado não mudam outcome.
- [ ] Chunk commit só sucede após transaction; partial totals coerentes.
- [ ] Sentinelas ausentes de outputs e novos details DB.
- [ ] Models/taxonomy/worker clássico intactos.
- [ ] Máximo 4 arquivos + tasks.
- [ ] Rastreabilidade completa specs→testes; diff integral sem non-goals.
- [ ] Gates, OpenSpec strict e markdown lint exit 0; unit final >= baseline.

### Condições automáticas de INCOMPLETO

S1–S4 não verificados; baseline/RED ausente; nome de stage dinâmico; started
persistido como status inválido; callback recebe kwargs/contexto; exception do
callback mascara ação; failed não propaga erro original; chunk commit antes da
transação; contador incoerente; sentinela em qualquer surface; raw exception;
model/migration/taxonomy/worker clássico alterado; arquivo extra; requisito sem
teste; gate/OpenSpec/markdown falho; relatório incompleto; tasks marcadas sem
evidência; archive executado sem autorização.

## Gates de autoavaliação

1. Qual teste prova localização da ativação sem mudar `timeout`?
2. Qual prova parse failed mantendo classificação existente?
3. Como callback quebrado fica best-effort sem engolir a ação clínica?
4. Qual row/detail prova partial committed=1/failed=1?
5. Qual teste serializa todas as surfaces e elimina cada sentinela?
6. Onde o enum é único e como nomes dinâmicos são rejeitados?
7. Quais testes cobrem cada requirement dos quatro delta specs?

## Validação mínima

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
openspec validate harden-targeted-evolution-full-sync --strict
```

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-HTEFS-S5-report.md` com Status, BASE_REF, base anterior
a S1, verificação S1–S4, matriz R1–R10 e rastreabilidade de todas as specs,
baseline, RED/GREEN, snippets antes/depois **de cada arquivo** (`tasks.md`
incluído), sentinelas e surfaces verificadas, inspeções interpretadas, revisão
do diff integral, gates/OpenSpec/markdown com exit/resumo, riscos/pendências e
`Handoff para verificador` com comandos exatos e checklist.

Se completo, marque somente 5.x, markdown lint, commit/push e STOP. Não arquive
o change; aguarde terceiro LLM e autorização explícita do operador.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the entire harden-targeted-evolution-full-sync change and verified S1-S4 reports. Implement ONLY HTEFS-S5 exactly as its slice prompt. Require clean BASE_REF and unit baseline. RED first for a single closed substep enum, ordered started→terminal events, activation timeout and parse failure localization preserving original taxonomy, optional/stub compatibility, callback failure best-effort, DB stage materialization, successful and partial chunk aggregates, transaction commit failure, and serialized sentinel absence across stdout/stderr/new details_json. Minimal GREEN only in bridge, adapter and persistent worker plus one consolidated test; no model/migration/taxonomy/navigation/classic worker edits. Run all rg/read-only diffs, whole-change requirements→tests audit, official gates, markdown lint and openspec validate harden-targeted-evolution-full-sync --strict. Create /tmp/sirhosp-slice-HTEFS-S5-report.md with before/after per file and verifier reruns. Any unmet item is INCOMPLETE without task mark/commit. If complete mark only 5.x, commit, push and STOP; do not archive without explicit authorization.
```
