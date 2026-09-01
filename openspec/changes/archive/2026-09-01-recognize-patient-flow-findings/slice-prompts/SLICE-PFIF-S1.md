# PFIF-S1 — Fallback persistente de Atendimentos

## Handoff para implementador LLM com contexto zero

Leia integralmente, nesta ordem, antes de editar:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. `openspec/changes/recognize-patient-flow-findings/` inteiro, com foco em
   `design.md` D1–D4 e specs `patient-flow-findings`,
   `persistent-session-ingestion-worker` e `patient-admission-mirror`;
3. `apps/ingestion/extractors/legacy_navigation.py`, especialmente busca,
   `click_internacoes`, leitura de rows e erros sanitizados;
4. `apps/ingestion/extractors/real_handle_bridge.py`, cache de admissions,
   lifecycle boundaries e `_resolve_active_page`;
5. `apps/ingestion/extractors/persistent_extraction_adapter.py`, método
   `get_admission_snapshot` e controller cleanup;
6. `apps/ingestion/extractors/errors.py`, `run_lifecycle.py` e
   `ensure_nonempty_batch_admissions`;
7. `_process_admissions_only` no worker persistente e seus helpers de stages,
   attempts, follow-ups e batch closure;
8. testes de bridge, navigation, adapter e persistent worker para reutilizar
   fakes sintéticos; não copie fixtures reais.

Estado atual: lista vazia batch-bound sempre levanta
`EmptyAdmissionsSnapshotError`. O legado real tem um item visível
`Atendimentos`; spike read-only confirmou `frame_pol`, corpo
`#tabela_resultados\:resultList_data > tr`, quatro células com Data/Tipo/
Especialidade/Profissional e Data `DD/MM/AAAA`. O spike não é fixture e nenhum
artefato real pode entrar no repositório.

Objetivo exato: no caminho persistente, após admissions vazias batch-bound,
consultar uma vez a tabela de atendimentos. Hoje/ontem local conclui o run como
achado reconhecido, sem Admission/full-sync; qualquer outro resultado continua
fail-closed. Não implemente worker clássico, páginas ou métricas deste change.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Este slice será implementado por um modelo rápido. Siga literalmente. Se
qualquer item falhar, declare `Status: INCOMPLETE`, não marque `tasks.md`, não
faça commit/push e responda com bloqueio e evidência.

1. Antes de editar, registre no relatório `BASE_REF=$(git rev-parse HEAD)`,
   `git status --short` limpo e matriz `Requisito → arquivo(s) → teste(s)`.
2. Rode baseline oficial `./scripts/test-in-container.sh unit`; registre exit
   code, `passed`, `failed` e `errors`. Qualquer failure/error bloqueia.
3. Faça RED real primeiro: pelo menos um teste novo deve falhar porque fallback
   recente ainda termina em `invalid_payload`, e outro pelo contrato/parser
   ausente. Falha de import acidental não conta como RED funcional.
4. GREEN mínimo: somente os arquivos permitidos, sem antecipar S2–S5.
5. REFACTOR local: clean code, DRY, YAGNI, nomes claros, funções coesas,
   dependências direcionadas e nenhum estado morto.
6. Rode checks de inspeção e todos os gates oficiais deste arquivo.
7. Unit final deve ter exit 0, zero failures/errors e
   `passed_final >= passed_baseline`. Integration e quality gate devem ter exit
   zero.
8. Relatório deve conter evidência reproduzível, não opinião, e handoff para
   terceiro verificador.

## Objetivo vertical

Uma execução persistente sintética de `admissions_only` batch-bound com
internações vazias e atendimento de hoje/ontem termina `succeeded`, registra
stage allowlisted, mantém contadores clínicos zero, não cria Admission/full-sync
e permite drenagem do batch. A mesma execução com data limítrofe/antiga/ausente
continua no caminho de falha atual.

## Requisitos funcionais

### R1 — Contrato mínimo e puro

Criar value object imutável em módulo dedicado, com admissions normalizadas,
última data válida opcional e enum/faixa de recência. O cálculo recebe
`today` injetável, usa calendário local e classifica:

- hoje/ontem = `recent_confirmed`;
- anteontem = `boundary`;
- três ou mais dias = `stale`;
- sem válida = `none`.

Data futura nunca é recente. Não carregar nome, profissional, texto ou HTML.

### R2 — Parser estrutural do legado

