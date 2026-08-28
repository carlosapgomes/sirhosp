# RPAP-S3 — Remover demografia duplicada do batch

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md` e todo o change atual;
2. prompts/relatórios COMPLETE de S1 e S2;
3. delta `patient-demographics-ingestion` e requisito Admissions-only parity;
4. `apps/census/services.py` no enqueue por paciente, sem editá-lo;
5. admissions-only nos dois commands de ingestion;
6. `tests/unit/test_current_vs_persistent_parity.py`.

Estado: o censo cria `admissions_only` e `demographics_only` no mesmo batch.
Depois, ambos os workers criam outro demographics destacado (`batch=None`). S2
já impede follow-up após vazio; este slice corrige a duplicação após sucesso.

## Protocolo obrigatório para implementador DeepSeek4-Flash

1. Registre BASE_REF, árvore limpa e matriz requisito→arquivo→teste.
2. Confirme S1/S2 COMPLETE; rode `./scripts/test-in-container.sh unit` baseline.
   Falha/error bloqueia e torna o slice INCOMPLETE.
3. Escreva RED de paridade antes do código. O teste deve falhar porque há uma
   segunda demografia batch-bound, não por fixture/import.
4. Implemente GREEN mínimo sem alterar o enqueue do censo ou full-sync.
5. Refatore somente o tocado com condição clara, DRY, YAGNI e comentários atuais.
6. Rode inspeções e todos os gates.
7. Unit final exit 0, zero failures/errors e passed_final >= baseline.
8. Relatório completo antes de marcar 3.1–3.6, commit/push e STOP.

## Objetivo vertical

Para ambos os workers, concluir um `admissions_only` batch-bound deve criar
somente o full-sync esperado, pois a demografia já pertence ao batch. Um
`admissions_only` standalone continua criando exatamente uma demografia.

## Requisitos funcionais

### R1 — Propriedade batch-bound

Se `run.batch_id` existe, não chamar `queue_demographics_only_run` no
pós-admissions. Não consultar conteúdo de `parameters_json` para inferir origem.

### R2 — Standalone preservado

Sem batch, manter exatamente um demographics follow-up destacado, com intent e
parâmetros explícitos existentes.

### R3 — Full-sync e lifecycle preservados

Em ambos os contextos, captura não vazia continua persistindo e criando o
full-sync da internação recente nas condições atuais. Não alterar attempts,
stages, counters, cleanup, retry, batch closure ou labels sanitizados.

### R4 — Paridade

Current e persistent produzem o mesmo padrão observável de follow-ups para
batch-bound e standalone.

## Arquivos esperados e limite

Máximo de **4 arquivos de código/teste rastreados** (Emenda 2):

1. `apps/ingestion/management/commands/process_ingestion_runs.py`;
2. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`;
3. `tests/unit/test_current_vs_persistent_parity.py`;
4. `tests/unit/test_persistent_worker_command.py` — SOMENTE para o reparo
   dos 2 testes de caracterização definido na seção "Reparo autorizado de
   testes de caracterização" (Emenda 2).

`tasks.md` não conta. Não editar census/services, ingestion/services, models,
migrations, adapter, templates ou docs. Se o teste de paridade não comportar a
prova, pare e reporte bloqueio; não adicionar arquivo silenciosamente.

## Reparo autorizado de testes de caracterização (Emenda 2)

A regra R1 revoga a semântica "sucesso batch-bound cria exatamente uma
demografia destacada", hoje codificada por testes de caracterização do
PSW-S15. Esses testes são parte do presente slice e devem ser atualizados
pelo novo requisito no mesmo commit da regra — nunca removidos.

Testes elegíveis ao reparo (classe `TestAdmissionsOnlyPersistenceParity` em
`tests/unit/test_persistent_worker_command.py`):

1. `test_full_sync_followup_inherits_real_non_null_batch`;
2. `test_retry_then_success_does_not_duplicate_followups`.

Contrato de reparo (modo obrigatório):

- trocar as asserções de demografia do cenário batch-bound de
  `count() == 1` para `count() == 0` (no segundo teste, tanto após o sucesso
  quanto após a reinvocação);
- remover do primeiro teste apenas a asserção dependente do registro
  existente (`demos.first().batch_id is None`), insatisfazível com
  `count() == 0`; a propriedade "detached" continua provada nas células
  standalone da matriz de paridade e nos testes de services;
- atualizar as docstrings para justificar a mudança de requisito (RPAP-S3:
  o batch do censo já é dono da única demographics do paciente);
- preservar TODAS as demais asserções: full-sync criado, herança real de
  batch (`f.batch_id == batch.pk`), propagação de parâmetros
  (`admission_source_key`, `start_date`, `end_date`, `patient_record`),
  sequência de attempts `["failed", "succeeded"]`, não duplicação após
  reinvocação e batch `running`/`finished_at is None` enquanto o filho está
  enfileirado;
- proibido remover/pular teste, deletar ou relaxar qualquer asserção não
  demográfica, ou alterar outros testes do arquivo.

## TDD obrigatório

### RED

Adicionar matriz com worker × origem:

1. current + batch: zero demographics extra, um full-sync;
2. persistent + batch: mesmo resultado;
3. current + standalone: uma demografia;
4. persistent + standalone: uma demografia;
5. snapshot não vazio e métricas clínicas preservadas;
6. nenhum weakening de testes antigos que esperavam duplicação: atualizar a
   expectativa com justificativa de mudança de requisito, estritamente pelo
   contrato da seção "Reparo autorizado de testes de caracterização"
   (Emenda 2).

### GREEN

