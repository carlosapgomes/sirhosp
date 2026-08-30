# HTEFS-S2 — Seleção estrita da internação alvo

## Handoff para implementador LLM com contexto zero

Leia integralmente, nesta ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. este change completo, com foco em `design.md` D1,
   `specs/persistent-session-ingestion-worker/spec.md`,
   `specs/evolution-extraction-coverage/spec.md` e `tasks.md`;
3. relatório verificado de S1:
   `/tmp/sirhosp-slice-HTEFS-S1-report.md`; confirme no git que 1.x está
   concluído. Se não existir/não estiver verificado, pare;
4. `apps/patients/models.py`: `Patient` e `Admission` (campos de identidade,
   datas e relacionamento);
5. `apps/ingestion/extractors/legacy_navigation.py`:
   `choose_overlapping_admissions`, `open_internacao_detail` e o
   `click_evolucao` entregue por S1;
6. `apps/ingestion/extractors/real_handle_bridge.py`:
   `extract_evolutions_via_legacy_actions`, especialmente seleção, loops e
   branches que hoje convertem `NavigationError` em `continue`, `break` ou
   lista vazia;
7. `apps/ingestion/extractors/persistent_extraction_adapter.py`:
   `extract_evolutions` e dispatch action-first;
8. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`:
   `_process_full_sync`, resolução do paciente e parâmetros do run;
9. testes existentes de selector/bridge/adapter/worker para copiar padrões de
   fakes, nunca dados reais.

Estado atual: `admission_id` está no run, mas desaparece antes do adapter. O
bridge escolhe todas as admissões sobrepostas; `open_internacao_detail` ainda
pode cair na primeira linha quando a chave não resolve. A chave do legado é
volátil. A associação alvo deve usar início + estado/fim, com a chave somente
como desempate compatível.

## Protocolo obrigatório para DeepSeek4-Flash

Qualquer falha implica `Status: INCOMPLETE`, sem marcar tasks, commit ou push.

1. `BASE_REF=$(git rev-parse HEAD)`; exigir árvore limpa e S1 verificado.
2. Matriz `requisito → arquivo → teste` antes de editar.
3. Baseline oficial `./scripts/test-in-container.sh unit` com exit/resumo; falha
   bloqueia.
4. TDD real: testes primeiro, subset RED falhando por comportamento esperado.
5. GREEN mínimo e REFACTOR estritamente local; clean code, DRY, YAGNI.
6. Inspeções obrigatórias interpretadas.
7. Todos os gates oficiais + markdown lint, exit 0 e unit final >= baseline.
8. Relatório completo, reproduzível por terceiro LLM.

## Objetivo end-to-end

Uma `full_sync`/`full_admission_sync` com `admission_id` resolve a `Admission`
local pertencente ao paciente do run, propaga contexto mínimo em memória e
extrai somente a linha legada compatível. Chave legada alterada não impede um
match único por período/estado. Zero/ambiguidade ou falha em ação obrigatória do
alvo falha fechada e sanitizada; nunca abre primeira linha, outra admissão ou
retorna vazio funcional. Run sem `admission_id` preserva todas as sobrepostas.

## Requisitos funcionais

- **R1 — Resolução local:** o worker valida `admission_id` não vazio como PK de
  `Admission` do `patient` recém-persistido/resolvido. ID inválido, inexistente
  ou de outro paciente falha com `ValidationError` ou erro tipado sanitizado
  antes da extração de evolução.
- **R2 — Contexto mínimo:** propagar worker → adapter → action bridge somente
  início ISO, fim ISO/opcional, booleano ativo e `source_admission_key` como
  dica. Não persistir snapshot do legado nem criar model/field.
- **R3 — Seletor puro:** criar função pura com fixtures dict. Primeiro filtra
  overlap solicitado; exige início local compatível; ativa exige fim legado
  aberto, encerrada exige fim local compatível. Dica de chave apenas desempata
  candidatos já compatíveis.
- **R4 — Chave volátil:** exatamente um candidato por fatos estáveis vence
  mesmo com chave diferente. A chave nunca autoriza período/estado incompatível.
- **R5 — Ambiguidade fail-closed:** zero ou múltiplos candidatos após desempate
  levantam mensagem constante sanitizada; nada de primeiro/mais recente.
- **R6 — Detalhe estrito:** no modo alvo,
  `open_internacao_detail(..., strict=True)` (ou contrato equivalente) proíbe o
  fallback para primeira linha. Modo legado mantém comportamento atual.
- **R7 — Falha alvo não é vazio:** no caminho alvo, falha obrigatória em detalhe,
  ação, data, relatório, download ou parse propaga erro tipado. Somente diálogo
  explícito de sem evoluções retorna lista vazia.
- **R8 — Compatibilidade:** `target_admission=None` mantém
  `choose_overlapping_admissions` e todas as admissões sobrepostas; stubs do
  adapter continuam funcionando sem argumento novo obrigatório.
- **R9 — Sanitização:** nenhum log/erro contém admission id/key, prontuário,
  datas recebidas, URL, selector, HTML/PDF ou raw exception.

## TDD obrigatório

### RED mínimo

Em um único arquivo novo focado, prove antes do GREEN:

1. duas admissões sobrepostas: alvo local ativo com início exato é o único
   selecionado; fechada antiga não é aberta;
2. source key local stale + um match período/estado: match é aceito;
3. dois matches estáveis + um único hint compatível: hint desempata;
4. hint aponta para candidato com início/estado incompatível: não é aceito;
5. zero match e ambiguidade residual: erros constantes, sem sentinelas;
6. `open_internacao_detail` strict não tenta locator de primeira linha; modo
   default preserva fallback existente;
7. adapter passa contexto alvo ao método real e não muda dispatch stub;
8. worker com `admission_id` pertencente ao paciente passa contexto correto;
   admission de outro paciente falha antes de `extract_evolutions`;
9. bridge alvo chama detalhe somente para a chave atual selecionada e uma falha
   obrigatória não retorna `[]`;
10. sem `admission_id`/`target_admission`, duas sobrepostas continuam
    processáveis no modo legado.

Use datas e identificadores claramente sintéticos (`SYNTH-*`); não copie o caso
real da investigação. Não abra browser/rede.

### GREEN

Implementar R1–R9 com um selector puro e argumentos opcionais explícitos.

### REFACTOR

- uma única regra de seleção, sem copiá-la no worker/bridge;
- contexto target nomeado/tipado, não dict mágico espalhado;
- branch strict pequeno; fluxo legado intacto;
- nenhuma persistência de cobertura/chunk (S3), cooldown (S4) ou telemetry (S5).

## Arquivos permitidos

Limite de **5 arquivos**, além de `tasks.md`:

1. `apps/ingestion/extractors/legacy_navigation.py`;
2. `apps/ingestion/extractors/real_handle_bridge.py`;
3. `apps/ingestion/extractors/persistent_extraction_adapter.py`;
4. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`;
5. `tests/unit/test_targeted_evolution_admission.py` (novo e consolidado).

