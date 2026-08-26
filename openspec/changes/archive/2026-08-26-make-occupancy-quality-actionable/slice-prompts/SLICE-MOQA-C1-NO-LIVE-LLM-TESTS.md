# MOQA-C1 — Proibir chamadas reais de LLM nos testes

## Handoff com contexto zero

O attempt da task 4.4 foi interrompido porque
`tests/integration/test_summary_worker_lifecycle.py` chamou OpenRouter/Mistral e
recebeu HTTP 429. Leia `AGENTS.md`, `PROJECT_CONTEXT.md`, este prompt, o relatório
`/tmp/sirhosp-slice-MOQA-4.4-report.md`, `pyproject.toml`, `config/settings.py`,
`apps/summaries/llm_gateway.py`, `apps/summaries/services.py`, o management
command e o arquivo de integração completo.

Há duas alterações documentais preexistentes e fora deste slice:
`docs/releases/README.md` e `docs/releases/v0.1.0-rc.10-upgrade.md`. Preserve-as
sem incluí-las no commit corretivo.

## Objetivo

Garantir por construção que nenhuma suíte pytest possa abrir cliente OpenAI
real por omissão e fornecer resposta LLM sintética determinística aos testes de
lifecycle que exercitam o pipeline serial.

## Requisitos

- R1: fixture global autouse bloqueia `OpenAI` e `AsyncOpenAI` do gateway com
  erro local explícito antes de rede.
- R2: testes de lifecycle simulam `apps.summaries.services.call_llm_gateway`
  com payload válido e determinístico.
- R3: teste de regressão comprova que cliente sem mock é bloqueado.
- R4: teste comprova que o lifecycle usa o gateway simulado e conclui.
- R5: nenhum código de produção, configuração de release ou dependência muda.
- R6: integration completa passa independentemente de chave/provedor/rede.

## Limite rígido

Máximo dois arquivos:

1. novo `tests/conftest.py`;
2. `tests/integration/test_summary_worker_lifecycle.py`.

Não alterar aplicação, pyproject, Compose, `.env`, migrations ou docs.

## TDD

RED já reproduzido no gate oficial: 10 falhas, 380 passes, HTTP 429. Registre-o
como teste de caracterização. Primeiro adicione teste explícito do bloqueio e do
mock; depois implemente as fixtures mínimas. REFACTOR sem abstração genérica.

## Gates

```bash
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate make-occupancy-quality-actionable --strict
./scripts/markdown-lint.sh
```

Todos devem retornar exit 0, sem 429. Inspecione:

```bash
rg -n "OpenAI|AsyncOpenAI|Unexpected external LLM|call_llm_gateway" \
  tests/conftest.py tests/integration/test_summary_worker_lifecycle.py
rg -n "https://|openrouter|mistral|api_key" \
  tests/integration/test_summary_worker_lifecycle.py
```

## Critérios binários

- [ ] RED externo documentado.
- [ ] Guard global síncrono e assíncrono.
- [ ] Stub serial válido.
- [ ] Regressões de bloqueio e uso do stub.
- [ ] Integração 390/390 ou superior, zero falhas/429.
- [ ] Todos os gates verdes.
- [ ] Somente dois arquivos no commit.
- [ ] Release/deploy/ativação não executados.

### INCOMPLETO automático

Qualquer chamada externa, gate falho, mock aplicado ao namespace errado,
interferência em testes que mockam explicitamente, arquivo extra, inclusão das
docs RC10 no commit ou início da task 4.4 torna o slice INCOMPLETO.

## Relatório

Criar `/tmp/sirhosp-slice-MOQA-C1-report.md` com status, baseline/RED, matriz
R1–R6, snippets antes/depois, inspeções, gates, lista exata do commit, riscos e
handoff. Commit/push somente os dois arquivos de teste e pare. Não marcar 4.4.

## Prompt pronto

```text
Implement ONLY MOQA-C1. Preserve the preexisting uncommitted RC10 docs. Use the
recorded 10-failure HTTP-429 integration run as RED, then add a global autouse
guard against real OpenAI/AsyncOpenAI clients and a deterministic service-level
LLM stub for summary lifecycle integration tests. Add regression tests proving
both. Touch at most tests/conftest.py and the lifecycle test. Run every official
gate; any network call/failure means INCOMPLETE. Commit/push only those two test
files, create /tmp/sirhosp-slice-MOQA-C1-report.md and STOP without task 4.4.
```
