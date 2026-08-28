# RPAP-S2 — Falhar captura vazia vinculada a batch

## Handoff com contexto zero

Leia integralmente antes de editar:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. todo o change `repair-persistent-admissions-pipeline`;
3. `slice-prompts/SLICE-RPAP-S1.md` e
   `/tmp/sirhosp-slice-RPAP-S1-report.md`;
4. `apps/ingestion/extractors/errors.py` e `run_lifecycle.py`;
5. os métodos de admissions/full-sync nos dois commands
   `process_ingestion_runs*.py`;
6. `apps/ingestion/services.py` em `persist_admissions_snapshot` e follow-ups;
7. `tests/unit/test_current_vs_persistent_parity.py`;
8. `tests/unit/test_persistent_worker_command.py` e
   `tests/integration/test_worker_lifecycle.py` somente para localizar fixtures.

Pré-condição: S1 está COMPLETE e o bridge entrega o snapshot real. Atualmente
listas vazias continuam válidas em todos os contextos. Este slice distingue run
batch-bound de sincronização standalone e mantém paridade dos dois workers.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Se qualquer item falhar, declare `INCOMPLETE`, não marque tasks, não faça
commit/push e pare.

1. Registre BASE_REF, árvore limpa e matriz requisito→arquivo→teste.
2. Confirme relatório S1 COMPLETE. Rode baseline oficial
   `./scripts/test-in-container.sh unit`; qualquer failure/error bloqueia.
3. Escreva RED primeiro. Pelo menos um teste novo deve falhar porque um run
   batch-bound vazio termina como succeeded ou persiste efeito indevido.
4. Implemente GREEN mínimo nos arquivos permitidos. Não misture a deduplicação
   demográfica de S3.
5. Refatore somente o trecho tocado: validação única/coesa, exceção clara, DRY,
   YAGNI, sem lógica clínica complexa no command.
6. Rode inspeções, unit, integration e todos os gates oficiais.
7. Exija unit final exit 0, zero failures/errors e passed_final >= baseline.
8. Gere relatório; só depois marque 2.1–2.6, commit/push e pare.

## Objetivo vertical

Nos workers atual e persistente, uma captura vazia ligada a batch deve seguir o
caminho real de falha/retry antes da persistência e sem follow-ups, enquanto uma
captura standalone vazia mantém o feedback explícito já suportado.

## Requisitos funcionais

### R1 — Erro tipado e taxonomia

Introduzir uma exceção de snapshot de internações vazio, sanitizada e
classificada como `invalid_payload` sem mensagem contendo contexto clínico. Não
adicionar novo choice/model/migration.

### R2 — Regra contextual compartilhada

Aplicar a mesma regra nos dois workers: vazio é inválido quando `run.batch_id`
não é nulo. Cobrir `admissions_only` e a captura obrigatória anterior a
full-sync batch-bound. Não duplicar condições divergentes se um helper pequeno
puder ser compartilhado.

### R3 — Zero efeito em falha

Antes de falhar não criar/alterar Patient ou Admission, não gravar estágio de
admissions como succeeded, não marcar attempt succeeded, não criar demografia
ou full-sync e não registrar contador positivo. Cleanup e retry existentes
devem ocorrer.

### R4 — Standalone preservado

Run sem batch com snapshot vazio mantém o contrato de `no admissions found`,
eventos zero e nenhum candidato de evolução. Não quebrar endpoints/testes
históricos dessa jornada.

### R5 — Paridade observável

Current e persistent devem concordar em status/retry, attempt, stage,
`failure_reason`, `timed_out`, contadores, persistência, follow-ups e batch
closure para vazio batch-bound.

## Arquivos esperados e limite

Máximo de **6 arquivos de código/teste rastreados** (Emenda 1):

