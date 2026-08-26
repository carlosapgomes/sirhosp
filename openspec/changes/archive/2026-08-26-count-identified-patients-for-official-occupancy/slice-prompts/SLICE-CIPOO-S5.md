# CIPOO-S5 — Dry-run e publicação futura v5

## Handoff com contexto zero

Leia integralmente `AGENTS.md`, `PROJECT_CONTEXT.md`, todo o change CIPOO,
relatórios S1–S4, runbook/release implantada, comando
`activate_sector_capacity_catalog.py`, serviço `capacity_catalog.py`, JSON v5 e
relatórios operacionais v4 anteriores. Produção deve estar na nova RC, saudável,
com v4 vigente e zero v5. Use somente pane tmux root autenticado e
`/srv/apps/prisma`.

Este slice requer **autorização explícita do operador para uma data local
futura concreta**. Sem mensagem explícita contendo a data, pare `INCOMPLETE` e
não execute nem dry-run operacional formal. Este slice publica catálogo, mas não
aguarda/executa primeiro censo v5.

## Protocolo obrigatório para implementador DeepSeek4-Flash

1. Registre autorização literal, BASE_REF, árvore e matriz requisito→evidência.
2. Rode baseline oficial unitário e OpenSpec strict antes da operação. Registre
   exit 0, zero failures/errors e contagem passed; qualquer falha bloqueia.
3. Trate preflight `v5_catalogs=0/v5_measurements=0` como RED operacional.
4. Dry-run deve provar zero escrita por snapshot agregado byte-idêntico.
5. Antes da publicação, revalide data estritamente futura, hash, backup, runtime
   e data vazia. Qualquer divergência para.
6. Publique uma vez e faça um retry exato somente para idempotência.
7. Prove catálogos anteriores byte-equivalentes, v4 ainda aplicável no dia
   corrente, v5 selecionável apenas na data futura e zero medição/backfill.
8. Sem primeiro censo, restart, migration, edição ou PHI.
9. Scripts temporários seguem clean code, DRY e YAGNI; não criar framework
   operacional novo.
10. Relatório; somente então task S5 e STOP.

## Objetivo vertical

Validar sem escrita e publicar explicitamente o catálogo v5 integral para a data
futura aprovada, preservando história e deixando v4 aplicável até a meia-noite
local.

## Requisitos operacionais

### R1 — Autorização e preflight

Registrar mensagem do operador com data. Confirmar:

- root/diretório, release/revision nova, DB/health/302/dez workers/migrations;
- data Django `America/Bahia` anterior à data aprovada;
- backup S4 modo/checksum válidos;
- hash do JSON v5 igual ao commit/release;
- v4 aplicável e hash conhecido;
- data futura vazia;
- v5 catalogs/groups/memberships/measurements zero;
- zero erro estrutural recente.

### R2 — Snapshot histórico privado

Calcular digest SHA-256 canônico sobre metadados completos de versões, grupos e
memberships anteriores, imprimindo somente digest, datas, schemas, algoritmos,
hashes e contagens. Nunca imprimir nomes de pacientes ou snapshots clínicos.

### R3 — Dry-run

Executar management command com `--dry-run` e serviço com `dry_run=True` para
observar `created=False`, algoritmo, hash, 43/48/47/39/4/666/666 e aliases
48/48. Snapshot determinístico de catálogo antes/depois deve ser literalmente
igual; data futura continua vazia.

### R4 — Publicação atômica/idempotente

Somente após R1–R3:

- executar comando sem `--dry-run` uma vez;
- exigir `publicado`, data/hash/algoritmo/totais;
- repetir exatamente e exigir `já publicado (idempotente)`;
- confirmar uma versão v5, 43 grupos, 48 memberships, aliases 48/48;
- nenhum partial row.

### R5 — Isolamento temporal

Digest dos catálogos anteriores idêntico. `_applicable_catalog` deve selecionar
v4 na data corrente e v5 na aprovada. V5 measurements=0, sem summary/backfill.
Runtime permanece saudável e dez workers.

## Arquivos e escopo

Nenhum arquivo rastreado deve mudar. Somente prompt/tasks ignorados e
`/tmp/sirhosp-slice-CIPOO-S5-report.md`. Não editar env/Compose/docs/código,
não migrar/restartar, não executar extração/processamento, não aguardar meia-noite
e não iniciar S6.

## TDD operacional

### RED

