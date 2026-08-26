# CIPOO-S6 — Primeiro censo v5 e arquivamento

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md`;
2. todos os artefatos e relatórios CIPOO S1–S5;
3. change/relatórios `make-occupancy-quality-actionable`;
4. quatro specs canônicas e as deltas dos dois changes;
5. release/runbook implantados, ADR-0007 e comando OpenSpec archive;
6. modelos de measurement/group/summary/ingestion e `/beds`.

Entrada: release v5-capable saudável, catálogo v5 publicado para data futura,
zero medições v5 no final de S5. Aguarde o primeiro censo **completo, aceito e
materializado naturalmente** cuja data local usa v5. Não dispare, altere,
reprocesse ou feche runs manualmente. Não use v4 como fallback.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Qualquer falta de evidência, reconciliação aberta, UI divergente, fluxo clínico
falho, PHI em output/report, gate falho ou archive forçado torna `INCOMPLETE`.

1. Registre BASE_REF/árvore, matriz requisito→consulta/teste e baseline oficial
   com exit 0, zero failures/errors e contagem passed.
2. Preflight deve mostrar catálogo v5 aplicável e encontrar uma medição exact-run
   v5 completa; se ainda não existe, pare `INCOMPLETE/AGUARDANDO`, sem mutação.
3. Consultas de produção imprimem somente IDs técnicos, timestamps, algoritmos,
   hashes, contagens, booleanos e agregados allowlisted. Nunca nomes, records,
   leitos, idades ou HTML.
4. Prove todas as pontes aritméticas, summary e fluxo. Divergência não pode ser
   explicada verbalmente.
5. Valide `/beds` em memória/arquivo temporário 600, imprimindo somente status e
   booleans de labels; remova o arquivo. Nunca capture corpo no relatório.
6. Rode todos os gates e auditoria de consistência antes de arquivar.
7. Feche MOQA honestamente como história v4: não marque critérios sem evidência;
   registre o defeito operacional conhecido e sua substituição forward por v5.
8. Arquive MOQA primeiro para sincronizar v4; valide. Depois sincronize/archive
   CIPOO para deixar canônico final v5. Se OpenSpec bloquear ou diff divergir,
   pare; não use `--skip` para ocultar.
9. Sincronização/scripts seguem clean code, DRY e YAGNI; não criar ferramenta
   ou abstração operacional nova.
10. Commit/push somente artefatos/specs/archives, relatório completo e STOP.

## Objetivo vertical

Demonstrar que o primeiro censo v5 real conta pacientes identificados de forma
fechada e privada, apresenta a UI aprovada, preserva fluxo clínico e história,
e então tornar v5 o contrato canônico arquivando changes na ordem correta.

## Requisitos operacionais

### R1 — Exact-run v5

Selecionar primeira medição `occupancy-v5` por data/captured_at e confirmar:

- run aceito/succeeded e cobertura >=40;
- catálogo exato v5, schema/hash/data;
- snapshots do run e measurement one-to-one;
- known/calculable 666/666, 43 official/39 calculable;
- sem uso de medição anterior.

### R2 — Ponte de pacientes

A partir da reconciliação persistida e groups, sem consultar/imprimir PHI:

- schema v5 correto;
- `valid_identity_rows` fecha em duplicate within group + standard + unrated +
  pending + unmapped;
- official numerator = soma de group occupied_count standard;
- balance = soma `max(capacity - occupied,0)` standard;
- excess = soma `max(occupied - capacity,0)` standard;
- percentage corresponde numerator/666 com ROUND_HALF_UP;
- contadores incomplete, cross-group, name variants, RN/non-RN/age conflict,
  without-bed e estados são inteiros não negativos;
- unrated não recebe taxa/capacidade/saldo/excesso;
- nenhum indicador 3A total 48.

Se houver paciente sem leito, provar por agregados que ele pertence aos pacientes
contados, não à omissão. Se o contador for zero nesse censo, usar teste S1 como
evidência e registrar ausência observacional, sem fabricar caso.

### R3 — 3A e qualidade

Adulto/Infantil têm capacidades 32/16 e soma de suas atribuições é compatível
com contadores de classificação. Fallbacks incrementam warning agregado e não
exclusão. Toda medição v5 é elegível; historical exclusion counts permanecem
zero para v5.

### R4 — Resumo diário

Summary local usa catálogo/algoritmo v5, measurement_count correto,
eligible=total, warning_count conforme points, min/mean/max derivados somente de
v5 do dia e nenhuma data anterior reconstruída. Idempotência observada sem
executar materialização de novo.

### R5 — `/beds`

- anônimo 302;
- autenticado 200;
- exact measurement timestamp/catalog;
- um label/card de capacidade oficial; sem cards conhecidos/calculáveis v5;
- labels `Pacientes identificados`, `Saldo da capacidade oficial`,
  `Setores, pacientes e estados de leitos` e ponte nova presentes;
- termos v5 proibidos ausentes nas seções v5;
- estados operacionais e identificação incompleta têm blocos factuais;
- detalhes já autorizados renderizam em memória, sem output nominal;
- nenhum N+1/erro estrutural evidente.

### R6 — Fluxo clínico/runtime

Health, DB, dez workers, serviços/imagens/revision, filas agregadas, batches,
runs clínicos succeeded/failed e logs estruturais. O censo v5 não bloqueou
processamento clínico. Não considerar falha clínica existente como causada por
v5 sem correlação temporal/evidência.

### R7 — História e privacidade

- v1–v4 counts/hashes/digests anteriores inalterados;
- v4 measurements não recalculadas;
- nenhum backfill;
- scanner recursivo de reconciliation/history não encontra chaves/valores PHI;
- logs/relatórios/consultas sanitizados;
- screenshot real permanece fora do Git e deve ser removido quando não for mais
  necessário.

### R8 — Sincronização e arquivo

1. executar `openspec validate` strict nos changes;
2. usar checker de consistência specs↔código↔ADR↔reports;
3. completar MOQA apenas com evidência formal do primeiro v4 e nota de defeito
   substituído; nunca fingir ausência do defeito;
4. arquivar MOQA primeiro e validar specs canônicas v4;
5. aplicar/sincronizar as quatro deltas CIPOO e revisar diff final;
6. arquivar CIPOO com data corrente;
7. `openspec validate --specs --strict`/comando equivalente disponível;
8. Markdown lint, quality gate, git diff sem PHI/secret;
9. commit/push claro.

## Arquivos e limites

Nenhum arquivo de aplicação, migration, catálogo JSON, Compose ou release deve
mudar. Mudanças esperadas são somente:

- quatro specs canônicas;
- diretórios de archive dos changes;
- índices/metadados OpenSpec gerados legitimamente;
- tasks/prompts dentro dos changes;
- relatório `/tmp` não versionado.

Se código precisar correção, pare e abra slice corretivo; não implemente em S6.

## TDD operacional

### RED

Estado S5 tinha zero measurements v5. A pré-condição deste slice é observar a
primeira medição criada pelo fluxo normal. Se ainda zero, status
`INCOMPLETE/AGUARDANDO`.

### GREEN

Uma medição v5 exact-run existe e satisfaz todas as equações/consultas. UI e
summary refletem seus valores. Não criar dados para fazer GREEN.

### REFACTOR

Aplicar clean code, DRY e YAGNI somente à sincronização textual de specs,
preservando requisitos históricos e eliminando contradições finais. Não
reescrever specs não relacionadas.

## Checks de inspeção obrigatórios

Local:

```bash
openspec validate make-occupancy-quality-actionable --strict
openspec validate count-identified-patients-for-official-occupancy --strict
rg -n "occupancy-v5|identified patient|Pacientes identificados|Saldo da capacidade oficial|RN" \
  openspec/changes/count-identified-patients-for-official-occupancy \
  openspec/specs docs/adr/ADR-0007-*.md
