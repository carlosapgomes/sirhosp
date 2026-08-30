# HTEFS-S3 — Cobertura e commit incremental por chunk

## Handoff para implementador LLM com contexto zero

Leia integralmente, nesta ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. este change completo, com foco em `design.md` D3/D4,
   `specs/evolution-extraction-coverage/spec.md`, observability delta e
   `tasks.md`;
3. relatórios verificados de S1/S2 em `/tmp`; confirme tasks 1.x/2.x e commits.
   Ausência de verificação bloqueia;
4. `apps/ingestion/models.py` e a migration mais recente em
   `apps/ingestion/migrations/`;
5. `apps/patients/models.py`: `Admission`;
6. `apps/ingestion/gap_planner.py` e seus testes; identifique a inferência
   atual por `ClinicalEvent` e preserve compatibilidade não alvo;
7. `automation/source_system/medical_evolution/chunking.py` e o wrapper
   `build_chunks_for_interval` já usado pelo bridge; não copie o algoritmo;
8. `apps/ingestion/evolution_ingestion.py`: transações internas e retorno de
   contadores;
9. `_process_full_sync` e `_mark_run_failed` no worker persistente entregue por
   S2, incluindo `all_evolutions`, `gaps_json`, stages e counters;
10. testes de planner, worker e migrations para seguir fixtures sintéticas.

Estado atual: o planner alvo ainda pode inferir cobertura porque existe um
evento no dia; o worker acumula todas as janelas antes de persistir. Uma falha
posterior descarta todo o acumulado. S2 garante que, no modo alvo, falha de ação
não vira vazio; isso é pré-condição para registrar cobertura vazia com segurança.

## Protocolo obrigatório para DeepSeek4-Flash

Qualquer item não comprovado implica `Status: INCOMPLETE`, sem tasks/commit/push.

1. Capture `BASE_REF`, exija árvore limpa e S1/S2 verificados.
2. Registre matriz `requisito → arquivo → teste` antes de editar.
3. Rode baseline oficial unit **e integration**; qualquer falha bloqueia.
4. Faça RED primeiro. Pelo menos um teste novo deve falhar pela ausência do
   ledger e outro pelo acúmulo tardio atual, não por import/migration quebrada.
5. GREEN mínimo. REFACTOR local aplicando clean code, DRY, YAGNI.
6. Execute inspeções, `makemigrations --check` no container oficial quando
   possível e todos os gates.
7. Unit/integration finais sem failures/errors e passed não inferiores aos
   baselines respectivos.
8. Relatório com evidências transacionais e handoff reproduzível.

## Objetivo end-to-end

Em uma sync alvo longa, o planner usa cobertura explícita da `Admission`, divide
lacunas pelo chunker canônico e executa um chunk por vez. Eventos, contadores e
coverage de um chunk são confirmados na mesma transação. Se o segundo falhar, o
primeiro permanece; retry não repete o primeiro chunk completo e processa só a
lacuna (salvo overlap canônico de borda). Chunk explicitamente vazio também
cobre. Evento preexistente sem ledger não cobre.

## Requisitos funcionais

- **R1 — Model enxuto:** `EvolutionExtractionCoverage` em `apps.ingestion` com
  FK `Admission`, `source_system`, bounds inclusivos `start_date`/`end_date`, FK
  anulável `completed_by_run` para `IngestionRun`, `event_count` não negativo e
  `completed_at`. Constraint única por admission/source/bounds; check constraint
  `end_date >= start_date`; índice adequado a consultas por admission/source e
  período.
- **R2 — Migration limpa:** criar migration nova a partir do último número, sem
  editar migrations antigas, sem backfill e sem dados reais.
- **R3 — Planner explícito alvo:** quando recebe Admission alvo, cobertura vem
  somente do ledger. Calcular união de dias/intervalos dentro do pedido,
  contiguous gaps e overlap existente. Um `ClinicalEvent` isolado não cobre.
  Sem alvo, preservar contrato legado para não ampliar S3.
- **R4 — Chunker único:** dividir cada gap alvo com
  `build_chunks_for_interval`; não copiar constantes/algoritmo. Mesma entrada
  gera mesmos chunks, máximo 15 dias e overlap existente.
