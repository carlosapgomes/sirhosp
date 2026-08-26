# IBPU-S4 — Release RC12 e deploy de produção

## Handoff com contexto zero

Este é um slice operacional de alto impacto. Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md`;
2. todos os artefatos do change `improve-beds-v5-page-ux` e os relatórios
   `/tmp/sirhosp-slice-IBPU-S1..S3-report.md`;
3. commits/diffs S1–S3;
4. `deploy/README.md`, `compose.hospital.yml`,
   `.github/workflows/publish-release-image.yml`;
5. `docs/releases/README.md` e os runbooks `v0.1.0-rc.10-upgrade.md` e
   `v0.1.0-rc.11-upgrade.md`;
6. `tests/unit/test_release_hospital_deploy.py` (em especial
   `NEXT_RELEASE` e `test_next_release_runbook_declares_dormant_v5_contract`);
7. `openspec/specs/release-image-hospital-deploy/spec.md`.

Entrada esperada: S1–S3 commitados/pushed, árvore limpa, produção rodando
`v0.1.0-rc.11` com `occupancy-v5` vigente desde 2026-08-26 (medições v5
sendo criadas naturalmente). Saída: release imutável `v0.1.0-rc.12`
(somente UI) publicada pelo workflow oficial e implantada em produção
saudável, com backup protegido e RC11 preservada como rollback.

Diferenças cruciais para releases anteriores: **nenhuma migration nova**
(confirme com `git log v0.1.0-rc.11..HEAD -- 'apps/*/migrations'` vazio),
**nenhum catálogo novo** (5 versões existentes, hashes preservados),
**nenhum comando de ativação ou dry-run** — o v5 já é vigente e as medições
continuem sendo criadas pelo fluxo natural. Este slice nunca interrompe o
fluxo clínico além da janela de deploy documentada.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Qualquer falha, HTTP 429, gate não executado, output truncado sem marcador,
divergência de hash/revision/digest, backup inválido ou serviço fora torna o
slice `INCOMPLETE`. Não aceite exceção verbal.

1. Registre `BASE_REF=$(git rev-parse HEAD)`, origin/master, árvore e matriz
   requisito→evidência.
2. Audite S1–S3 antes de editar. Achado que exige código retorna ao slice
   responsável; não faça hotfix oportunista.
3. Rode baseline/gates oficiais completos antes da tag e registre exit 0,
   zero failures/errors e contagem passed. Integração com zero chamada LLM
   externa; 429 bloqueia.
4. Crie o runbook por TDD: primeiro o teste documental da RC12, depois o
   runbook que o satisfaz.
5. Commit/push docs antes da tag; a tag deve apontar ao commit exato
   auditado.
6. Workflow oficial deve criar release/assets/imagem imutáveis. Verifique
   SHA, digest e OCI revision.
7. Produção somente por pane tmux autenticado root no `eon`, em
   `/srv/apps/prisma`, com scripts fail-closed (heredoc com marcadores
   BEGIN/END, trap imprimindo `RC=`, cleanup de buffers, `docker compose
   exec -T ... < /dev/null`). Nunca imprimir `.env` ou Compose interpolado.
   Confirme que o pane está livre antes de enviar; reenvie script idêntico
   se um envio não executar, antes de qualquer escrita.
8. Drene a fila sem mutação manual de status, crie backup protegido com
   SHA-256 em `/srv/apps/prisma/backups/`, faça o deploy, restaure a
   topologia e valide somente por agregados.
9. Relatório completo; somente então task 4.x. Não execute nenhum comando de
   catálogo.

## Objetivo vertical

Publicar e implantar `v0.1.0-rc.12` com as melhorias de UX de S1–S3, sem
mudança de schema nem de dados, mantendo o fluxo clínico e as medições v5
intactas, e validando a página nova por agregados.

## Requisitos funcionais/operacionais

### R1 — Auditoria final

- proposal/design/tasks/delta spec coerentes com o implementado;
- relatórios S1–S3 `COMPLETE`, com RED/GREEN e gates verificáveis;
- zero migrations novas no intervalo `v0.1.0-rc.11..HEAD`;
- catálogos inalterados (SHA-256 das 5 versões conferido);
- privacidade, exact-run, autenticação e regressão v1–v4 cobertos;
- zero credencial/PHI no diff e nos relatórios.

### R2 — Gates binários

Executar check, unit, integration, lint, typecheck, quality-gate, OpenSpec
strict e Markdown lint no commit a publicar. Registrar passed/failed/errors
e exit. Final passed >= baseline. Nenhuma rede LLM real.

### R3 — Runbook e teste documental RC12

Atualizar por TDD `tests/unit/test_release_hospital_deploy.py`:
`NEXT_RELEASE = "v0.1.0-rc.12"` e substituir/adaptar o contrato do runbook
para a RC12 — o runbook deve declarar:

- escopo somente UI (S1–S3), sem migrations, sem catálogo e sem ativação;
- cadeia de commits e prova de ausência de migrations no intervalo;
- preflight: RC11 saudável, v5 vigente com medições correntes, fila e
  workers;
- drenagem da fila de ingestão sem mutação manual;
- backup protegido com SHA-256 antes do deploy (obrigatório mesmo sem
  migration);
- deploy: preservar Compose RC11 como rollback, pull por tag exata,
  `config --quiet`, `up -d` e `migrate` idempotente (no-op esperado);
- verificação: health 200, `/beds` anônimo 302, dez `persistent_worker`,
  `/beds` autenticado contendo `Situação real do hospital` e cabeçalhos com
  métricas (verificação por agregados, sem PHI em relatório/screenshot);
- logs sem Traceback/CRITICAL novos;
- rollback: redeploy da RC11, trivial por ausência de mudança de schema;
  dados v5 são imutáveis e independentes da UI;
- nenhum comando de catálogo/dry-run/ativação.

Publicar tag somente se inexistente e apontando para HEAD/origin. Workflow
oficial success; release prerelease imutável com `compose.hospital.yml` e
`v0.1.0-rc.12-upgrade.md` como assets; imagem GHCR por tag exata e OCI
revision igual ao commit.

### R4 — Preflight produção

Confirmar somente agregados/metadados: root, `/srv/apps/prisma`, Docker
rootful, `.env` modo 600 sem conteúdo impresso, RC11 saudável (health, 302,
dez workers), migrations atuais, catálogo aplicável `occupancy-v5` com hash
`c84af977…`, medição v5 corrente existente, fila/status agregados sem PHI.

### R5 — Drenagem e backup

Bloquear novas entradas conforme runbook, manter workers para drenar e
aguardar queued/running zero (batches/summaries conforme prática RC11). Não
alterar status de run. Parar mutantes somente na ordem segura. Criar dump
custom em `/srv/apps/prisma/backups`, diretório 700, dump/checksum 600,
tamanho > 0 e `sha256sum -c` válido. Não copiar backup para fora do host.

### R6 — Deploy e verificação

- preservar Compose RC11 como rollback (`compose.hospital.yml.rc11`);
- alterar silenciosamente somente a versão aprovada;
- pull por tag exata, `config --quiet`, `migrate` (no-op esperado, idempotente
  se repetido), `up -d` na topologia completa;
- health 200, `/beds` anônimo 302, dez `persistent_worker`, imagem/revision
  exatas, zero Traceback/CRITICAL;
- `/beds` autenticado com a UI nova por agregados (presença de
  `Situação real do hospital`, cabeçalhos com `Cap.`/`pacientes`; sem nomes
  no relatório);
- medições v5 continuam sendo criadas pelo fluxo natural após o deploy;
- catálogo v5 idêntico antes/depois (hash e contagens).

## Arquivos esperados e limite

No repositório, máximo **3 arquivos rastreados**:

1. `docs/releases/v0.1.0-rc.12-upgrade.md`;
2. `docs/releases/README.md`;
3. `tests/unit/test_release_hospital_deploy.py`.

Não editar aplicação, migration, catálogo, ADR, Compose ou workflow neste
slice. Achado nesses arquivos bloqueia e retorna ao slice anterior. Relatório
`/tmp` e tasks ignoradas não contam.

## TDD e auditoria

### RED

Primeiro atualize o teste documental (contrato RC12) e prove failure pela
ausência do runbook RC12/`NEXT_RELEASE` antigo. Se os testes existentes já
cobrirem integralmente o novo contrato, registre inspeção RED justificando
por que nenhum teste novo é necessário; não fabrique alteração de código.

### GREEN

Runbook mínimo satisfaz o contrato RC12. Não alterar workflow maduro.

### REFACTOR

Clean code, DRY e YAGNI no runbook novo. Não reformatar runbooks antigos.

## Checks de inspeção obrigatórios

```bash
git status --short --branch
git log --oneline --decorate -12
git log v0.1.0-rc.11..HEAD -- 'apps/*/migrations' | wc -l
sha256sum apps/census/data/sector_capacity_catalog_v*.json
rg -n "somente UI|sem migration|sem catálogo|backup|sha256|drain|drenag|rollback|rc.11|302|persistent_worker|Situação real" \
  docs/releases/v0.1.0-rc.12-upgrade.md
