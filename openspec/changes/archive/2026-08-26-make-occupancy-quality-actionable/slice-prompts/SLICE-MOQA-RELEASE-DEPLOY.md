# MOQA-RELEASE-DEPLOY — Release imutável e deploy sem ativação v4

## Handoff para executor com contexto zero

Execute somente a task 4.4 do change `make-occupancy-quality-actionable`.
Leia integralmente `AGENTS.md`, `PROJECT_CONTEXT.md`, todos os artefatos do
change, o relatório `/tmp/sirhosp-slice-MOQA-FINAL-AUDIT-report.md`,
`deploy/README.md`, `docs/releases/README.md`, o runbook RC9, o runbook da nova
release, o workflow `publish-release-image.yml` e `compose.hospital.yml`.

Estado esperado:

- tasks 1.1–4.3 concluídas e auditoria COMPLETE;
- branch `master` limpa e sincronizada;
- produção em `v0.1.0-rc.9` no diretório `/srv/apps/prisma`;
- acesso já autenticado ao `eon` pelo pane tmux da janela 9;
- dez réplicas de `persistent_worker`;
- catálogo v3 vigente e nenhum catálogo/measurement v4;
- próxima candidata: `v0.1.0-rc.10`.

## Protocolo obrigatório

1. Registre `BASE_REF`, árvore e tag/release/image inexistentes.
2. Crie runbook específico e índice antes da tag.
3. Execute gates oficiais antes do commit/tag.
4. Commit/push dos documentos; tag exata nesse commit.
5. Publique somente pelo workflow oficial e aguarde `success`.
6. Confirme release imutável, assets, hashes, imagem e revisão OCI.
7. No servidor, nunca imprima `.env` nem Compose interpolado.
8. Drene filas por contagens agregadas; não altere/requeue runs.
9. Crie backup custom, checksum e modos protegidos antes da migration.
10. Preserve Compose RC9, aplique 0022/0023, suba RC10 e restaure dez workers.
11. Compare metadados agregados de catálogo/measurement antes e depois; v4 deve
    permanecer ausente. Não executar comando de ativação nem `--dry-run`.
12. Gere relatório sanitizado, marque somente 4.4, commit/push se houver artefato
    rastreado pendente e pare.

Qualquer falha torna o slice **INCOMPLETO**. Não avance para ativação.

## Requisitos

### R1 — Release rastreável

- Tag nova e exata `v0.1.0-rc.10`.
- Tag aponta para commit contendo código S1–S3, ADR-0006 e runbook RC10.
- Workflow oficial executa quality gate e publica imagem linux/amd64.
- Release `draft=false`, `prerelease=true`, `immutable=true`.
- Assets: Compose e runbook da mesma tag.
- Imagem exata informa revisão igual ao commit da tag.

### R2 — Segurança operacional

- Alterar somente `/srv/apps/prisma`, containers e banco da aplicação.
- Não alterar host, rede, Cloudflared, systemd ou outras aplicações.
- Não expor secrets ou PHI.
- Não usar `down -v`, checkout, pull de Git ou build local no servidor.
- Preservar portal em `127.0.0.1:8001` e dez workers.

### R3 — Drenagem e backup

- Preflight verde: Compose quiet, DB ready, health 200, dez workers.
- Parar novas entradas e drenar queued/running por agregados.
- Parar mutadores antes do dump.
- Backup custom não vazio sob `/srv/apps/prisma/backups/`.
- Diretório modo 700; dump/checksum modo 600; SHA-256 validado.

### R4 — Deploy imutável

- Baixar assets da release e validar hash esperado do Compose.
- Preservar `compose.hospital.yml.rc9`.
- Atualizar somente `SIRHOSP_VERSION` no `.env`, sem imprimi-lo.
- Pull da tag exata; migrations 0022/0023 em one-shot; `No migrations to apply`
  em verificação repetida.
- Subir web, workers, summary worker e orquestrador; health 200; `/beds` anônimo
  302; logs estruturais sem `Traceback`/`CRITICAL` recente.

### R5 — Nenhuma ativação v4

Antes e depois, registrar somente:

- data/schema/algoritmo/hash do catálogo mais recente;
- contagem de catálogos `occupancy-v4`;
- contagem de medições `occupancy-v4`.