Adicionar a menor guarda explícita no ponto do follow-up. Não criar helper,
constraint, query de dedupe ou feature flag se `run.batch_id` resolve o caso.
Com a regra ativa, reparar os 2 testes de caracterização estritamente pelo
contrato da seção "Reparo autorizado de testes de caracterização"
(Emenda 2).

### REFACTOR

Remover comentários que afirmam paridade antiga incorreta. Manter blocos
simétricos e nomes existentes; não consolidar commands inteiros.

## Checks de inspeção obrigatórios

```bash
rg -n -B 8 -A 14 "queue_demographics_only_run" \
  apps/ingestion/management/commands/process_ingestion_runs.py \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n -B 5 -A 12 "enqueue_most_recent|_enqueue_most_recent" \
  apps/ingestion/management/commands/process_ingestion_runs.py \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "batch.*demograph|standalone.*demograph|full_sync|follow.up" \
  tests/unit/test_current_vs_persistent_parity.py
rg -n "queue_demographics_only_run\(patient_record=prontuario, batch=batch\)" \
  apps/census/services.py
```

Esperado: produtor do censo permanece; workers guardam apenas demografia por
batch; full-sync continua; teste cobre as quatro células.

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

- [ ] R1–R4 provados RED/GREEN.
- [ ] Batch-bound cria zero demografia adicional em ambos os workers.
- [ ] Standalone cria uma em ambos.
- [ ] Full-sync e efeitos clínicos permanecem.
- [ ] Enqueue demográfico do censo permanece intacto.
- [ ] Exatamente quatro arquivos esperados, além de tasks (Emenda 2).
- [ ] Testes de caracterização PSW-S15 reparados pelo requisito (demografia
      batch-bound `1 -> 0`), preservando todas as demais asserções (Emenda 2).
- [ ] Gates exit 0; unit final >= baseline sem failures/errors.

### Condições automáticas de INCOMPLETO

- pré-condição/baseline/RED ausente ou falho;
- somente um worker corrigido;
- demografia do censo removida;
- standalone perde refresh;
- full-sync, retry, cleanup ou batch closure muda;
- query/constraint/migration desnecessária é criada;
- teste antigo é apagado em vez de corrigido pelo requisito;
- teste de caracterização fora dos 2 elegíveis é alterado, ou asserção não
  demográfica é deletada/relaxada para obter GREEN (Emenda 2);
- arquivo extra, PHI/secrets ou gate falho;
- relatório ausente ou task/commit prematuro.

## Gates de autoavaliação

1. Qual matriz prova os quatro caminhos?
2. Onde se demonstra que o censo continua dono da demografia?
3. Qual assert preserva full-sync?
4. Houve mudança além da guarda mínima? Por quê?
5. Por que cada arquivo é indispensável?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-RPAP-S3-report.md` com Status, BASE_REF, matriz,
RED/GREEN, snippets, inspeções, baseline/final, gates, rerun, riscos,
justificativas e `Handoff para verificador` R1–R4.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, all repair-persistent-admissions-pipeline
artifacts, SLICE-RPAP-S3.md and COMPLETE S1/S2 reports, plus the INCOMPLETE
S3 report (blocking). Implement ONLY S3, resuming: BASE_REF 4e27f60 already
holds the verified uncommitted GREEN in the three authorized files (guards in
both workers + parity matrix + strengthened S2 nonempty test) — do NOT
discard or rewrite it; confirm it still matches the blocking report via git
diff, then apply the Emenda 2 repair to the two PSW-S15 characterization
tests and rerun every gate. Follow the DeepSeek4-Flash protocol: official unit
baseline, real RED parity matrix already proven (reproduce if needed), minimal
GREEN, mandatory rg and all official gates, final passed >= baseline with
zero failures/errors. Batch-bound admissions must enqueue no extra
demographics; standalone must keep one; full-sync and census-owned
demographics remain. Touch
at most the four listed files. Repair the two PSW-S15 characterization tests
(TestAdmissionsOnlyPersistenceParity) per the Emenda 2 contract: batch-bound
demographics count 1 -> 0 (both spots in the retry test), drop only the
unsatisfiable demos.first().batch_id assertion, update docstrings, and
preserve every non-demographics assertion; never delete or weaken a test. Do
not add
dedupe infrastructure, recovery, health, models or migrations. Create
/tmp/sirhosp-slice-RPAP-S3-report.md with evidence and verifier handoff. Any
missing/failing item means INCOMPLETE: no task update or commit. If complete,
mark only S3, commit, push, reply REPORT_PATH=..., then STOP.
```

## Histórico de emendas

- **Emenda 2** — decisão do planner após bloqueio reportado em
  `/tmp/sirhosp-slice-RPAP-S3-report.md` (INCOMPLETE, sem edições fora dos 3
  arquivos autorizados, sem tasks/commit) e verificação independente por
  terceiro LLM. O RED item 6 exigia atualizar testes antigos que codificam o
  requisito revogado, mas o limite de 3 arquivos não incluía nenhum arquivo
  de teste antigo — o mesmo conflito estrutural da Emenda 1 do S2. Orçamento
  ampliado de 3 para 4 arquivos, autorizando o reparo dos 2 testes de
  caracterização do PSW-S15 (`TestAdmissionsOnlyPersistenceParity`) pelo
  próprio S3: única solução em código que satisfaz R1 deixa `count()` de
  demografia batch-bound em 0. Verificação independente confirmou: RED
  genuíno por asserção (célula batch-bound e teste não-vazio S2 fortalecido),
  guarda mínima correta nos dois workers, censo/full-sync intocados e
  exatamente essas 2 falhas de unit (nenhuma outra). Fora o limite e o novo
  contrato de reparo, nenhuma outra semântica do slice foi alterada.