Em `legacy_navigation.py`, adicionar helpers pequenos para clicar o item exato
visível `Atendimentos`, aguardar `frame_pol` bounded e ler rows de
`#tabela_resultados\:resultList_data > tr`. Exigir quatro células, parsear
somente a primeira como `DD/MM/AAAA`, ordenar deterministicamente e ignorar row
inválida. Erros devem ser tipados/sanitizados como os helpers existentes.

### R3 — Bridge job-scoped

O bridge deve oferecer ação de flow snapshot que primeiro captura admissions e,
apenas se vazias e solicitado, lê atendimentos na mesma sessão. Estado em
memória deve ser limpo em nova navegação, cleanup, falha, restart, bootstrap e
shutdown. Nenhum `page.content()` superior pode ser tratado como iframe.

### R4 — Adapter compatível

Adicionar método enriquecido que retorna o value object sem quebrar
`get_admission_snapshot()` nem fakes/stubs existentes. Readiness, renewal,
cleanup e `mark_job_processed` ocorrem uma vez por job. Não abrir nova URL,
browser, sessão ou subprocess.

### R5 — Reconhecimento recente no worker persistente

Somente `_process_admissions_only` com `run.batch_id` e admissions vazias pode
usar o fallback. Para `recent_confirmed`:

- run/attempt terminam succeeded;
- `admissions_seen/created/updated` e eventos ficam zero;
- não chamar `persist_admissions_snapshot` com lista vazia;
- não criar Patient/Admission/full-sync nem demografia adicional;
- registrar `admissions_capture` sem efeito clínico e stage
  `encounter_fallback` com details allowlisted, incluindo exatamente outcome e
  recency fechados, sem data;
- chamar batch closure canônico.

### R6 — Fail-closed preservado

Boundary/stale/none, navegação inválida e full-sync vazio continuam usando erro,
retry/cleanup/taxonomia existentes. Standalone vazio e admissions não vazias
não acionam fallback e preservam comportamento atual.

### R7 — Privacidade e lifecycle

Nenhum stdout/stderr/error/stage/report pode conter registro, nome, nascimento,
profissional, tipo/especialidade reais, data real, URL, seletor dinâmico, HTML,
cookie ou credencial. Testes devem usar sentinelas sintéticas e provar ausência.

## Arquivos esperados e limite

Máximo de **6 arquivos de código/teste**, além de `tasks.md`:

1. `apps/ingestion/extractors/patient_flow_snapshot.py` (novo);
2. `apps/ingestion/extractors/legacy_navigation.py`;
3. `apps/ingestion/extractors/real_handle_bridge.py`;
4. `apps/ingestion/extractors/persistent_extraction_adapter.py`;
5. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`;
6. `tests/unit/test_persistent_encounter_fallback.py` (novo consolidado).

Não editar worker clássico, `path2.py`, models, migrations, views, templates,
health, métricas, docs ou dependências. Se o contrato exigir sétimo arquivo,
pare e reporte bloqueio; não exceda silenciosamente.

## TDD obrigatório

### RED

Com fakes sintéticos, cobrir no arquivo novo:

1. quatro buckets de recência, bordas e data futura;
2. tabela confirmada com rows fora de ordem, inválida e data válida;
3. seletor/iframe/menu ausente e timeout sanitizado;
4. admissions não vazias não clicam `Atendimentos`;
5. standalone/full-sync não acionam fallback;
6. vazio+hoje/ontem produz run succeeded, counters zero, stage allowlisted, sem
   persist/follow-up e batch drenado;
7. vazio+boundary/stale/none mantém failure/retry/cleanup;
8. cleanup/restart/bootstrap elimina cache entre pacientes;
9. compatibilidade de `get_admission_snapshot` e job contado uma vez;
10. sentinelas sensíveis ausentes em output/stage/error.

Registre comando e pelo menos uma falha funcional esperada.

### GREEN

Implemente somente R1–R7, reutilizando erros/controller/lifecycle existentes.

### REFACTOR

Remova duplicação local, preserve APIs antigas como wrappers finos e mantenha
browser/domínio separados. Não generalize parser para outros menus, não crie
repository/model/status/feature flag.

## Checks de inspeção obrigatórios antes de concluir

```bash
rg -n "Atendimentos|tabela_resultados|resultList_data|frame_pol" \
  apps/ingestion/extractors/legacy_navigation.py \
  apps/ingestion/extractors/real_handle_bridge.py
rg -n "recent_confirmed|boundary|stale|none|future" \
  apps/ingestion/extractors/patient_flow_snapshot.py \
  tests/unit/test_persistent_encounter_fallback.py
