# SLICE-S4 — Hardening operacional e transição final

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/containerized-test-standardization/proposal.md`
4. `openspec/changes/containerized-test-standardization/design.md`
5. `openspec/changes/containerized-test-standardization/tasks.md`
6. `openspec/changes/containerized-test-standardization/specs/developer-quality-gates/spec.md`
7. `/tmp/sirhosp-slice-CTS-S3-report.md`
8. este arquivo `slice-prompts/SLICE-S4.md`

## Pré-condição de branch

Obrigatório estar na branch da change (mesma da S1/S2/S3).

## Objetivo do slice

Finalizar a padronização operacional, removendo ambiguidades de execução e adicionando troubleshooting objetivo.

## Escopo permitido (somente)

- `README.md`
- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/containerized-test-standardization/*` (ajustes finais de artefato)

## Escopo proibido

- Código de domínio
- Novas features de produto
- Mudança estrutural no pipeline além de hardening documental/operacional

## Limite de alteração

Máximo: **6 arquivos**.

## Regras obrigatórias deste slice

1. Política explícita final:
   - quality gate oficial = containerizado;
   - host-only = diagnóstico local.
2. Adicionar seção de troubleshooting para falhas comuns:
   - Docker indisponível;
   - porta de PostgreSQL ocupada;
   - timeout de healthcheck;
   - cleanup de containers órfãos.
3. Validar consistência entre AGENTS, README e artefatos OpenSpec.

## TDD obrigatório (quando aplicável)

1. **RED**: apontar inconsistências remanescentes entre documentos.
2. **GREEN**: alinhar linguagem e comandos oficiais.
3. **REFACTOR**: remover redundâncias e manter instrução única por contexto.

## Gates obrigatórios S4

Registrar comando + exit code + resultado:

1. `./scripts/test-in-container.sh quality-gate`
2. `uv run python manage.py check` (sanity local)
3. `./scripts/markdown-lint.sh` (obrigatório por alteração `.md`)

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-CTS-S4-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- declaração explícita de conclusão da change.

Pare ao concluir.
