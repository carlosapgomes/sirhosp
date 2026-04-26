# SLICE-S3 — Regressão de lifecycle do worker (rerun com chave volátil não duplica internação)

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-period-canonical-reconciliation/proposal.md`
4. `openspec/changes/admission-period-canonical-reconciliation/design.md`
5. `openspec/changes/admission-period-canonical-reconciliation/tasks.md`
6. `openspec/changes/admission-period-canonical-reconciliation/specs/patient-admission-mirror/spec.md`
7. `openspec/changes/admission-period-canonical-reconciliation/specs/evolution-ingestion-on-demand/spec.md`
8. este arquivo (`slice-prompts/SLICE-S3.md`)

## Objetivo do slice

Validar em integração (worker lifecycle) que múltiplos runs para a mesma internação/período com `admission_key` variável convergem para uma única `Admission`.

## Escopo permitido (somente)

- `tests/integration/test_worker_lifecycle.py`
- `apps/ingestion/services.py` (somente se algum ajuste residual for necessário para passar o teste)

## Escopo proibido

- extractor/playwright
- views/templates
- mudanças de contrato HTTP
- migrações

## Limite de alteração

Máximo: **2 arquivos**.

Se precisar exceder, pare e reporte bloqueio.

## TDD obrigatório

1. **RED**: criar teste de integração novo no bloco de lifecycle/semântica de admissões cobrindo:
   - run 1 captura snapshot com `admission_key=A` para período P;
   - run 2 captura snapshot com `admission_key=B` para mesmo período P;
   - opcionalmente incluir falha de extração em um run e sucesso no outro;
   - assert final: existe **1 única** `Admission` para paciente+período.
2. **GREEN**: ajustar implementação **apenas se o teste falhar**.
3. **REFACTOR**: mínimo, sem ampliar escopo.

## Critérios de aceite

- Regressão reproduzida em teste automatizado.
- Worker não multiplica admissões para mesmo período após rerun.
- Contratos anteriores de semântica de falha/sucesso permanecem válidos.

## Gates obrigatórios S3

Executar e registrar saída/exit code:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh integration`
3. `./scripts/test-in-container.sh unit`

## Relatório obrigatório de saída

Gerar **`/tmp/sirhosp-slice-APCR-S3-report.md`** contendo:

1. resumo do slice;
2. checklist de aceite;
3. arquivos alterados;
4. snippets `ANTES`/`DEPOIS` por arquivo alterado;
5. comandos executados e resultados;
6. riscos/pêndencias finais;
7. status final do change (pronto para review/archive ou pendente).

Pare ao concluir o slice.