rg -n "NEXT_RELEASE" tests/unit/test_release_hospital_deploy.py
rg -n "OpenAI|AsyncOpenAI|call_llm_gateway" tests/conftest.py
```

Após publicação:

```bash
git rev-list -n 1 v0.1.0-rc.12
gh run view <RUN_ID> --json status,conclusion,headSha,url
gh api repos/carlosapgomes/sirhosp/releases/tags/v0.1.0-rc.12 \
  --jq '{tag_name,draft,prerelease,immutable,assets:[.assets[].name]}'
docker buildx imagetools inspect ghcr.io/carlosapgomes/sirhosp:v0.1.0-rc.12
```

Interpretação obrigatória: o intervalo da RC deve ter zero migrations; os
cinco hashes de catálogo devem ser idênticos aos anteriores; o runbook deve
conter drenagem, backup, verificação e rollback; nenhum comando de catálogo
pode aparecer no runbook além de consulta read-only.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate improve-beds-v5-page-ux --strict
./scripts/markdown-lint.sh
```

## Critérios binários de sucesso

- [ ] S1–S3 auditados e coerentes; zero migrations; catálogos idênticos.
- [ ] Todos os gates verdes, sem 429/rede real.
- [ ] Docs commitados/pushed antes da tag.
- [ ] Tag/release/assets/imagem imutáveis e revision exata.
- [ ] Preflight RC11/v5 corrente.
- [ ] Fila drenada sem mutação manual; backup protegido/checksum válido.
- [ ] Deploy saudável: health 200, 302, dez workers, imagem exata, logs
      limpos.
