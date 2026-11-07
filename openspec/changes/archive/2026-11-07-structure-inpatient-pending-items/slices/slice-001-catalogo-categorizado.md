# S1 — Catálogo categorizado utilizável

## Identity e objetivo

- ID: `STRUCT-PEND-S1`; change: `structure-inpatient-pending-items`.
- Tasks: [grupo 1](../tasks.md#1-s1--catálogo-categorizado).
- Estado: proposto; executar somente após aprovação da change e deste contrato.
- Objetivo: permitir que o administrador mantenha o catálogo categorizado e
  que a equipe identifique seus tipos nos fluxos existentes, sem perder dados.

## Read first

- `AGENTS.md`, `PROJECT_CONTEXT.md` e `openspec/config.yaml` na raiz.
- [Proposal](../proposal.md), [catálogo completo](../catalog.md) e
  [design D1, D3 (enforcement), D4, D8 e D9](../design.md).
- [Delta PI-02/06/10](../specs/inpatient-pending-items/spec.md).
- Spec atual `openspec/specs/inpatient-pending-items/spec.md`, PI-03–08.
- `apps/pending_items/models.py`, `admin.py`, `forms.py`, `services.py` e
  `migrations/0001_initial.py`, `migrations/0002_bootstrap_outro_group.py`.
- Templates de seleção de tipo e histórico em
  `apps/pending_items/templates/pending_items/`.
- `tests/integration/test_pending_items_http.py::TestAdminCatalog`,
  `tests/unit/test_pending_items_services.py` e
  `tests/integration/test_pending_items_browser.py`.
- Helpers `_ensure_bootstrap` em
  `tests/integration/test_pending_items_browser.py` e
  `tests/integration/test_pending_items_exit_lifecycle.py`: recriam Outro após
  flush e precisam da categoria e do contrato fixo, não apenas name/slug.

## Requirements e evidência planejada

| ID  | Entrega observável e fonte                                      | Evidência planejada                                                                                                                             |
| --- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | Banco novo recebe 10 categorias e as 46 entradas exatas, PI-02  | Integração compara identidades, vínculos, perfis e capacidades com catalog.md; CATE único e duas RNM distintas                                  |
| R2  | Admin mantém catálogo com identidade/contrato protegidos, PI-02 | Alteração de slug negada mesmo sem uso; contrato de tipo usado só em revisão e contrato fixo de Outro protegidos; constraints locais de D3      |
| R3  | Upgrade/carga têm resultado binário sem perda, PI-02/10         | Cada linha da matriz D8 em contexto inicial/pós-S1; colisões com rollback; reaplicar após renomeação/customização; PKs/FKs/conteúdo preservados |
| R4  | Classificação nova é auditável sem inventar passado, PI-06      | Snapshot com nomes/slugs de categoria e tipo, perfil, capacidade RNM e observação obrigatória; renomear não muda revisão anterior               |
| R5  | Tipos homônimos são distinguíveis no fluxo atual, PI-02         | Seletores de cadastro/edição mostram Categoria > Tipo, inclusive as duas RNM; regressão dos fluxos existentes                                   |

## Estado entregue e fronteira

Este slice entrega uma jornada administrativa completa: abrir admin, manter
categoria/tipo, selecionar esse tipo no portal atual e consultar sua autoria
e classificação histórica. Não é uma entrega apenas de migrations.

Os formulários de pendência ainda exigem observação como hoje. Perfis são
metadados reais do catálogo; campos complementares do item e observação
condicional serão entregues juntos em S2. Não antecipar colunas de agendamento,
tratamento, assinatura, contraste ou sedação nos itens/revisões. Não acrescentar
flags de ativação para encobrir essa sequência. O conjunto só estará pronto
para entrega final depois de todos os slices e gates.

## Expected blast radius

Models/migrations/admin do catálogo, metadados de classificação em revisões,
escritores existentes de revisões, rótulos dos seletores e renderização
histórica correspondente; testes desses caminhos. Ajustar fixtures existentes
para categoria/perfil quando necessário, sem reescrever regras não afetadas.
Em particular, adaptar `_ensure_bootstrap` de browser e exit_lifecycle para
recriar/reutilizar categoria outras-pendencias e Outro com seu contrato completo
após flush. Jornadas que precisam do catálogo inteiro usam a carga no contexto
pós-S1, não fingem uma nova adoção de legado. Não criar framework genérico de
fixtures para esse ajuste.

Preservar descrição obrigatória nesta etapa, permissões, transações, ordem de
locks, FSM e integrações de saída/merge. Não alterar o recorte, filtros ou
colunas XLSX. Expansão necessária deve ser justificada; redesign exige decisão.

## Failing-before plan

Usar TDD nos seams existentes antes de implementar:

- Estender TestAdminCatalog para criar categoria/tipo e verificar os dois
  rótulos RNM; esperar ausência dos controles/classificação no código atual.
- Testar carga exata, slug imutável e contrato de tipo referenciado somente em
  revisão; esperar catálogo incompleto e guardas ausentes, não só import.
- Testar Outro sem uso com tentativa de mudar categoria, perfil, habilitação
  RNM ou obrigatoriedade; esperar rejeição por contrato fixo.
- Exercitar as constraints locais de S1 em D3 por escrita direta no banco;
  registrar RED/GREEN sem substituir a proteção administrativa por testes de UI.
- Testar criação de revisão por endpoint atual e renomeação posterior do
  catálogo; esperar ausência da classificação observada no histórico.

Registrar RED/GREEN. Upgrade e reaplicação terão testes de integração com
estado histórico sintético, sem consultar ou copiar produção.

## Implementation constraints

Seguir `AGENTS.md` e a menor mudança correta. Usar perfis/identidades de
catalog.md e a matriz exata de D8: nome isolado não prova identidade; adoção
inicial exige slug+nome canônicos exatos. Não inferir fase de carga pelo nome
atual nem executar adoção de legado na reaplicação. Slugs são imutáveis e
referência por item ou revisão protege também a categoria do tipo; Outro mantém
o contrato inteiro mesmo sem uso. Revisões antigas mantêm metadados novos
desconhecidos ausentes; novas
revisões registram classificação também em finalizações humanas e do Sistema.
Falha de snapshot continua revertendo a operação inteira. Não transformar
cadastro de categoria em permissão para editar pendências fora do grupo atual.

## Validation

### Focused validation

Cobrir R1–R5 em testes de catálogo, admin, migrations, services e HTTP. Executar
`check`, `unit` e `integration` pelo wrapper oficial de `AGENTS.md`, conferindo
que nenhuma suíte existente fica quebrada para ser corrigida por outro slice.
No runner, conferir migrations com
`uv run --no-sync python manage.py makemigrations --check --dry-run`.

### Project-required gates

Aplicar gates estáticos, Markdown e protocolo de revisão de `AGENTS.md`.
Esta skill não executa nem marca esses gates como cumpridos.

### Runtime / verification

No live_server sintético, autenticar administrador, manter um tipo e comprovar
sua seleção contextualizada no portal por integrante autorizado. Usar um tipo
Registro simples para cadastrar com observação, abrir histórico e confirmar
que renomeação não reescreve o nome observado. Verificar também RNM homônimas
por seus rótulos, sem exigir campos estruturados ainda não entregues.

## Acceptance criteria

- [ ] R1: catálogo novo corresponde à lista, não apenas à contagem de entradas.
- [ ] R2: slugs, categoria/contrato de tipo histórico e contrato fixo de Outro estão protegidos; constraints de S1 rejeitam estados locais inválidos.
- [ ] R3: todos os casos de D8 têm resultado esperado; rollback/preservação de customizações e helpers após flush estão demonstrados.
- [ ] R4: snapshots contêm os sete metadados de D4; novos campos permanecem desconhecidos nas versões antigas.
- [ ] R5: seletores distinguem homônimos e os fluxos anteriores continuam funcionando.
- [ ] Evidência de runtime, gates focados e relatório correspondem ao estado final.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se colisão exigir decidir significado,
descartar dados ou fundir tipos; se houver contradição de spec/design, mudança
não prevista de arquitetura/persistência/FSM/permissão, risco de integridade,
segurança ou privacidade, escopo material novo ou infraestrutura bloqueada.

## Evidence report e worker handoff

Produzir `/tmp/sirhosp-slice-STRUCT-PEND-S1-report.md` conforme `AGENTS.md`, com
R1–R5 -> evidência, RED/GREEN, comandos/resultados, runtime, arquivos, desvios,
levers e riscos reais. Falha de browser/asset não é prova de produto.

Quando autorizado, implementar somente este slice usando as referências.
Não atualizar tasks, criar commit, push, merge, archive ou iniciar outro slice.
Terminar com `READY_FOR_REVIEW` e `REPORT_PATH`, ou `BLOCKED_NEEDS_DECISION`
com evidências e decisão necessária.
