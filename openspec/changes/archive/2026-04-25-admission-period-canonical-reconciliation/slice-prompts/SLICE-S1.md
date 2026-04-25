<!-- markdownlint-disable MD013 -->
# SLICE-S1 — Reconciliação canônica por paciente+período (prevenção de novas duplicatas)

## Handoff de entrada (contexto zero)

Você está no projeto `sirhosp`.

Leia obrigatoriamente antes de codar:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-period-canonical-reconciliation/proposal.md`
4. `openspec/changes/admission-period-canonical-reconciliation/design.md`
5. `openspec/changes/admission-period-canonical-reconciliation/tasks.md`
6. `openspec/changes/admission-period-canonical-reconciliation/specs/patient-admission-mirror/spec.md`
7. `openspec/changes/admission-period-canonical-reconciliation/specs/evolution-ingestion-on-demand/spec.md`
8. este arquivo (`slice-prompts/SLICE-S1.md`)

## Objetivo do slice

Impedir que o sistema crie nova `Admission` quando o `admission_key` externo mudar entre runs, mas o paciente e o período de internação forem os mesmos.

## Escopo permitido (somente)

- `apps/ingestion/services.py`
- `tests/unit/test_ingestion_service.py`

## Escopo proibido

- models/migrations
- views/templates
- worker command (`process_ingestion_runs`) e extractor
- qualquer alteração fora do serviço de upsert e seus testes unitários

## Limite de alteração

Máximo: **2 arquivos**.

Se precisar exceder, pare e reporte bloqueio.

## TDD obrigatório

1. **RED**: adicionar teste(s) em `TestUpsertAdmissionSnapshot` comprovando:
   - primeira captura cria internação `A` para paciente/período;
   - segunda captura com mesma janela e `admission_key` diferente **não** cria nova linha;
   - total de admissões para o paciente/período permanece `1`.
2. **GREEN**: implementar o mínimo em `upsert_admission_snapshot` para passar.
3. **REFACTOR**: limpeza mínima sem ampliar escopo.

## Critérios de aceite

- Rerun com chave volátil no mesmo período não duplica `Admission`.
- Continua válido exibir internações sem eventos.
- Contrato de retorno (`created`, `updated`) permanece coerente com os testes existentes.

## Gates obrigatórios S1

Executar e registrar saída/exit code:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`

## Relatório obrigatório de saída

Gerar **`/tmp/sirhosp-slice-APCR-S1-report.md`** contendo:

1. resumo do que foi implementado;
2. checklist de aceite (marcado item a item);
3. lista de arquivos alterados;
4. para cada arquivo alterado: snippets `ANTES` e `DEPOIS` dos trechos relevantes;
5. comandos executados (comando, exit code, resultado);
6. riscos/pendências;
7. próximo passo sugerido (S2).

Pare ao concluir o slice.