- [ ] `/beds` autenticado com UI nova por agregados; medições v5 continuam.
- [ ] Catálogo v5 idêntico antes/depois; nenhum comando de catálogo.
- [ ] Rollback documentado e RC11 preservada.

### Condições automáticas de INCOMPLETO

- qualquer gate/teste/HTTP externo falha;
- tag/release/imagem preexistente divergente;
- asset/hash/digest/revision não verificável;
- migration no intervalo da RC ou schema alterado;
- catálogo novo/alterado ou comando de catálogo executado;
- fila mutada manualmente ou não drenada;
- backup ausente, público ou checksum falho;
- serviço fora, worker != 10, health/302/log falho;
- `/beds` autenticado sem a UI nova (verificação por agregados falhou);
- medições v5 deixaram de ser criadas após o deploy;
- segredo/PHI/output de `.env` em log ou relatório;
- código corrigido dentro do slice;
- relatório sem marcadores/evidência.

## Gates de autoavaliação

1. Qual commit exato foi tagueado e como origin/tag/revision coincidem?
2. Quais gates e contagens comprovam release-ready sem LLM externo?
3. Qual comando prova zero migrations no intervalo e hashes de catálogo
   idênticos?
4. Como a drenagem foi feita sem mutar runs?
5. Caminho/tamanho/modo/SHA do backup?
6. Quais containers provam dez workers e imagem exata?
7. Qual verificação por agregados prova a UI nova em produção?
8. Por que o rollback é trivial e qual Compose foi preservado?
9. Qual comando proibido não foi executado?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-IBPU-S4-report.md` com status, BASE_REF/release
commit, matriz R1–R6, auditoria, RED/GREEN documental, snippets antes/depois,
baseline versus final, quality gate completo, comandos exatos de rerun,
release URL/run, assets/hashes/digest/revision, pre/post produção sanitizado,
drenagem, backup, deploy, health/workers/logs, verificação da UI por
agregados, riscos, rollback e `Handoff para verificador`. Nunca incluir PHI
ou secrets.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the complete improve-beds-v5-page-ux
change, S1-S3 reports and diffs, deploy/workflow/runbook docs and
SLICE-IBPU-S4.md. Execute ONLY S4 under its DeepSeek4-Flash fail-closed
protocol. Audit first; do not patch application findings. Prove zero new
migrations and unchanged catalog hashes, then run every official container
gate with zero failures/errors/429. Update by TDD the release contract test
for v0.1.0-rc.12 (UI-only scope, no migration, no catalog, no activation,
drain, protected backup, aggregate verification, trivial rollback to RC11),
create the runbook and index, commit/push docs, then publish the exact
immutable tag/release/image through the official workflow. In authenticated
root tmux production use sanitized marked fail-closed scripts: preflight,
drain without manual mutations, SHA-verified backup, pull exact tag, config
check, idempotent no-op migrate, up -d, restore exactly ten workers, verify
health/302/images/revision/logs, confirm the new /beds UI via aggregates
only, and confirm v5 measurements keep flowing with the v5 catalog
unchanged. Never run catalog/dry-run/activation commands, print
env/secrets/PHI, build locally or edit outside /srv/apps/prisma. Any missing
or failing evidence is INCOMPLETE. Create /tmp/sirhosp-slice-IBPU-S4-report.md
with full verifier handoff. Mark only 4.x and STOP.
```