Preflight comprova `v5_catalogs=0`, `candidate_date=0` e `v5_measurements=0`.
Registrar snapshot e digest antes.

### GREEN

Dry-run mantém RED inalterado. Publicação autorizada muda somente catálogo para
uma versão integral. Retry não muda nada. Isso é a evidência operacional
RED→GREEN; nenhum teste artificial ou código é criado.

### REFACTOR

Não se aplica a código de aplicação. Aplicar clean code, DRY e YAGNI: scripts
temporários devem ser pequenos, fail-closed, removidos pelo wrapper e nunca usar
`exit` que encerre o shell root aninhado.

## Checks de inspeção obrigatórios

Local:

```bash
sha256sum apps/census/data/sector_capacity_catalog_v5.json
git status --short --branch
openspec validate count-identified-patients-for-official-occupancy --strict
./scripts/markdown-lint.sh
```

Produção, somente saída sanitizada:

```text
whoami/PWD
compose config --quiet
DB ready, health, 302, workers=10, revision
showmigrations alvo
local_today/effective_date
backup sha256sum -c
historical digest
v4 applicable; v5 zeros
management command --dry-run
service dry_run=True
snapshot equality
atomic publication + idempotent retry
v4 today/v5 future; v5 measurements=0
```

## Gates oficiais obrigatórios

Antes da operação:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate count-identified-patients-for-official-occupancy --strict
./scripts/markdown-lint.sh
```

Como nenhum código muda, compare a suíte unitária baseline/final e registre zero
failures/errors e `passed_final >= passed_baseline`; após a publicação, valide
estado local limpo e OpenSpec/Markdown ao marcar task.

## Critérios binários de sucesso

- [ ] Autorização explícita contém data futura exata.
- [ ] Release/runtime/backup/preflight verdes.
- [ ] Hash/totais/aliases exatos.
- [ ] Dry-run created=False e snapshot igual.
- [ ] Publicação criada uma vez e retry idempotente.
- [ ] Histórico anterior digest idêntico.
- [ ] V4 hoje, v5 apenas na data futura.
- [ ] Zero medição/backfill v5.
- [ ] Runtime saudável, sem restart/edits/PHI.
- [ ] S6 não executado.

### Condições automáticas de INCOMPLETO

- autorização sem data explícita;
- data atual/passada ou diferente da aprovada;
- release/hash/backup/runtime divergente;
- catálogo já existente inesperadamente;
- dry-run escreve ou snapshot difere;
- totais/aliases divergem;
- publicação parcial/não idempotente;
- histórico muda;
- medição v5 aparece;
- extração/restart/migration/env/Compose tocado;
- PHI/secret em output/report;
- marcador final ausente ou script temporário restante.

## Gates de autoavaliação

1. Onde está a autorização literal e qual data foi usada?
2. Qual snapshot prova zero escrita do dry-run?
3. Quais hash/totais/aliases foram observados?
4. Qual output diferencia criação e retry idempotente?
5. Qual digest prova preservação histórica?
6. Qual consulta prova v4 hoje/v5 futuro/zero measurements?
7. Que comandos mutantes foram explicitamente evitados?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CIPOO-S5-report.md` com status, autorização, release,
matriz R1–R5, RED/GREEN operacional, snippets/snapshots antes e depois,
baseline versus final, quality gate completo, comandos exatos de rerun,
preflight, backup, hash/totais, criação/idempotência, digest histórico, seleção
temporal, runtime, privacidade, riscos, scripts/cleanup e
`Handoff para verificador`. Não incluir identificadores clínicos.

## Prompt pronto para o implementador

```text
Read all CIPOO artifacts/reports, production runbook, catalog activation code
and SLICE-CIPOO-S5.md. Execute ONLY S5 after obtaining an explicit operator
message approving one exact future America/Bahia date. Follow the fail-closed
DeepSeek protocol. Run local official gates, preflight the deployed immutable
release, protected backup, v4 applicability and zero v5. Capture safe aggregate
snapshots/digests, run the exact v5 document with --dry-run and dry_run=True,
prove 43/48/47/39/4/666/666, aliases 48/48, created=False and byte-identical
state. Then publish once for the approved future date, retry exactly for
idempotency, prove prior catalogs unchanged, v4 today/v5 future and zero v5
measurements/backfill. Never edit/restart/migrate/extract, print secrets/PHI or
run S6. Any mismatch is INCOMPLETE. Create
/tmp/sirhosp-slice-CIPOO-S5-report.md, mark only S5 and STOP.
```
