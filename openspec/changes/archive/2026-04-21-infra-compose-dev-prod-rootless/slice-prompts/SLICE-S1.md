# SLICE-S1 — Base de imagem container (dev/prod targets)

## Handoff de entrada (contexto zero)

Você está no projeto `sirhosp` (Django 5 + uv). A Fase A funcional já foi concluída.

Sua missão neste slice é **apenas** criar a base de imagem para container.

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/infra-compose-dev-prod-rootless/proposal.md`
4. `openspec/changes/infra-compose-dev-prod-rootless/design.md`
5. `openspec/changes/infra-compose-dev-prod-rootless/tasks.md`

## Objetivo

Implementar build container com targets `dev` e `prod`, sem alterar regras de negócio.

## Escopo permitido

- `Dockerfile`
- `.dockerignore`
- `docker/entrypoint.sh` (ou nome equivalente em `docker/`)
- ajuste mínimo em docstring/comentário, se estritamente necessário

## Escopo proibido

- modelos Django, migrações, services de domínio, views, templates clínicos
- qualquer implementação da Fase B

## Limite de alteração

Máximo: **5 arquivos**.

Se precisar de mais, pare e reporte bloqueio.

## Estratégia de validação (RED/GREEN operacional)

Não criar suíte nova de testes unitários para este slice.

Faça RED/GREEN operacional:

1. RED: evidenciar que não há build funcional antes da implementação.
2. GREEN: executar build dos targets e comprovar sucesso.

## Comandos mínimos sugeridos

- detectar engine disponível (`docker compose` ou `podman compose`)
- build target dev
- build target prod

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-S1-report.md` com:

- resumo do que foi feito;
- arquivos alterados;
- snippets antes/depois;
- comandos executados e resultados;
- riscos e próximo passo.

Pare ao concluir o slice.