rg -n "encounter_fallback|admissions_seen|persist_admissions_snapshot|enqueue_most_recent" \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "professional|profissional|nome|cookie|password|patient_record" \
  tests/unit/test_persistent_encounter_fallback.py \
  apps/ingestion/extractors/patient_flow_snapshot.py
git diff --check
git diff --stat
```

Interprete no relatório: confirme fallback somente após vazio batch-bound,
ordem antes de persist/follow-up, um cleanup/job, enum-only details e que
ocorrências de sentinelas existem apenas como dados sintéticos de teste com
asserção de ausência. Busca textual sozinha não prova privacidade.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate recognize-patient-flow-findings --strict
./scripts/markdown-lint.sh
```

Execução host-only não substitui gate oficial.

## Critérios binários de sucesso

- [ ] R1–R7 cobertos por RED/GREEN sintético.
- [ ] Hoje/ontem reconhece; anteontem e mais antigo não reconhecem.
- [ ] Run reconhecido tem counters zero e nenhum efeito clínico/follow-up.
- [ ] Não vazio, standalone e full-sync não usam fallback.
- [ ] Boundary/stale/none preservam fail-closed/retry/cleanup.
- [ ] Estado não cruza job/lifecycle.
- [ ] API antiga e testes existentes permanecem verdes.
- [ ] Nenhum dado real/segredo ou acesso de rede.
- [ ] Máximo de seis arquivos + tasks.
- [ ] Gates exit zero e unit final não regride contagem.

### Condições automáticas de INCOMPLETO

Marque incompleto se baseline/RED/gate não tiver evidência; algum teste real
acessar browser/rede/produção; data anteontem for aceita automaticamente;
profissional/row/HTML for persistido ou emitido; fallback ocorrer para não vazio,
standalone ou full-sync; `persist_admissions_snapshot([])` for chamado; surgir
Admission/full-sync/counter positivo; cache atravessar job; API antiga quebrar;
model/migration/status/dependência for criado; arquivo extra for tocado; teste
antigo for removido/enfraquecido; tasks forem marcadas antes dos gates; relatório
não existir no caminho exigido.

## Gates de autoavaliação

1. Qual teste prova que anteontem é ambíguo e não aceito?
2. Qual teste prova que o clique extra só ocorre após vazio batch-bound?
3. Onde se prova zero persistência e zero follow-up?
4. Como readiness/cleanup/job count continuam exatamente uma vez?
5. Qual teste prova limpeza entre dois pacientes?
6. Como details/logs permanecem allowlisted?
7. Por que cada arquivo alterado foi indispensável?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-PFIF-S1-report.md` com:

- `Status: COMPLETE|INCOMPLETE`;
- BASE_REF e árvore inicial;
- matriz requisito→arquivo→teste;
- baseline unit com exit/resumo explícito;
- RED com comando, falhas e motivo;
- GREEN/REFACTOR com comandos e resultados;
- snippets antes/depois de **cada** arquivo alterado (`antes=ausente` para
  novo arquivo);
- inspeções `rg` e interpretação;
- unit baseline versus final (`passed`, `failed=0`, `errors=0`, exit 0);
- todos os gates, OpenSpec e markdown lint;
- arquivos alterados e justificativa;
- riscos/pendências e respostas aos gates;
- comandos exatos para rerun;
- `Handoff para verificador` com checklist R1–R7 e o que inspecionar no diff.

Não incluir dados reais/sensíveis. Somente escrever `Status: COMPLETE` se todos
os critérios estiverem comprovados.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full recognize-patient-flow-findings change and SLICE-PFIF-S1.md. Implement ONLY PFIF-S1. Follow its DeepSeek4-Flash protocol: clean BASE_REF, official unit baseline, requirement matrix, real RED, minimal GREEN, local clean-code/DRY/YAGNI refactor, rg inspections, all official container gates, OpenSpec strict, markdown lint and baseline-vs-final evidence. Use only synthetic fixtures; never access legacy/production or save HTML/screenshots. Implement the persistent empty-admissions encounter fallback only: conservative date-only buckets, recent recognized outcome with counters zero/no persistence/no follow-up, and fail-closed otherwise. Touch at most the six listed files plus tasks.md; do not implement classic parity, classifiers, pages, health or metrics. Create /tmp/sirhosp-slice-PFIF-S1-report.md with before/after per file and Handoff para verificador. If any item is missing/failing, report INCOMPLETE and do not mark tasks or commit. If all pass, mark only tasks 1.1–1.5, commit, push, reply REPORT_PATH=..., then STOP.
```
