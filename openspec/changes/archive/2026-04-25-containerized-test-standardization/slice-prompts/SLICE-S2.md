# SLICE-S2 — Padronização dos comandos oficiais (AGENTS/README)

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/containerized-test-standardization/proposal.md`
4. `openspec/changes/containerized-test-standardization/design.md`
5. `openspec/changes/containerized-test-standardization/tasks.md`
6. `openspec/changes/containerized-test-standardization/specs/developer-quality-gates/spec.md`
7. `/tmp/sirhosp-slice-CTS-S1-report.md`
8. este arquivo `slice-prompts/SLICE-S2.md`

## Pré-condição de branch

Obrigatório estar na branch da change (mesma da S1).

## Objetivo do slice

Tornar explícito que o caminho oficial de validação do projeto é o fluxo containerizado.

## Escopo permitido (somente)

- `AGENTS.md`
- `README.md`
- `PROJECT_CONTEXT.md` (somente se necessário para alinhar execução oficial)
- `Makefile` (novo, opcional)

## Escopo proibido

- Código de domínio (`apps/*`)
- Compose de infra (já tratado no S1)
- CI workflow (S3)

## Limite de alteração

Máximo: **6 arquivos**.

## Regras obrigatórias deste slice

1. Comandos oficiais de quality gate devem apontar para `scripts/test-in-container.sh` (diretamente ou via Makefile).
2. Documentar claramente:
   - por que `POSTGRES_HOST=db` falha no host;
   - que execução host-only é diagnóstico, não fluxo oficial.
3. Não remover fallback de diagnóstico sem alinhar com revisor.

## TDD obrigatório (quando aplicável)

1. **RED**: identificar e listar trechos documentais conflitantes com a política containerizada.
2. **GREEN**: atualizar documentação/comandos para caminho único oficial.
3. **REFACTOR**: reduzir duplicação de instruções entre `AGENTS.md` e `README.md`.

## Gates obrigatórios S2

Registrar comando + exit code + resultado:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`
3. `./scripts/test-in-container.sh lint`
4. `./scripts/test-in-container.sh typecheck`
5. `./scripts/markdown-lint.sh` (obrigatório porque altera `.md`)

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-CTS-S2-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S3).

Pare ao concluir.