Proibido: models/migrations, `gap_planner.py`, worker clássico, services,
automação `path2.py`, specs/design, dependências. Se uma barreira técnica real
exigir sexto arquivo, pare e reporte; não exceda escopo.

## Inspeções obrigatórias

```bash
rg -n "admission_id|target_admission|strict" \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py \
  apps/ingestion/extractors/persistent_extraction_adapter.py \
  apps/ingestion/extractors/real_handle_bridge.py \
  apps/ingestion/extractors/legacy_navigation.py
rg -n "first visible|first row|choose_overlapping_admissions" \
  apps/ingestion/extractors/legacy_navigation.py \
  apps/ingestion/extractors/real_handle_bridge.py
rg -n "source_admission_key|admission_key" \
  apps/ingestion/extractors/legacy_navigation.py \
  apps/ingestion/extractors/real_handle_bridge.py
rg -n "SYNTH-|ambiguous|stale|strict" \
  tests/unit/test_targeted_evolution_admission.py
git diff --check
git diff --name-only "$BASE_REF"..HEAD 2>/dev/null || git diff --name-only
```

Interprete: contexto percorre as três fronteiras; chave é só hint no selector;
strict não alcança fallback; modo sem alvo ainda usa overlap; apenas arquivos
permitidos mudaram.

## Critérios binários de aceite

- [ ] R1–R9 cobertos por RED/GREEN.
- [ ] Alvo único por período/estado funciona com chave stale.
- [ ] Hint só desempata candidatos compatíveis.
- [ ] Zero/ambíguo e admission de outro paciente falham antes de extrair.
- [ ] Modo alvo nunca abre primeira linha nem converte ação falha em vazio.
- [ ] Vazio explícito continua sucesso vazio.
- [ ] Modo sem alvo preserva todas as sobrepostas e stub compatibility.
- [ ] Sentinelas não aparecem em output, erros ou métricas.
- [ ] Máximo 5 arquivos + `tasks.md`; sem model/migration.
- [ ] Gates exit 0; unit final >= baseline.

### Condições automáticas de INCOMPLETO

S1 não verificado; baseline/RED ausente; selector depende primariamente da chave;
hint aceita período incompatível; ambiguidade escolhe uma linha; strict ainda
faz fallback; target failure retorna vazio; dados reais; model/migration;
worker clássico alterado; arquivo extra; gate falho; relatório incompleto; tasks
marcadas sem evidência.

## Gates de autoavaliação

1. Qual teste prova chave volátil com match estável?
2. Qual prova que o hint não supera período/estado?
3. Qual prova que a linha antiga sobreposta nunca é aberta?
4. Qual prova que uma falha obrigatória do alvo não vira vazio/cobertura?
5. Qual prova o comportamento sem `admission_id`?
6. Por que os cinco arquivos são necessários e suficientes?

## Validação mínima

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
```

Inclua comando exato do subset RED/GREEN.

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-HTEFS-S2-report.md` com Status, BASE_REF, confirmação
de S1/verificador, matriz requisito→arquivo→teste, baseline, RED/GREEN, snippets
antes/depois **por todo arquivo alterado** (`tasks.md` incluído), inspeções
interpretadas, gates com exit/resumo, riscos e `Handoff para verificador` com
reruns e checklist R1–R9.

Se completo, marque somente 2.x, markdown lint novamente, commit/push e STOP.
Não inicie S3.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full harden-targeted-evolution-full-sync change and verified S1 report. Implement ONLY HTEFS-S2 exactly as slice-prompts/SLICE-HTEFS-S2.md. Require clean BASE_REF and official unit baseline. TDD real RED first in the one new consolidated test file: active target among overlaps, volatile key accepted by unique period/state, compatible hint tie-break only, incompatible hint rejected, zero/ambiguous fail closed, strict detail has no first-row fallback, worker→adapter→bridge propagation, target action failure never returns empty, and no-admission mode preserved. Then minimal GREEN/DRY refactor. Touch only the 5 allowed files plus tasks.md; no models/migrations/gap/cooldown/telemetry. Run rg inspections and all official gates + markdown lint. Write /tmp/sirhosp-slice-HTEFS-S2-report.md with baseline/RED/GREEN, before/after snippets per changed file and verifier rerun handoff. Any unmet item is INCOMPLETE without task mark/commit. If complete mark only 2.x, commit, push and STOP before S3.
```