- **R5 — Uma chamada por chunk:** no ramo alvo do worker, chamar adapter uma vez
  por chunk. O bridge S2 receberá uma janela de no máximo 15 dias e seu chunker
  canônico interno produzirá uma janela, sem algoritmo novo.
- **R6 — Atomicidade:** envolver `ingest_evolutions`, upsert da coverage e
  incremento cumulativo do run em `transaction.atomic()` externo por chunk.
  Falha em qualquer parte reverte todas as mudanças daquele chunk.
- **R7 — Commit incremental:** avançar somente após commit. Não usar
  `all_evolutions` no ramo alvo. Counters do run representam chunks já
  confirmados mesmo se run depois vira queued/failed.
- **R8 — Vazio confirmado:** resultado `[]` do caminho alvo S2 cria coverage com
  `event_count=0`; falha levantada não cria coverage.
- **R9 — Idempotência:** `update_or_create`/equivalente sob constraint; retry e
  overlap não duplicam coverage nem eventos. Contadores devem contar o trabalho
  da tentativa atual sem dupla soma do mesmo coverage já confirmado.
- **R10 — Retomada:** retry replana pelo ledger. Não repete o primeiro chunk
  completo já coberto; overlap de um dia pode reconsultar somente a borda.
- **R11 — Terminalidade preservada:** falha posterior chama política atual de
  retry/finalização, mantém admissions e chunks anteriores, não marca run como
  sucesso parcial.
- **R12 — Modo sem alvo:** não cria coverage admission-specific e preserva o
  fluxo acumulado atual.

## TDD obrigatório

### RED mínimo

Consolide os novos testes no arquivo permitido e prove:

1. model aceita coverage não vazia e vazia, relaciona run e rejeita
   bounds invertidos/duplicata lógica;
2. planner alvo com `ClinicalEvent` mas sem ledger retorna a data como gap;
3. coverage vazia explícita cobre o intervalo;
4. múltiplos registros sobrepostos/adjacentes formam união e full coverage;
5. mesma lacuna gera chunks canônicos determinísticos de no máximo 15 dias;
6. fake adapter em intervalo que produz pelo menos dois chunks: primeiro retorna
   eventos sintéticos, segundo lança timeout; após `_process_full_sync`, evento,
   coverage e counters do primeiro existem, segundo não, run está queued/failed
   conforme fixture;
7. retry do mesmo intervalo não chama novamente o primeiro chunk completo
   coberto; documente/assert o overlap de borda permitido;
8. primeiro chunk retorna `[]`: coverage zero é criada;
9. `ingest_evolutions` lança após mudança parcial ou coverage upsert é forçado a
   falhar: evento/counters/coverage do chunk são todos revertidos;
10. reprocessar bounds já confirmados não duplica coverage nem soma counters
    indevidamente;
11. run sem admission id não cria coverage e mantém compatibilidade.

Use apenas fixtures anônimas/sintéticas, sem Playwright real. Para provar
atomicidade, consulte o banco depois da exceção; não aceite mocks que apenas
asserem `transaction.atomic` chamado.

### GREEN

Implementar R1–R12 minimamente nos cinco arquivos permitidos.

### REFACTOR

- helper pequeno para commit de um chunk, se necessário;
- nenhum algoritmo duplicado de chunk/gap;
- query coverage limitada por admission/source/range;
- nenhuma generalização de status pending/failed, repository ou callback;
- preservar o ramo sem alvo e o retry lifecycle.

## Arquivos permitidos

Limite de **5 arquivos**, além de `tasks.md`:

1. `apps/ingestion/models.py`;
2. `apps/ingestion/migrations/<nova_migration_coverage>.py`;
3. `apps/ingestion/gap_planner.py`;
4. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`;
5. `tests/unit/test_incremental_evolution_coverage.py` (novo consolidado).

Não alterar `evolution_ingestion.py`, bridge/adapter/navigation, worker clássico,
admin, services, specs/design ou dependências. Se a migration precisar de um
arquivo adicional por conflito real, pare e reporte.

## Inspeções obrigatórias

```bash
rg -n "class EvolutionExtractionCoverage|UniqueConstraint|CheckConstraint|completed_by_run" \
  apps/ingestion/models.py apps/ingestion/migrations/