Os valores pós-deploy devem permanecer v3/zero/zero. Não executar
`activate_sector_capacity_catalog`, nem com `--dry-run`.

## Escopo e arquivos

Arquivos rastreados permitidos antes da release:

1. `docs/releases/v0.1.0-rc.10-upgrade.md`;
2. `docs/releases/README.md`.

O prompt e `tasks.md` estão no change ignorado. Não alterar aplicação,
migrations, tests, Compose ou workflow. Se precisar, pare como INCOMPLETO.

## Validação obrigatória

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate make-occupancy-quality-actionable --strict
./scripts/markdown-lint.sh
```

Todos exigem exit 0. Falha ambiental não é verde.

## Inspeções obrigatórias

```bash
git status --short --branch
git log -8 --oneline --decorate
git tag --list v0.1.0-rc.10
gh release view v0.1.0-rc.10
docker buildx imagetools inspect ghcr.io/carlosapgomes/sirhosp:v0.1.0-rc.10
sha256sum compose.hospital.yml docs/releases/v0.1.0-rc.10-upgrade.md
rg -n "rc.10|0022|0023|sem ativação|occupancy-v3|occupancy-v4|10" \
  docs/releases/v0.1.0-rc.10-upgrade.md docs/releases/README.md
rg -n "activate_sector_capacity_catalog|--dry-run" \
  docs/releases/v0.1.0-rc.10-upgrade.md
```

Ocorrências do comando de ativação só podem existir como proibição explícita.

## Critérios binários

- [ ] Auditoria final COMPLETE e 20/25 tasks no início.
- [ ] Runbook/índice válidos e gates verdes.
- [ ] Tag/release/image não existiam antes.
- [ ] Workflow oficial terminou success.
- [ ] Release imutável e imagem da revisão exata.
- [ ] Preflight e drenagem por agregados verdes.
- [ ] Backup protegido e checksum válido.
- [ ] Migrations 0022/0023 aplicadas.
- [ ] RC10 saudável com dez workers e `/beds` 302 anônimo.
- [ ] Catálogo permaneceu v3 e contagens v4 ficaram zero.
- [ ] Nenhum dry-run/ativação v4 ocorreu.
- [ ] Relatório sanitizado criado e somente 4.4 marcada.

### Condições automáticas de INCOMPLETO

- qualquer gate/comando obrigatório falhar;
- tag, release ou imagem já existir no preflight;
- workflow não terminar success/immutable;
- asset, digest ou revisão divergir;
- fila não drenar ou DB/health falhar;
- backup vazio, checksum/modo incorreto;
- menos/diferente de dez workers ao final;
- catálogo/measurement v4 existir ou mudar durante deploy;
- comando de ativação/dry-run ser executado;
- secret/PHI aparecer em saída/relatório;
- arquivo fora do escopo ser alterado;
- task posterior ser marcada.

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-MOQA-4.4-report.md` com status, referências, matriz
R1–R5, arquivos e snippets antes/depois, gates, workflow/release/assets/imagem,
preflight, drenagem agregada, backup (caminho/tamanho/modo/hash), migration,
health/workers/logs, metadados antes/depois sem PHI, confirmação de nenhuma
ativação, rollback, riscos e `Handoff para verificador`.

Se COMPLETE, marque somente task 4.4, responda
`REPORT_PATH=/tmp/sirhosp-slice-MOQA-4.4-report.md` e pare.

## Prompt pronto

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the complete MOQA change, final audit,
deploy docs, RC9/RC10 runbooks, workflow and Compose. Execute ONLY task 4.4:
publish immutable v0.1.0-rc.10 and deploy it to eon from the authenticated tmux
window 9. Do not run dry-run or activate v4. Preserve 10 workers and portal
127.0.0.1:8001. Never print .env, interpolated Compose, PHI or credentials.

Run every official gate. Create/push runbook docs, exact tag and official
workflow; require immutable release, exact assets and OCI revision. Drain using
aggregates, backup with SHA-256/modes, apply 0022/0023 and validate health,
workers and v3/zero-v4 before/after. Any failure means INCOMPLETE and STOP.
Create /tmp/sirhosp-slice-MOQA-4.4-report.md, mark only 4.4 and STOP.
```
