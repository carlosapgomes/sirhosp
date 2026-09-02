# Tasks — `clarify-patient-flow-labels`

## 1. CFL-S1 — Rótulos sem jargão de TI

- [x] 1.1 Baselines oficiais (unit/integration do commit base real)
      registradas e árvore limpa.
- [x] 1.2 RED: os pinos de teste passam a esperar "Suspeita de paciente
      residual" e "Suspeita de internação antiga em aberto ou alta não
      detectada" e falham contra as constantes antigas (motivo: label
      divergente).
- [x] 1.3 GREEN: os 2 labels em `_FINDING_SPECS` renomeados (códigos/
      severidades/revisão intocados) — no máximo 3 arquivos no diff.
- [x] 1.4 Gates: quality-gate, integration, openspec strict e markdown
      lint exit 0, passed >= baseline.
- [x] 1.5 Relatório `/tmp/sirhosp-slice-CFL-S1-report.md` com RED/GREEN,
      snippets antes/depois, contagens e handoff para verificador; marcar
      1.1–1.5 somente após tudo verde.

## 2. Verificação final do change

- [x] 2.1 Relatório COMPLETE aprovado de CFL-S1 por verificador
      independente, com RED reproduzido e gates re-executados.
- [x] 2.2 `./scripts/test-in-container.sh quality-gate` e
      `./scripts/test-in-container.sh integration` com exit code zero.
- [x] 2.3 `openspec validate clarify-patient-flow-labels --strict` e
      `./scripts/markdown-lint.sh` sem erros.
- [x] 2.4 Revisar diff acumulado: sem PHI, sem model/migration/dependência,
      classificador semanticamente intocado (apenas as 2 constantes de
      label), zero ocorrências dos textos antigos fora de archives.
