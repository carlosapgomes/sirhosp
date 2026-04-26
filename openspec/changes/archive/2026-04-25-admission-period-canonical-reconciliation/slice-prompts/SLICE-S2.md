# SLICE-S2 — Consolidação de duplicatas já existentes (merge determinístico + preservação de eventos)

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-period-canonical-reconciliation/proposal.md`
4. `openspec/changes/admission-period-canonical-reconciliation/design.md`
5. `openspec/changes/admission-period-canonical-reconciliation/tasks.md`
6. `openspec/changes/admission-period-canonical-reconciliation/specs/patient-admission-mirror/spec.md`
7. este arquivo (`slice-prompts/SLICE-S2.md`)

## Objetivo do slice

Quando já existirem admissões duplicadas para o mesmo paciente/período (chaves de origem diferentes), consolidar para uma única admissão canônica, sem perder eventos já extraídos.

## Escopo permitido (somente)

- `apps/ingestion/services.py`
- `tests/unit/test_ingestion_service.py`

## Escopo proibido

- migrations
- alterações de schema
- views/templates
- qualquer comando de manutenção separado

## Limite de alteração

Máximo: **2 arquivos**.

Se precisar exceder, pare e reporte bloqueio.

## TDD obrigatório

1. **RED**: adicionar testes unitários para cenário com duplicatas pré-existentes no mesmo período:
   - criar 2 admissões (mesmo paciente/período, `source_admission_key` distintos),
   - anexar evento(s) em pelo menos uma delas,
   - executar `upsert_admission_snapshot` com snapshot desse período,
   - validar que restou apenas 1 admissão para o período,
   - validar que os eventos ficaram associados à admissão canônica.
2. **GREEN**: implementar merge determinístico no serviço:
   - canônica = maior `event_count`; empate = menor `id`.
3. **REFACTOR**: extração de helper local somente se necessário, sem expandir escopo.

## Critérios de aceite

- Duplicatas por período deixam de existir após upsert.
- Nenhum `ClinicalEvent` é perdido no merge.
- Regras S1 continuam válidas (não regressão).

## Gates obrigatórios S2

Executar e registrar saída/exit code:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`

## Relatório obrigatório de saída

Gerar **`/tmp/sirhosp-slice-APCR-S2-report.md`** contendo:

1. resumo do slice;
2. checklist de aceite;
3. arquivos alterados;
4. snippets `ANTES`/`DEPOIS` por arquivo alterado;
5. comandos executados e resultados;
6. riscos/pêndencias;
7. próximo passo sugerido (S3).

Pare ao concluir o slice.
