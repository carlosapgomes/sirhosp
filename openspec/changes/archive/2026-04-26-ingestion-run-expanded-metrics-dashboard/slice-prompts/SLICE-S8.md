# SLICE-S8 — Hardening final, evidências e fechamento

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/ingestion-run-expanded-metrics-dashboard/proposal.md`
4. `openspec/changes/ingestion-run-expanded-metrics-dashboard/design.md`
5. `openspec/changes/ingestion-run-expanded-metrics-dashboard/tasks.md`
6. todos os relatórios anteriores:
   - `/tmp/sirhosp-slice-IRMD-S1-report.md`
   - `/tmp/sirhosp-slice-IRMD-S2-report.md`
   - `/tmp/sirhosp-slice-IRMD-S3-report.md`
   - `/tmp/sirhosp-slice-IRMD-S4-report.md`
   - `/tmp/sirhosp-slice-IRMD-S5-report.md`
   - `/tmp/sirhosp-slice-IRMD-S6-report.md`
   - `/tmp/sirhosp-slice-IRMD-S7-report.md`
7. este arquivo `slice-prompts/SLICE-S8.md`

## Pré-condição de branch

```bash
git checkout feature/ingestion-run-expanded-metrics-dashboard
```

## Objetivo do slice

Consolidar o change com validação completa, ajustes residuais mínimos e evidência final para revisão/aprovação.

## Escopo permitido

- Ajustes residuais estritamente necessários para passar quality gate.
- Atualização de artefatos OpenSpec desta change (`tasks.md` e, se necessário, docs desta change).

## Escopo proibido

- nova funcionalidade fora de escopo da change
- refactors amplos sem relação com falha de validação

## Limite de alteração

Máximo: **5 arquivos** além de correções estritamente necessárias para gates.

## Requisitos obrigatórios do slice

1. Executar gate completo oficial:
   - `./scripts/test-in-container.sh quality-gate`
2. Validar markdown:
   - `./scripts/markdown-lint.sh`
3. Atualizar `openspec/changes/ingestion-run-expanded-metrics-dashboard/tasks.md` marcando checkboxes concluídos.
4. Não alterar sem necessidade artefatos fora da change.

## Entregável obrigatório

Gerar `/tmp/sirhosp-slice-IRMD-S8-report.md` com:

- resumo executivo da change;
- checklist final de aceite;
- lista de arquivos alterados no S8;
- snippets before/after por arquivo alterado no S8;
- comandos executados e resultados completos dos gates;
- pendências remanescentes (se houver);
- recomendação objetiva de `APPROVE` ou `REQUEST_CHANGES`.

Pare ao concluir.
