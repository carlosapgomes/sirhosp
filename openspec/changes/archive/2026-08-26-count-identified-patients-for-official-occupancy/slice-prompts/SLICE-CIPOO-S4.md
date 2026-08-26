# CIPOO-S4 — Auditoria, release e deploy sem ativação

## Handoff com contexto zero

Este é um slice operacional de alto impacto. Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md`;
2. todos os artefatos deste change e relatórios S1–S3;
3. commits/diffs S1–S3, ADR-0007 e migrations novas;
4. change ativo `make-occupancy-quality-actionable` e relatórios RC10;
5. `deploy/README.md`, `deploy/systemd/`, `compose.hospital.yml`;
6. `docs/releases/README.md` e runbooks RC9/RC10;
7. `.github/workflows/publish-release-image.yml`;
8. testes de release/deploy e guard contra LLM externo.

Entrada esperada: três slices de código commitados/pushed, árvore limpa, produção
RC10/v4. Saída: próxima RC imutável implantada com suporte v5 dormente,
migrations aplicadas, backup protegido e **zero catálogo/medição v5**. Este
slice nunca executa dry-run nem ativação de catálogo.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Qualquer falha, HTTP 429, gate não executado, output truncado sem marcador,
divergência de hash/revision, backup inválido ou v5 presente torna o slice
`INCOMPLETE`. Não aceite exceção verbal.

1. Registre BASE_REF, origin/master, árvore e matriz requisito→evidência.
2. Audite artefatos antes de editar. Achado que exige código retorna ao slice
   responsável; não faça hotfix oportunista.
3. Rode baseline/gates oficiais completos antes de tag e registre exit 0, zero
   failures/errors e contagem passed. Integração deve ter zero chamada LLM
   externa; 429 bloqueia.
4. Crie runbook por TDD usando testes de release existentes quando aplicável.
5. Commit/push docs antes da tag; a tag deve apontar ao commit exato auditado.
6. Workflow oficial deve criar release/assets/imagem imutáveis. Verifique SHA,
   digest e OCI revision.
7. Produção somente por pane tmux autenticado root no `eon`, em
   `/srv/apps/prisma`, com scripts fail-closed, marcadores, cleanup e saída
   sanitizada. Nunca imprimir `.env` ou Compose interpolado.
8. Drene fila sem mutação manual, faça backup, deploy/migrate, restaure topologia
   e prove v4 vigente/v5 zero.
9. Relatório completo; somente então task S4. Não executar S5.

## Objetivo vertical

Publicar e implantar release imutável v5-capable, preferencialmente
`v0.1.0-rc.11`, sem alterar algoritmo vigente. A operação termina com RC nova
saudável e catálogo v4 ainda aplicável.

## Requisitos funcionais/operacionais

### R1 — Auditoria final

- proposal/design/tasks/quatro specs coerentes;
- relatórios S1–S3 `COMPLETE`, limites e RED/GREEN verificáveis;
- migration aditiva, sem backfill/RunPython;
- catálogo v5/hash/totais corretos e anteriores preservados;
- ADR-0007/index coerentes;
- privacidade, exact-run, autenticação e fluxo clínico cobertos;
- zero credencial/PHI no diff.

### R2 — Gates binários

Executar check, unit, integration, lint, typecheck, quality-gate, OpenSpec strict
e Markdown lint no commit a publicar. Registrar passed/failed/errors e exit.
Final passed >= baseline. Nenhuma rede LLM real.

### R3 — Runbook/release

Runbook da RC nova deve conter:

- cadeia de commits e escopo v5 dormente;
- tag/assets/imagem/digest/revision/hash;
- preflight v4 e zero v5;
- drenagem, backup, migration, deploy, health, 302 e dez workers;
- prova de ausência de ativação;
- rollback funcional somente antes da vigência v5 e correção forward depois;
- nenhuma credencial/comando destrutivo.

Publicar tag somente se inexistente e apontando para HEAD/origin. Workflow
oficial success; release prerelease immutable; assets exatos; imagem GHCR por
tag exata e OCI revision igual ao commit.

### R4 — Preflight produção

Confirmar somente agregados/metadados:

- root, diretório, Docker rootful e Compose válido;
- `.env` modo 600 sem conteúdo;
- RC10 saudável, DB ready, `/health`, `/beds` anônimo 302;
- dez `persistent_worker`, serviços e rede externa preservados;
- migrations atuais;
- catálogo aplicável `occupancy-v4` e seu hash/data;
- `v5_catalogs=0`, `v5_measurements=0`;
- fila/status agregados sem PHI.

### R5 — Drenagem e backup

Bloquear novas entradas conforme runbook, manter workers para drenar e aguardar
queued/running/batches/summaries/pipelines zero. Não alterar status de run.
Parar mutantes somente na ordem segura. Criar dump custom em
`/srv/apps/prisma/backups`, diretório 700, dump/checksum 600, tamanho >0 e
`sha256sum -c` antes/depois. Não copiar backup.

### R6 — Deploy sem catálogo

- preservar Compose RC10 como rollback;
- alterar silenciosamente somente versão aprovada;
- pull por tag exata, `config --quiet`, migrations;
- segunda migrate idempotente;
- subir web, dez workers, summary worker e orquestrador;
- health OK, 302, DB ready, imagem/revision exatas, zero Traceback/CRITICAL;
- catálogo v4 idêntico e v5 0/0 antes/depois;
- não executar comando de catálogo nem com `--dry-run`.

## Arquivos esperados e limite

No repositório, máximo **3 arquivos rastreados**:

1. `docs/releases/v0.1.0-rc.11-upgrade.md` ou versão realmente aprovada;
2. `docs/releases/README.md`;
3. opcionalmente teste de runbook/release existente, somente via TDD.

Não editar aplicação, migration, catálogo, ADR, Compose ou workflow neste slice.
Achado nesses arquivos bloqueia e retorna ao slice anterior. Relatório `/tmp` e
tasks ignoradas não contam.

## TDD e auditoria

### RED

Se runbook é novo, adicionar/ajustar teste documental antes dele e provar failure
por ausência da RC/contrato. Se os testes existentes já cobrem integralmente,
registre inspeção RED justificando por que nenhum teste novo é necessário; não
fabrique alteração de código.

### GREEN

Runbook mínimo satisfaz contratos. Não alterar workflow maduro sem requisito.

### REFACTOR

Aplicar clean code, DRY e YAGNI aos scripts/runbook novos. Remover duplicação
documental apenas se não ampliar escopo. Não reformatar runbooks antigos.

## Checks de inspeção obrigatórios

```bash
git status --short --branch
git log --oneline --decorate -12
rg -n "occupancy-v5|0024|sem ativ|dry-run|backup|sha256|10|302|forward" \
  docs/releases/v0.1.0-rc.11-upgrade.md
