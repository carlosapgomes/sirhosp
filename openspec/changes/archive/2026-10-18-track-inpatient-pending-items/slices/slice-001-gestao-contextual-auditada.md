# PEND-S1 — Gestão contextual auditada

## Identity

- Change: `track-inpatient-pending-items`.
- Task: `tasks.md`, 1.1.
- Dependências: nenhuma implementação anterior desta change.
- Estado: contrato proposto, executar somente após aprovação.

## Objective

Permitir que a equipe cadastre, edite e finalize pendências pela internação selecionada, com histórico consultável e proteção do episódio e da autoria.

## Read first

Paths relativos à raiz do repositório:

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/changes/track-inpatient-pending-items/proposal.md`.
- `openspec/changes/track-inpatient-pending-items/design.md` — D1–D4, D6, D9 e Migration Plan.
- `openspec/changes/track-inpatient-pending-items/specs/inpatient-pending-items/spec.md` — PI-01 a PI-06 e PI-08.
- `openspec/changes/track-inpatient-pending-items/specs/pending-items-portal/spec.md` — PP-01 e PP-09.
- `apps/patients/models.py`, `apps/patients/views.py`, `apps/patients/templates/patients/admission_list.html`.
- `apps/patients/admission_merge.py`, `apps/ingestion/services.py` — inventário e consolidação legada.
- `apps/census/models.py`, `apps/services_portal/views.py::_build_censo_context`.
- `tests/unit/test_admission_merge.py`, `tests/integration/test_admission_merge.py`, `tests/integration/test_summary_admission_cta_http.py`.
- `config/settings.py`, `config/urls.py`, `Dockerfile` e `compose.test.yml`.

## Requirements

| ID | Contrato observável | Evidência planejada |
| --- | --- | --- |
| R1 | PI-01/02: catálogo inicial Outro, grupo vazio e pendências manuais com tipo/descrição; duplicidade de tipo permitida. | Migrations/bootstrap, constraints, admin e cadastro de duas pendências iguais em tipo; rename/delete de Outro bloqueados mesmo sem uso, exclusão de tipo referenciado impedida e snapshots preservados após rename permitido. |
| R2 | PI-03 e PP-01: página vinculada ao período selecionado, escrita apenas na internação atual única e presente no censo. | HTTP com internação atual, antiga, ausente, ambígua, reinternação e ausência do censo; mensagem exata e nenhum provisório. |
| R3 | PI-04: grupo exigido, incluindo superusuário; colegas podem editar; qualquer autenticado consulta. | Matriz de acesso em services/POST/admin e anônimo redirecionado no detalhe e histórico. |
| R4 | PI-05/06: editar Ativa, finalizar com ou sem anotação e impedir correção/reabertura/delete de finais; versão e estado atômicos. | Testes de FSM, rollback por falha na revisão, versão obsoleta e POST que não pode impersonar Sistema. |
| R5 | PI-06/PP-09: versões completas e somente leitura, sem logs clínicos e sem cache compartilhado das superfícies contextuais. | Histórico HTTP, alteração de catálogo/conta, escape/logs e assertions de Cache-Control private/no-store em página, formulário, histórico e reexibição de erro. |
| R6 | PI-08: registro da relação, preservação em merge/rollback e guarda sequencial, com corrida residual aceita somente como falha conservadora sem perda. | Inventário/transferência/rollback e regressão legada com/sem pendências; intercalação controlada entre guarda e exclusão, erro propagado e transferências revertidas. |

## Expected blast radius

- Novo `apps/pending_items/`: schema/migrations, catálogo/admin, política de grupo, services, queries mínimas de elegibilidade, forms, endpoints e templates contextuais.
- Configuração de apps/URLs e ação contextual na tela de admissões.
- `apps/patients/admission_merge.py`, `apps/ingestion/services.py` e testes correlatos somente para preservar a nova relação.
- Novos testes unitários/integrados e cenário browser contextual; fixtures locais de assets estritamente necessárias a D9.
- Preservar comportamento de seleção de internação, catálogo clínico de origem, censo/XLSX existentes e consolidação sem pendências. Não alterar matching ou fontes de saída.

## Failing-before plan

Primeiro comprovar o harness mínimo de D9 no ambiente isolado: live_server/PostgreSQL, interceptação das URLs CDN por assets reais locais versionados e login pelo formulário em uma página existente. Somente depois registrar o RED da jornada contextual de pendências ainda ausente; erro de browser/assets/login é bloqueio de infraestrutura, não evidência de falha do produto.

Acrescentar testes RED dos serviços, proteção de Outro e headers de cache. Na proteção legada, demonstrar o comportamento anterior com fixture sintética e cobrir a intercalação de criação após a guarda: a falha conservadora deve preservar a pendência e desfazer transferências da consolidação. Registrar falhas/comandos no relatório; não alegar RED sem execução.

## Implementation constraints

Seguir as Engineering Policies de `AGENTS.md`; menor mudança correta, sem abstração especulativa ou refactor adjacente. Usar o modelo e a política de D1–D4 e a contenção específica de D6. Não implementar painel agregado, XLSX ou os hooks de encerramento automático de S2. Não publicar o estado intermediário como feature operacional completa.

Pendências/versões não têm CRUD administrativo paralelo nem DELETE HTTP. Bootstrap não associa nenhum usuário real ao grupo. A guarda legada antecede transferências/exclusões e não autoriza merge sem confirmação. Sua corrida residual é a de D6: erro de FK pode abortar a operação perdedora, com propagação e rollback, nunca sucesso falso ou perda de conteúdo; não prometer serialização de todas as candidatas.

## Validation

### Focused validation

- Novos testes propostos: `tests/unit/test_pending_items_services.py`, `tests/integration/test_pending_items_http.py` e cobertura de migrations/admin.
- Regressões de identidade/merge, consolidação e navegação contextual; proteção de Outro em uso e sem uso; teste da intercalação da guarda e rollback de transferências.
- Verificar diretivas private/no-store de Cache-Control nas respostas contextuais, formulário, histórico e erro de formulário, sem exigir ordenação específica das diretivas.
- Conferir ausência de migrations não registradas com `uv run python manage.py makemigrations --check --dry-run`, dentro do runner isolado; isso é adicional e não substitui os gates.

### Project-required gates

Executar os comandos oficiais de check, unit, integration, lint e typecheck definidos em `AGENTS.md`; markdown lint se houver documentação alterada. A integração é obrigatória neste slice. Não tratar execução host-only como gate.

### Runtime / verification evidence

Acrescentar jornada em `tests/integration/test_pending_items_browser.py` com servidor/banco de testes e login real: abrir internação, cadastrar, editar texto, consultar versões, finalizar sem anotação e consultar em modo leitor. Validar também apresentação em viewport móvel. Usar D9; não abrir sessão no portal dev implantado.

## Acceptance criteria

- [ ] R1: Outro/grupo disponíveis, rename/delete de Outro bloqueados inclusive sem uso, exclusão de tipo em uso impedida e cadastro permite tipo repetido com texto obrigatório.
- [ ] R2: período selecionado é preservado e casos inelegíveis bloqueiam escrita sem inventar dados.
- [ ] R3: matriz de acesso passa, inclusive superusuário sem grupo e edição de colega.
- [ ] R4: FSM, atomicidade e conflito de versão são demonstrados por testes executados.
- [ ] R5: versões completas/imutáveis, logs sem dados reais e Cache-Control private/no-store nas quatro superfícies contextuais são comprovados.
- [ ] R6: inventário, merge/rollback, guarda sequencial e intercalação conservadora passam sem perda ou regressão dos conjuntos sem pendências.
- [ ] Harness mínimo comprovado antes do RED de produto, jornada contextual de browser e validações obrigatórias passam; relatório existe.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` diante de contradição spec/design, nova decisão de produto/arquitetura, expansão material, quebra de compatibilidade, persistência/FSM não prevista ou novo risco clínico, de segurança, privacidade ou integridade. Bloquear também se preservar a relação exigir substituir o reconciliador ou se não houver verification confiável; não contornar com seleção arbitrária ou skip.

## Evidence report

Produzir `/tmp/sirhosp-slice-PEND-S1-report.md` conforme `AGENTS.md`: status, R1–R6 → evidência/resultado, arquivos/motivos, falha antes, sucesso depois, comandos/exit status, runtime, desvios de escopo, levers, riscos e decisões pendentes. Não duplicar o diff nem incluir dados reais.

## Worker handoff

Implementar somente este slice aprovado, reconstruindo contexto pelas referências. Produzir RED reproduzível, a menor implementação correta, validações e relatório. Não atualizar tasks, commitar, publicar, arquivar ou iniciar outro slice. Sem nova decisão, terminar com `READY_FOR_REVIEW` e `REPORT_PATH=/tmp/sirhosp-slice-PEND-S1-report.md`; caso contrário, `BLOCKED_NEEDS_DECISION`.
