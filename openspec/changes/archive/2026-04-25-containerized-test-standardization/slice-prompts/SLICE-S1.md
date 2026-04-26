# SLICE-S1 — Infra base de testes em container (Compose + test-runner)

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/containerized-test-standardization/proposal.md`
4. `openspec/changes/containerized-test-standardization/design.md`
5. `openspec/changes/containerized-test-standardization/tasks.md`
6. `openspec/changes/containerized-test-standardization/specs/developer-quality-gates/spec.md`
7. este arquivo `slice-prompts/SLICE-S1.md`

## Pré-condição de branch

- Confirmar branch do change com o revisor.
- Se não houver branch dedicada, criar/usar:

```bash
git checkout -b feature/containerized-test-standardization
```

## Objetivo do slice

Estabelecer a base operacional para rodar quality gates em container com PostgreSQL gerenciado automaticamente.

## Escopo permitido (somente)

- `compose.test.yml` (novo)
- `scripts/test-in-container.sh` (novo)
- `README.md` (somente trecho mínimo de uso do novo script, se estritamente necessário)

## Escopo proibido

- Código de domínio em `apps/*`
- Models/migrations
- Views/templates
- Mudanças em CI neste slice

## Limite de alteração

Máximo: **6 arquivos**.

## Regras obrigatórias deste slice

1. `test-in-container.sh` deve ter fluxo determinístico: `up -> wait -> run -> down`.
2. Teardown obrigatório em caso de erro (`trap EXIT`).
3. Subcomandos mínimos obrigatórios: `check`, `unit`, `lint`, `typecheck`.
4. `compose.test.yml` deve usar `db` da stack Compose (sem depender de host `127.0.0.1`).

## TDD obrigatório (quando aplicável)

1. **RED**: registrar falha inicial do comando oficial no host (erro infra/host `db`).
2. **GREEN**: executar `check` e `unit` via script em container com sucesso.
3. **REFACTOR**: simplificar script sem ampliar escopo.

## Gates obrigatórios S1

Registrar comando + exit code + resultado:

1. `docker compose -f compose.yml -f compose.test.yml config`
2. `./scripts/test-in-container.sh check`
3. `./scripts/test-in-container.sh unit`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-CTS-S1-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S2).

Pare ao concluir.