rg -n "registro divergente|não autoritativo" \
  apps/census/templates/census/bed_status.html tests/unit/test_bed_status_view.py
rg -n "tmp/beds-v4.png|prontuario|nome do paciente" . --glob '!tmp/**'
git diff --check
git status --short
```

Produção deve emitir somente objeto agregado/booleans e marcador final. Validar
que qualquer arquivo HTML temporário tem mode 600 e é removido.

## Gates oficiais obrigatórios

Antes e depois da sincronização/arquivo:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
./scripts/markdown-format.sh
./scripts/markdown-lint.sh
```

Validar todos os changes/specs com os comandos suportados pela versão OpenSpec
instalada. Autofix Markdown exige revisão do diff.

## Critérios binários de sucesso

- [ ] Primeira medição v5 real/exact-run, sem trigger manual.
- [ ] Ponte, numerator, balance, excess e rate fecham.
- [ ] 3A/fallback/quality/summary coerentes.
- [ ] `/beds` 302/200 e contratos v5 por booleans seguros.
- [ ] Fluxo clínico/runtime saudáveis.
- [ ] História/privacidade/backfill preservados.
- [ ] MOQA encerrado honestamente e arquivado primeiro.
- [ ] Quatro specs finais refletem v5 e ambos changes arquivados.
- [ ] Todos os gates/Markdown/OpenSpec verdes.
- [ ] Commit/push sem app/PHI/secret.