rg -n "ClinicalEvent|EvolutionExtractionCoverage|build_chunks_for_interval" \
  apps/ingestion/gap_planner.py \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "all_evolutions|transaction.atomic|ingest_evolutions|event_count" \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "first.*chunk|second.*chunk|empty|rollback|retry|without.*admission" \
  tests/unit/test_incremental_evolution_coverage.py
find apps/ingestion/migrations -maxdepth 1 -type f -name '*.py' | sort | tail -5
git diff --check
git diff --stat
```

Execute também, pelo caminho oficial disponível no projeto, o equivalente a:

```bash
./scripts/test-in-container.sh check
```

E registre se o Django check inclui migrations; se não incluir, rode
`docker compose ... python manage.py makemigrations --check --dry-run` seguindo
como `test-in-container.sh` invoca o serviço, sem inventar execução host-only
como gate.

Interprete: target planner não consulta eventos; ramo alvo não acumula tudo;
transação contém eventos+coverage+counters; somente uma migration nova; modo
legado ainda pode consultar `ClinicalEvent` em branch explícito.

## Critérios binários de aceite

- [ ] R1–R12 com RED/GREEN e prova DB real de rollback.
- [ ] Migration nova, sem backfill/edição histórica, `makemigrations --check`.
- [ ] Evento isolado não cobre target; vazio explícito cobre.
- [ ] Primeiro chunk permanece após falha do segundo.
- [ ] Retry pula primeiro chunk completo e mantém overlap canônico documentado.
- [ ] Persistência e coverage falham/commitam juntas.
- [ ] Idempotência evita coverage e counters duplicados.
- [ ] Sem alvo não cria coverage e mantém regressão verde.
- [ ] Máximo 5 arquivos + tasks; sem mudança de conector.
- [ ] Unit/integration/gates finais exit 0 e sem regressão de contagem.

### Condições automáticas de INCOMPLETO

S1/S2 não verificados; baseline/RED ausente; coverage inferida por evento no
modo alvo; coverage criada antes/fora do commit clínico; vazio de exception
marcado coberto; primeiro chunk perdido; retry repete range completo;
algoritmo chunk duplicado; migration antiga editada/backfill; model com estados
YAGNI; ramo sem alvo quebrado; mock sem prova DB de atomicidade; arquivo extra;
gate/markdown falho; relatório incompleto; task marcada sem evidência.

## Gates de autoavaliação

1. Qual consulta prova que o primeiro chunk sobrevive ao segundo?
2. Qual teste força cada lado da atomicidade (clinical e coverage)?
3. Por que `ClinicalEvent` não é evidência de coverage alvo?
4. Como idempotência impede dupla soma no retry/overlap?
5. Onde o chunker canônico é reutilizado sem cópia?
6. Como o modo sem admission id foi preservado?

## Validação mínima

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
```

Inclua subset RED/GREEN e check de migration com comandos/exit codes.

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-HTEFS-S3-report.md` com Status, BASE_REF, verificação
S1/S2, matriz, baselines unit/integration, RED/GREEN, estado DB após falhas,
snippets antes/depois **de cada arquivo** (migration nova: antes = ausente;
`tasks.md` incluído), inspections, migration check, gates, riscos e `Handoff
para verificador` com reruns/checklist R1–R12.

Se completo, marque somente 3.x, markdown lint novamente, commit/push e STOP.
Não inicie S4.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full harden-targeted-evolution-full-sync change and verified S1/S2 reports. Implement ONLY HTEFS-S3 exactly as its slice prompt. Require clean BASE_REF plus official unit and integration baselines. Write real DB RED tests first for the lean coverage model/migration, target planner ignoring ClinicalEvent without ledger, explicit empty coverage, interval union/canonical chunks, first chunk committed before second timeout, retry skipping the first complete chunk (only canonical boundary overlap allowed), idempotency, and rollback from both clinical-persistence and coverage failures. Then minimal GREEN: one new table, no backfill, explicit target planner and transaction per target chunk around ingest+coverage+counters; preserve no-admission legacy branch. Touch only the 5 listed files plus tasks.md. Run migration inspections/check, all official gates and markdown lint. Create /tmp/sirhosp-slice-HTEFS-S3-report.md with DB evidence, RED/GREEN, before/after per file and verifier reruns. Any missing item is INCOMPLETE without task mark/commit. If complete mark only 3.x, commit, push and STOP before S4.
```