1. `apps/ingestion/extractors/errors.py`;
2. `apps/ingestion/management/commands/process_ingestion_runs.py`;
3. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`;
4. `tests/unit/test_current_vs_persistent_parity.py`;
5. `tests/unit/test_persistent_worker_command.py` OU
   `tests/integration/test_worker_lifecycle.py`, quando a matriz de paridade
   ou o reparo de fixtures exigir;
6. `tests/integration/test_ingestion_batch_closure.py` — SOMENTE para o
   reparo de fixtures obsoletos definido na seção "Reparo autorizado de
   fixtures" (Emenda 1).

`tasks.md` não conta. Não editar bridge, services, models, migrations, views,
templates ou docs. Se lógica compartilhada exigir `services.py`, pare e reporte
bloqueio em vez de exceder silenciosamente; o planner decidirá troca de arquivo.

## Reparo autorizado de fixtures obsoletos (Emenda 1)

A regra R2 revoga a semântica "captura vazia batch-bound termina em sucesso",
hoje codificada por fixtures pré-existentes. Esses fixtures são parte do
presente slice e devem ser reparados no mesmo commit da regra — nunca
removidos.

Motivo técnico dos itens 5 e 6 da lista abaixo: `try_close_batch` só fecha o
batch quando nenhum run está `queued`/`running`, e run em retry volta a
`queued`; portanto um run batch-bound vazio que passa a falhar/retry mantém o
batch aberto e quebra as asserções de fechamento desses testes.

Fixtures elegíveis ao reparo (executar o arquivo completo no baseline —
esperado: passa — e reexecutar após o GREEN; reparar cada um que quebrar):

1. em `tests/integration/test_ingestion_batch_closure.py`:
   - `TestBatchClosure::test_batch_closes_when_last_run_succeeds`;
   - `TestBatchClosure::test_batch_closes_when_last_full_sync_run_skips_extraction`;
   - `TestBatchClosure::test_batch_stays_running_while_other_runs_are_queued`;
   - `TestBatchClosure::test_batch_closes_after_both_runs_complete`;
   - `TestBatchClosure::test_batch_status_failed_when_any_final_failure_exists`
     (MIX_P1 recebe `[]` na primeira chamada do `side_effect`);
   - `TestBatchDurationComputability::test_duration_computable_after_closure`
     (DUR_P1 com `[]`).
2. em `tests/unit/test_persistent_worker_command.py`:
   - `TestBatchClosure::test_batch_closed_after_last_run_succeeds`
     (`_make_adapter_mock(snapshot_result=[])`).

Contrato de reparo (modo obrigatório):

- substituir o snapshot vazio (`[]`) por snapshot sintético mínimo NÃO vazio,
  no mesmo formato já usado por fixtures existentes (por exemplo o shape de
  `ADM_BATCH_001` em `tests/integration/test_ingestion_worker_retries.py`);
- preservar TODAS as asserções e invariantes originais: fechamento por
  drenagem como `succeeded`, permanência `running` com runs enfileirados,
  fechamento `failed` quando existe falha terminal e duração computável
  após fechamento;
- em MIX_P1, a primeira chamada do `side_effect` devolve o snapshot não
  vazio e a segunda continua levantando `ExtractionError` (MIX_P2 segue
  falha terminal);
- se follow-ups disparados pelo snapshot não vazio alterarem a drenagem do
  batch, isolá-los com patch explícito, mantendo as asserções originais;
- proibido remover teste, deletar/relaxar/pular asserção ou mascarar quebra
  para obter GREEN.

## TDD obrigatório

### RED

Cobrir sinteticamente:

1. current `admissions_only` batch-bound vazio;
2. persistent `admissions_only` batch-bound vazio;
3. ao menos um full-sync batch-bound vazio por caminho compartilhado;
4. razão `invalid_payload`, sem timeout;
5. zero Patient/Admission, stage success, attempt success e follow-up;
6. cleanup/retry preservado;
7. standalone vazio continua com resultado antigo em ambos os workers;
8. snapshot não vazio batch-bound continua persistindo e criando full-sync.

Rode unit oficial e registre failure assertivo pelo falso sucesso atual.

### GREEN

Criar a menor exceção e validação antes de qualquer persistência. Reusar a
máquina de falha/retry/cleanup existente; não criar status novo nem `if` de
produção baseado em labels ou datas do incidente. Com a regra ativa, reparar
os fixtures obsoletos estritamente pelo contrato da seção "Reparo autorizado
de fixtures" (payload não vazio, asserções intactas).

### REFACTOR

Eliminar duplicação apenas se isso couber no limite. Não mover orquestração ampla
para serviço novo, não renomear intents e não alterar taxonomia congelada além
de incluir a exceção no ramo já existente de payload inválido.

## Checks de inspeção obrigatórios

```bash
rg -n "Empty.*Admission|empty.*snapshot|invalid_payload" \
  apps/ingestion/extractors/errors.py \
  apps/ingestion/management/commands/process_ingestion_runs.py \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "persist_admissions_snapshot|queue_demographics_only_run|enqueue_most_recent|status = \"succeeded\"" \
  apps/ingestion/management/commands/process_ingestion_runs.py \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "batch.*empty|standalone.*empty|invalid_payload|no.*follow" \
  tests/unit/test_current_vs_persistent_parity.py \
  tests/unit/test_persistent_worker_command.py tests/integration/test_worker_lifecycle.py \
  tests/integration/test_ingestion_batch_closure.py
rg -n "class .*Error|SnapshotContainerMissingError" \
  apps/ingestion/extractors/errors.py apps/ingestion/run_lifecycle.py
