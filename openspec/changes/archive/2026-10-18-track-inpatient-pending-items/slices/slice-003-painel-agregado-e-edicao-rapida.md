# PEND-S3 — Painel agregado e edição rápida

## Identity

- Change: `track-inpatient-pending-items`.
- Task: `tasks.md`, 3.1.
- Dependência: PEND-S2 aceito.
- Estado: contrato proposto, executar somente após aprovação.

## Objective

Permitir acompanhar pendências dos internados atuais em duas visualizações responsivas, com filtros, primeira unidade registrada, indicadores hospitalares e edição rápida auditada.

## Read first

Paths relativos à raiz do repositório:

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/changes/track-inpatient-pending-items/proposal.md`.
- `openspec/changes/track-inpatient-pending-items/design.md` — D2–D4 e D7–D9.
- `openspec/changes/track-inpatient-pending-items/specs/pending-items-portal/spec.md` — PP-01 a PP-07 e PP-09.
- `openspec/changes/track-inpatient-pending-items/specs/inpatient-pending-items/spec.md` — PI-03 a PI-06.
- `apps/pending_items/` e testes entregues por S1/S2.
- `apps/services_portal/views.py::_build_censo_context`, `apps/census/models.py`, `apps/census/services.py::upsert_patient_movements`.
- `templates/includes/sidebar.html`, `templates/base_sidebar.html`, `templates/base.html`, `apps/core/context_processors.py`.
- `tests/unit/test_services_portal_censo.py`, `tests/integration/test_pending_items_browser.py` e `compose.test.yml`.

## Requirements

| ID | Contrato observável | Evidência planejada |
| --- | --- | --- |
| R1 | PP-02/03: menu e recorte atual conservador único; por paciente padrão e por pendência alternativo, com paridade em desktop/mobile. | HTTP/querysets com reinternação, duas abertas, leitos conflitantes, duplicatas equivalentes do censo, ausência de censo e paginação; browser das duas visões. |
| R2 | PP-04: filtros combinam antes do agrupamento, com autores separados, Sistema e tempo ativo/finalizado correto. | Testes de queries com relógio controlado e seleção de controles pelo browser. |
| R3 | PP-05: primeira unidade é do episódio, inclui PS e não usa passagem anterior; fallback explícito para evidência insuficiente. | Movimentos ligados/nulos, reinternação, sobreposição e sequência PS→UTI→Enfermaria; tabela/cards renderizados. |
| R4 | PP-06 e PI-04/06: modal edita pelo serviço canônico e histórico recolhível mostra versões; conflitos não anunciam sucesso. | Browser de edição/finalização, remoção do grupo vazio e leitor; HTTP de conflito, perda de grupo e saída durante formulário aberto. |
| R5 | PP-07: indicadores usam o mesmo recorte conservador, pacientes distintos e durações por pendência, ignorando filtros/modo/página. | Idades 2/8/5 dias em dois pacientes válidos, casos ambíguos excluídos e duplicatas equivalentes contadas uma vez; filtros vazios e ausência de ativas. |
| R6 | PP-01/03/09 e PI-06: consulta autenticada, sem efeitos/N+1, conteúdo escapado e histórico sob demanda sem cache compartilhado. | Matriz HTTP, logs/HTML, consultas por volumes, Cache-Control private/no-store em HTML/fragmentos/formulários inclusive erros e browser desktop/mobile. |

## Expected blast radius

- Queries, forms, views, URLs e templates do agregado em `apps/pending_items/`; reuso dos serviços contextuais.
- Menu/contexto ativo, fragmentos de formulário/modal/histórico e testes de UI/consultas.
- Eventual helper pequeno de censo/rótulos compartilhado, somente se necessário e com regressão das superfícies existentes.
- Fixtures locais de Bootstrap/HTMX/CSS para a prova real de browser, conforme D9.
- Preservar os hooks/FSM/histórico de S1/S2 e o HTML/XLSX de censo existentes. Não alterar origem dos dados, migrar movimentações ou antecipar XLSX de S4.

## Failing-before plan

Antes do painel, acrescentar testes RED para acesso a /pendencias/, seleção dos dois modos, primeira unidade e métricas globais. Registrar jornada browser sem a ação/menu/modal necessários. Queries novas devem começar por expectativas de recorte em fixtures com mais de um episódio, e não por dados que passariam mesmo usando todo o histórico do paciente.

## Implementation constraints

Seguir `AGENTS.md` e D3/D7/D8. Estado atual e primeira unidade não se confundem. Usar o mesmo resolver conservador para lista, indicadores e futura exportação: excluir leitos conflitantes, identidade ambígua e duas abertas; deduplicar apenas repetições equivalentes. Consulta histórica explícita não é proibida por essa exclusão do agregado. Filtrar antes de agrupar, não dividir o conjunto correspondente do paciente entre páginas, capturar censo/relógio uma vez e preservar filtros/modo ao salvar.

Não duplicar regras de escrita no modal ou criar tabela de acompanhamentos. O histórico é de versões, carregado sob demanda. Usuário comum e superusuário sem grupo são leitores. Nenhum filtro modifica indicadores globais, e nenhum GET faz reconciliação/encerramento.

## Validation

### Focused validation

- `tests/unit/test_pending_items_queries.py` e `tests/integration/test_pending_items_portal.py`.
- Estender `tests/integration/test_pending_items_browser.py` usando o harness e a interceptação de assets locais já comprovados em S1; sem framework novo.
- Testar as mesmas ambiguidades/duplicatas em lista e indicadores, e diretivas private/no-store de Cache-Control em todas as novas respostas com conteúdo clínico, incluindo fragmentos e erros.
- Reexecutar regressões de menu/contexto, tela de admissões, censo e services de S1/S2.
- Provar custo de queries limitado por página/lotes, sem consulta por paciente/pendência no loop; não fixar uma contagem arbitrária dependente de detalhes irrelevantes.

### Project-required gates

Executar check, unit, integration, lint e typecheck via `AGENTS.md`; markdown lint quando documentação mudar. Browser deste slice roda na integração isolada, sem exigir portal dev implantado.

### Runtime / verification evidence

Playwright com login real de integrante e leitor, em desktop (1280×800) e mobile (390×844): menu, alternância de visões, filtros, primeira unidade, histórico recolhível e edição/finalização em modal. Demonstrar atualização de listagem/indicadores, remoção de grupo vazio e ausência de ações de escrita para leitor. Usar JS/CSS reais das versões do shell; HTML 200 ou mocks de Bootstrap/HTMX não comprovam o comportamento.

## Acceptance criteria

- [ ] R1: modos/paginação usam o mesmo recorte, excluem ocupações/episódios ambíguos e não duplicam repetições equivalentes da foto.
- [ ] R2: filtros combinados e durações passam nos testes e na interação pelo browser.
- [ ] R3: PS é primeira unidade no percurso adequado; episódio anterior/ambiguidade não contamina o resultado.
- [ ] R4: modal e histórico funcionam com auditoria; conflitos e bloqueios não causam sobrescrita nem sucesso falso.
- [ ] R5: indicadores dão 2 pacientes/média 5 dias/máximo 8 dias para casos válidos, ignoram ambíguos e não mudam com filtros nem duplicatas equivalentes.
- [ ] R6: acesso, escape, GET sem efeitos, orçamento de queries e Cache-Control private/no-store de HTML/fragmentos/formulários e erros são demonstrados.
- [ ] Desktop/mobile e validações obrigatórias passam; relatório existe.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` em conflito spec/design, decisão nova de produto/arquitetura, expansão material, compatibilidade/persistência/FSM não prevista ou risco clínico, de privacidade, segurança ou integridade. Não reconstruir primeiro setor por fonte nova nem modificar o censo inteiro para cumprir o slice. Browser ou prova responsiva indisponível é bloqueio, não aceite por HTML estático.

## Evidence report

Produzir `/tmp/sirhosp-slice-PEND-S3-report.md` conforme `AGENTS.md`: R1–R6 → evidência, arquivos/motivos, RED/GREEN, comandos/exit status, cenários/browser/artefatos sintéticos, desvios, levers e riscos reais. Não incluir dados clínicos reais ou duplicação do diff.

## Worker handoff

Implementar apenas este slice aprovado pelas referências; produzir falha prévia, menor implementação, validações e relatório. Não atualizar tasks, commitar, publicar, arquivar ou iniciar outro slice. Terminar em `READY_FOR_REVIEW` e `REPORT_PATH=/tmp/sirhosp-slice-PEND-S3-report.md`, ou `BLOCKED_NEEDS_DECISION` com evidência.