### Condições automáticas de INCOMPLETO

- nenhuma medição v5 completa ainda;
- uso de latest v4/older fallback;
- consulta/output/report com PHI;
- qualquer equação não fecha;
- summary ineligible ou história alterada;
- UI label/status/auth diverge;
- fluxo/runtime falha sem tratamento;
- dado/run mutado manualmente;
- MOQA marcado/arquivado com critério falso;
- archive fora de ordem, warning ignorado ou spec final contraditória;
- código/app/catalog/release editado;
- qualquer gate falho ou relatório ausente.

## Gates de autoavaliação

1. Qual run/measurement/catalog técnico prova exact-run v5?
2. Mostre cada equação somente com agregados.
3. Como fallback/without-bed/cross-group afetam warning mas não elegibilidade?
4. Quais booleans comprovam UI sem expor o corpo?
5. Quais contagens comprovam fluxo clínico e dez workers?
6. Quais digests provam história e ausência de backfill?
7. Como o defeito v4 foi documentado sem falsificar closure?
8. Qual ordem/comandos/diffs provaram sincronização e archive?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CIPOO-S6-report.md` com:

- status COMPLETE/INCOMPLETE/AGUARDANDO;
- BASE_REF e matriz;
- identificação técnica exact-run sem PHI;
- equações completas;
- summary/quality/3A;
- UI status/booleans e cleanup;
- fluxo/runtime/logs;
- história/digests/privacidade;
- RED/GREEN operacional e baseline versus final;
- quality gate completo e comandos exatos de rerun;
- gates antes/depois;
- closure MOQA e ordem de archive;
- specs antes/depois por snippets;
- arquivos alterados, diff, commits/push;
- riscos e `Handoff para verificador` R1–R8 com rerun sanitizado.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, all CIPOO and MOQA artifacts/reports,
canonical specs, ADR-0007, deployed release evidence and SLICE-CIPOO-S6.md.
Execute ONLY S6. Wait for the first naturally accepted exact-run occupancy-v5
measurement; if absent report INCOMPLETE/WAITING and mutate nothing. Use only
safe aggregate production queries and in-memory boolean UI checks—never print
or report names, records, beds, exact ages or HTML. Prove the patient bridge,
standard/unrated partition, group sums, 666 rate, non-compensated balance/excess,
3A fallback counters, quality eligibility, daily summary, 302/200 v5 labels,
clinical flow, ten workers, history digests and no backfill. Run all official
gates. Close MOQA honestly with formal historical v4 evidence and known-defect
supersession, archive MOQA first, then sync/archive the four CIPOO specs so final
canonical contracts are v5. Never force archive, edit application/catalog/
release or fabricate data. Any mismatch is INCOMPLETE. Create
/tmp/sirhosp-slice-CIPOO-S6-report.md with full evidence and verifier handoff,
commit/push artifacts only, then STOP.
```
