# S2 — Cadastro e gestão estruturada

## Identity e objetivo

- ID: `STRUCT-PEND-S2`; change: `structure-inpatient-pending-items`.
- Tasks: [grupo 2](../tasks.md#2-s2--cadastro-e-gestão-estruturada).
- Dependência: S1 aceito; executar somente após aprovação deste contrato.
- Objetivo: cadastrar, editar, consultar e finalizar os quatro perfis de
  pendência na internação atual, preservando detalhes e histórico em toda escrita.

## Read first

- `AGENTS.md`, `PROJECT_CONTEXT.md` e `openspec/config.yaml` na raiz.
- [Proposal](../proposal.md), [catálogo](../catalog.md),
  [design D2–D6, D8 e D9](../design.md) e
  [contrato S1](slice-001-catalogo-categorizado.md).
- [Delta de domínio](../specs/inpatient-pending-items/spec.md) e
  [delta de portal](../specs/pending-items-portal/spec.md), PP-10 e PP-06.
- Specs atuais `openspec/specs/inpatient-pending-items/spec.md` e
  `openspec/specs/pending-items-portal/spec.md`, sobretudo invariantes mantidos.
- `apps/pending_items/{models,services,forms,views,views_aggregate}.py`,
  `eligibility.py`, `policy.py` e templates contextuais/de edição rápida.
- `tests/unit/test_pending_items_services.py`,
  `tests/unit/test_pending_items_exit_close.py`;
  `tests/integration/test_pending_items_http.py`,
  `test_pending_items_exit_lifecycle.py` e `test_pending_items_browser.py`.

## Requirements e evidência planejada

| ID  | Comportamento e fonte                                            | Evidência planejada                                                                  |
| --- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| R1  | Quatro perfis, observações condicionais e RNM, PI-01/09/11       | Matriz de casos abaixo, exercitada no domínio e em POST real                         |
| R2  | Todos os detalhes entram na revisão, PI-06                       | Alteração só de detalhe, no-op, revisão antiga, falha de snapshot e troca confirmada |
| R3  | FSM e saída Sistema preservadas, PI-05/07/08                     | Alta/óbito/transferência, merge e reprocessamento sem perder detalhes/finalizações   |
| R4  | Cadastro e todos os formulários de edição funcionam, PP-10/06    | HTTP e Playwright: contextual/modal, busca, adicionar outra, teclado/mobile          |
| R5  | Episódio, autorização e concorrência seguros, PI-03/04, PP-01/09 | Requisições diretas, conflito, perda de grupo/saída e cache em erro                  |
| R6  | Upgrade dos campos não inventa valores, PI-10                    | Migration desde S1 com item/revisões sintéticos e posterior edição                   |

## Matriz mínima de comportamento

| Caso                                                            | Resultado esperado, conforme specs/design                                  |
| --------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Tipo definido com observação vazia; Outro/Outros só com espaços | Primeiro aceito; genéricos rejeitados sem item/revisão                     |
| Agendada ausente; Não com data; Sim sem data; Sim com data      | Dois primeiros rejeitados; demais aceitos                                  |
| RNM em cada categoria                                           | Contraste e sedação independentes, incluindo Não informado e Não           |
| Tratamento sem datas, só início, só término ou ambas            | Aceitos; término anterior ao início rejeitado quando ambos existem         |
| Assinatura ausente ou preenchida                                | Aceita sem finalizar nem modificar a internação                            |
| Detalhe fora do perfil em POST direto                           | Rejeitado, sem estado parcial                                              |
| Troca de perfil com detalhe; Sim -> Não com data anterior       | Remoção somente confirmada; cancelamento preserva dados e revisão anterior |
| Alterar apenas data/contraste/sedação; reenviar estado idêntico | Nova versão no primeiro caso; no-op no segundo                             |
| Cadastro Risco de óbito ou data passada                         | Nenhuma inferência clínica, encerramento ou prioridade automática          |

## Expected blast radius e fronteira

Models/migrations dos campos reais de item/revisão, services/forms e todas as
views/templates que os recebem, inclusive edição rápida. Listagem e histórico
contextuais devem mostrar os valores gravados. Este slice entrega a
apresentação compartilhada inicial de D6, que S3 reutilizará no agregado, sem
criar uma segunda interpretação de detalhes. Catálogo e metadados de S1 são
reutilizados, não recarregados/redesenhados.

Este slice é dono de toda a escrita estruturada, inclusive token de versão e
preservação dos dados tentados no modal. Não adiar esse caminho para S3. A
apresentação resumida e o histórico recolhível do agregado, sua atualização
visual e o filtro por categoria são responsabilidade de S3.

Preservar recorte e XLSX anterior funcionando; não antecipar colunas novas.
Não alterar lógica de census/saída/merge, grupos ou métricas. Ajustes de
compatibilidade estritamente necessários devem ser justificados no relatório.

## Failing-before plan

Usar TDD antes de produção de código nos seams já existentes:

- POST de Tomografia sem observação e com Agendada Não: deve revelar a
  obrigatoriedade antiga antes de GREEN.
- RNM Sim sem data com contraste/sedação e alteração só de detalhe: deve
  revelar a ausência de persistência/revisão desses valores, não só import.
- Jornada de seleção progressiva e Salvar e adicionar outra: deve falhar pela
  interação ausente antes de implementar formulário/template.

Adicionar casos negativos da matriz antes de implementar cada regra. Registrar
RED/GREEN separando falha do produto de indisponibilidade do harness.

## Implementation constraints

Seguir `AGENTS.md` e D2–D6. Implementar as constraints locais de S2 enumeradas
em D3 tanto em item quanto em revisão, com testes de escrita direta: data
agendada exige Sim e término não antecede início quando ambos existem.
Preservar nulos históricos e testar separadamente a validação que depende do
tipo relacionado. Validar campos fora da UI; omissão em um formulário
antigo não pode apagar valores novos. Atualizar todos os pontos que criam
revisão, inclusive finalização humana e Sistema; não alterar lock order.
Não criar configuração genérica de campos, prioridade clínica ou tarefa
programada por datas. Finalização não exige completar campos de cadastro.

## Validation

### Focused validation

Cobrir matriz, upgrade, services, HTTP e regressão de saída/merge com `check`,
`unit` e `integration` pelo wrapper oficial. Conferir migrations pendentes no
runner conforme comando de tasks. Nenhuma falha de compatibilidade fica para
S3/S4; atualizar apenas expectativas cujo contrato mudou explicitamente.

### Project-required gates

Seguir gates estáticos, Markdown e revisão independente de `AGENTS.md`.

### Runtime / verification

No live_server sintético, cadastrar e editar os quatro perfis, distinguir as
duas RNM na busca, testar observações condicionais, datas parciais, troca
confirmada/cancelada, conflito e atualização da página sem cadastro duplicado.
Conferir persistência e histórico contextual, não apenas controles na tela.
Repetir fluxo essencial a 390px e por teclado. O modal deve gravar/recuperar
os campos; os resumos atualizados do agregado são demonstrados em S3.

Saída confirmada real deve ser verificada no contexto da internação: fecha
ativas como Sistema, preserva detalhes/finalizações e torna o episódio somente
leitura. O episódio encerrado não precisa nem pode permanecer no agregado atual.

## Acceptance criteria

- [ ] R1: matriz normativa e constraints locais de D3 são atendidas sem valores inferidos nem automação por datas.
- [ ] R2: revisão é completa/atômica; no-op não cria versão e remoção exige confirmação.
- [ ] R3: saídas/merge preservam detalhes e encerram somente ativas com autoria Sistema.
- [ ] R4: cadastro, edição contextual e modal gravam os mesmos dados nos viewports alvo; contexto usa a apresentação compartilhada inicial de D6.
- [ ] R5: conflito/perda de elegibilidade não sobrescrevem dados; cache permanece protegido.
- [ ] R6: campos novos permanecem desconhecidos no passado e upgrade mantém identidades.
- [ ] Gates focados, runtime e relatório correspondem ao estado final deste slice.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` para contradição de contrato, nova decisão de
produto/arquitetura, persistência ou FSM não previstas, risco de segurança,
privacidade/integridade, descarte, expansão material ou infraestrutura que
impeça verification. Não resolver essas decisões por alteração silenciosa.

## Evidence report e worker handoff

Produzir `/tmp/sirhosp-slice-STRUCT-PEND-S2-report.md` conforme `AGENTS.md`, com
R1–R6 -> evidência, RED/GREEN, comandos/resultados, runtime, arquivos, desvios,
levers e riscos reais.

Quando autorizado, implementar somente este slice com contexto reconstruído
das referências. Não atualizar tasks, criar commit, push, merge, archive ou
iniciar outro slice. Terminar com `READY_FOR_REVIEW` e `REPORT_PATH`, ou
`BLOCKED_NEEDS_DECISION` com evidências.