rg -n "OpenAI|AsyncOpenAI|call_llm_gateway" tests/conftest.py \
  tests/integration/test_summary_worker_lifecycle.py
rg -n "RunPython|backfill" apps/census/migrations/0024_*.py
sha256sum apps/census/data/sector_capacity_catalog_v*.json
```

Após publicação:

```bash
git rev-list -n 1 v0.1.0-rc.11
gh run view <RUN_ID> --json status,conclusion,headSha,url
gh api repos/carlosapgomes/sirhosp/releases/tags/v0.1.0-rc.11 \
  --jq '{tag_name,draft,prerelease,immutable,assets:[.assets[].name]}'
docker buildx imagetools inspect ghcr.io/carlosapgomes/sirhosp:v0.1.0-rc.11
```

Adapte versão somente se o preflight provar outra próxima tag aprovada.

## Gates oficiais obrigatórios

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

## Critérios binários de sucesso

- [ ] S1–S3 auditados e coerentes.
- [ ] Todos os gates verdes, sem 429/rede real.
- [ ] Docs commitados/pushed antes da tag.
- [ ] Tag/release/assets/imagem imutáveis e revision exata.
- [ ] Preflight v4/v5=0.
- [ ] Fila drenada sem mutação manual.
- [ ] Backup protegido/checksum válido.
- [ ] Migrations e runtime saudáveis, dez workers.
- [ ] V4 idêntico e v5 catalogs/measurements zero depois.
- [ ] Nenhum dry-run/publicação v5.

### Condições automáticas de INCOMPLETO

- qualquer gate/teste/HTTP externo falha;
- tag/release/imagem preexistente divergente;
- asset/hash/digest/revision não verificável;
- fila mutada ou não drenada;
- backup ausente, público ou checksum falho;
- serviço fora, worker !=10, health/302/log falho;
- catálogo v5 criado ou medição v5 existente;
- comando de ativação executado;
- segredo/PHI/output de `.env`;
- código corrigido dentro do slice;
- relatório sem marcadores/evidência.

## Gates de autoavaliação

1. Qual commit exato foi tagueado e como origin/tag/revision coincidem?
2. Quais gates e contagens comprovam release-ready sem LLM externo?
3. Qual snapshot agregado prova v4 vigente e v5 zero antes/depois?
4. Como drenagem foi feita sem mutar runs?
5. Caminho/tamanho/modo/SHA do backup?
6. Quais containers provam dez workers e imagem exata?
7. Qual comando proibido não foi executado?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CIPOO-S4-report.md` com status, BASE_REF/release commit,
matriz R1–R6, auditoria, RED/GREEN documental, snippets antes/depois, baseline
versus final, quality gate completo, comandos exatos de rerun, release URL/run,
assets/hashes/digest/revision, pre/post produção sanitizado, drenagem, backup,
migrations, health/workers/logs, prova v4/v5 zero, riscos, rollback e
`Handoff para verificador`. Nunca incluir PHI ou secrets.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the complete CIPOO change and reports S1-S3,
deploy/runbook/workflow docs, RC10 evidence and SLICE-CIPOO-S4.md. Execute ONLY
S4 under its DeepSeek4-Flash fail-closed protocol. Audit first; do not patch
application findings. Run every official container gate and integration with
zero failures/errors/429. Create and test the next RC runbook, commit/push docs,
then publish the exact immutable tag/release/image through the official
workflow. In authenticated root tmux production, use sanitized marked scripts,
drain without manual mutations, create protected SHA-verified backup, deploy
and migrate, restore exactly ten workers, verify health/302/images/revision/logs,
and prove occupancy-v4 remains applicable with v5 catalogs=0 and measurements=0.
Never run catalog activation or dry-run, print env/secrets/PHI, build locally or
edit outside /srv/apps/prisma. Any missing/failing evidence is INCOMPLETE. Create
/tmp/sirhosp-slice-CIPOO-S4-report.md with full verifier handoff. Mark only S4
and STOP; S5 requires separate explicit date authorization.
```