```

Interpretar ordem da validação antes de persistência/sucesso/follow-up, provar
que a exceção chega a `invalid_payload` sem novo choice e que os fixtures de
batch-closure reparados preservam todas as asserções originais.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate repair-persistent-admissions-pipeline --strict
./scripts/markdown-lint.sh
```

## Critérios binários de sucesso

- [ ] R1–R5 cobertos RED/GREEN.
- [ ] Ambos os workers falham vazio batch-bound antes de persistir.
- [ ] `failure_reason=invalid_payload`, `timed_out=False` e mensagem sanitizada.
- [ ] Nenhum follow-up, stage/attempt success ou contador positivo na falha.
- [ ] Cleanup/retry e batch closure seguem sem regressão.
- [ ] Standalone vazio e batch não vazio permanecem.
- [ ] Fixtures obsoletos de batch-closure reparados com snapshot sintético não
      vazio, preservando todas as asserções originais (Emenda 1).
- [ ] Máximo de seis arquivos e nenhum escopo S3+ antecipado.
- [ ] Gates exit 0; unit final >= baseline e sem failures/errors.

### Condições automáticas de INCOMPLETO

- S1/report não confirmado;
- baseline/RED/gate ausente ou falho;
- validação ocorre depois de Patient/Admission ou status succeeded;
- somente um worker é corrigido;
- full-sync batch-bound pode continuar após vazio;
- standalone vazio é transformado em falha;
- novo model/status/migration/choice é adicionado;
- mensagem/teste contém PHI, URL, HTML, PDF ou credencial;
- teste antigo é removido/enfraquecido para obter GREEN;
- fixture elegível é removido, pulado ou tem asserção deletada/relaxada em
  vez de reparado por snapshot não vazio (Emenda 1);
- arquivo fora do limite é tocado sem bloqueio;
- relatório ausente ou task marcada prematuramente.

## Gates de autoavaliação

1. Qual teste prova a ordem fail-before-persist?
2. Qual teste compara os dois workers?
3. Como a exceção chega a `invalid_payload` sem migration?
4. Qual teste preserva standalone vazio?
5. Quais efeitos colaterais foram explicitamente negados?
6. Por que cada arquivo alterado é necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-RPAP-S2-report.md` com Status, BASE_REF, matriz,
evidência RED/GREEN, snippets antes/depois, ordem de efeitos, inspeções, unit
baseline/final, todos os gates, rerun, riscos, arquivos/justificativa, respostas
e `Handoff para verificador` R1–R5. Não incluir dados reais/sensíveis.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full change
repair-persistent-admissions-pipeline, SLICE-RPAP-S2.md and the COMPLETE S1
report. Implement ONLY S2. Record clean BASE_REF and official unit baseline,
write real RED tests for empty batch-bound admissions in current and persistent
workers, then minimal GREEN and local clean-code/DRY/YAGNI refactor. Fail before
persistence with a typed sanitized invalid_payload error; preserve standalone
empty and non-empty behavior, retries, cleanup and batch semantics. Do not
implement demographics ownership, recovery, health, models or migrations.
Touch at most the six listed files. Repair the obsolete batch-closure fixtures
(empty batch-bound snapshots asserting success) by swapping in a minimal
synthetic non-empty snapshot, preserving every original assertion and
isolating follow-ups with explicit patches when needed; never delete or
weaken a test. Run rg inspections and every official gate;
final unit must have exit 0, zero failures/errors and passed >= baseline. Create
/tmp/sirhosp-slice-RPAP-S2-report.md with RED/GREEN, snippets, gates, rerun and
Handoff para verificador. On any missing/failing item report INCOMPLETE, do not
mark tasks or commit. If all pass, mark only S2 tasks, commit, push, reply
REPORT_PATH=..., then STOP.
```

## Histórico de emendas

- **Emenda 1** — decisão do planner após bloqueio reportado em
  `/tmp/sirhosp-slice-RPAP-S2-report.md` (INCOMPLETE sem edições) e
  verificação independente por terceiro LLM. Orçamento ampliado de 5 para
  6 arquivos, autorizando o reparo de fixtures obsoletos de batch-closure
  pelo próprio S2 (Opção A: regra e contratos revogados no mesmo commit).
  Correção da contagem do bloqueio: são 6 testes elegíveis em
  `test_ingestion_batch_closure.py` — os 4 originais mais
  `test_batch_status_failed_when_any_final_failure_exists` e
  `test_duration_computable_after_closure`, que também quebram porque
  `try_close_batch` mantém o batch aberto enquanto um run reenfileirado
  para retry permanece `queued` — além de 1 em
  `test_persistent_worker_command.py`. Fora o limite e o novo contrato de
  reparo, nenhuma outra semântica do slice foi alterada.
