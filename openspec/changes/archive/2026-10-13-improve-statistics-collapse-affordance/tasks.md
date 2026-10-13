# Tasks

Planejamento de implementação; nenhuma tarefa abaixo foi executada. A criação
desta change não autoriza iniciar implementação.

Validação de planejamento: OpenSpec strict e lint dos cinco Markdown desta
change passam. O lint global encontrou uma falha preexistente MD022 em
`openspec/specs/verification-origin-configuration/spec.md:3`, que não foi
alterado. Sua resolução é pendência separada antes de exigir esse gate global;
não autoriza ampliar silenciosamente o slice.

A skill `openspec-vertical-change-writer` dimensionou um único slice vertical:
markup, estilos, regressão e verification entregam juntos o comportamento
observável, sem separar artificialmente template, CSS e testes.

## 1. SCAF-S1 — Affordance e estado dos collapsibles

Contrato: [slice-001-statistics-collapse-affordance.md](slices/slice-001-statistics-collapse-affordance.md).
Cobre R1–R5; não há dependência de outro slice.

- [x] 1.1 [SCAF-S1](slices/slice-001-statistics-collapse-affordance.md): adicionar regressão de renderização com fixtures sintéticas e criar o cenário Playwright específico de D4 antes de alterar produção; verificar RED das categorias sem ícone e failing-before do chevron setorial estático, registrando comandos e exit status.
- [x] 1.2 [SCAF-S1](slices/slice-001-statistics-collapse-affordance.md): implementar os indicadores nos dois níveis e o layout/estilo neutro local conforme D1–D3; verificar GREEN de renderização e o ciclo direita → baixo → direita associado ao próprio `aria-expanded`, sem controlador JavaScript adicional.
- [x] 1.3 [SCAF-S1](slices/slice-001-statistics-collapse-affordance.md): demonstrar R1–R5 com `./scripts/test-in-container.sh integration` e `uv run python scripts/verify_statistics_collapses.py --output-dir /tmp/sirhosp-statistics-collapse-after`; verificar desktop/mobile, teclado, foco, independência, área clicável, título longo, badges e seção sem setor, com screenshots sintéticas e saída 0 sem skips.
- [x] 1.4 [SCAF-S1](slices/slice-001-statistics-collapse-affordance.md): produzir `/tmp/sirhosp-slice-SCAF-S1-report.md` com matriz R1–R5 → evidências, limitações e comandos; verificar completude segundo `AGENTS.md`, lint do cenário via `uv run ruff check scripts/verify_statistics_collapses.py` e markdown lint quando aplicável.

## 2. Encerramento da change pelo controller

Esta seção não é outro slice de implementação. Seguir `AGENTS.md` para revisão,
aceite, atualização das tarefas e commits no workflow posteriormente autorizado.

- [x] 2.1 Submeter SCAF-S1 a reviewer fresh/read-only e aceitar somente com R1–R5 demonstrados, validações obrigatórias aprovadas e nenhum P0/P1 ou decisão pendente; registrar o aceite e só então atualizar as tarefas correspondentes.
- [x] 2.2 Executar `./scripts/test-in-container.sh quality-gate` e a integração separada exigida por esta change no estado final; confirmar que a verification sintética corresponde ao mesmo código e que `./scripts/markdown-lint.sh` e `openspec validate improve-statistics-collapse-affordance --strict` passam; registrar resultados finais sem declarar pronto em caso de gate ou runtime bloqueado.

Não realizar push, merge, deploy, sync de specs ou archive nesta etapa.
