# S4 — XLSX estruturado

## Identity e objetivo

- ID: `STRUCT-PEND-S4`.
- Change: `structure-inpatient-pending-items`.
- Tasks: [grupo 4](../tasks.md#4-s4--exportação-estruturada).
- Dependência: S3 aceito; contrato proposto, execução depende de aprovação.
- Objetivo: exportar todos os resultados filtrados com uma linha por pendência,
  detalhes estruturados e datas utilizáveis no Excel.

## Read first

- `AGENTS.md`, `PROJECT_CONTEXT.md` e `openspec/config.yaml` na raiz.
- [Proposal](../proposal.md), inclusive quebra do contrato de células;
  [catálogo](../catalog.md) e [design D6–D9](../design.md).
- [Delta PP-08](../specs/pending-items-portal/spec.md) e
  [delta PI-09/10](../specs/inpatient-pending-items/spec.md).
- Spec atual `openspec/specs/pending-items-portal/spec.md`, PP-02/05/09, e
  [contrato S3](slice-003-painel-categorizado.md).
- `apps/pending_items/{export,views_export,queries}.py`.
- `tests/unit/test_pending_items_export.py`;
  `tests/integration/test_pending_items_export.py` e
  `tests/integration/test_pending_items_browser.py`.

## Requirements e evidência planejada

| ID  | Comportamento e fonte                                            | Evidência                                                            |
| --- | ---------------------------------------------------------------- | -------------------------------------------------------------------- |
| R1  | Contrato de 23 colunas, estado atual e uma linha por item, PP-08 | Workbook aberto, cabeçalho exato e IDs/valores por perfil            |
| R2  | Datas nativas, timezone e ausências corretas, PP-08/PI-09        | Round-trip openpyxl com datas civis, instantes e RNM desconhecida    |
| R3  | Mesmos filtros/recorte, sem paginação, PP-04/08                  | Integração com mais de uma página e modos/categorias diversos        |
| R4  | Texto literal, cache e memória, PP-08/09                         | Strings de fórmula, registro com zeros e resposta/efeitos observados |
| R5  | Arquivo usável e download real, PP-08                            | Browser, autofiltro, primeira linha congelada e abertura do download |

## Expected blast radius

`export.py`, `views_export.py` e testes de exportação/browser. Adaptar tipos de
serialização sem criar outro resolvedor de pacientes ou filtros. Pequeno helper
local é permitido se representar uma regra compartilhada concreta.

Não modificar persistência, catálogo, FSM, permissões, fontes clínicas ou
recorte. A mudança de colunas/tipagem é a quebra prevista; não criar segunda
versão de endpoint ou formato legado paralelo.

## Failing-before plan

Adicionar testes que abram o workbook atual e falhem por:

- ausência de categoria, IDs e detalhes no cabeçalho/dados;
- datas exportadas como texto em vez de datas;
- ausência de autofiltro/cabeçalho fixo.

Registrar RED antes de ajustar o exportador. Manter como regressão os testes
de fórmula, autorização, recorte e ausência de histórico; adaptar somente as
expectativas de colunas/tipos explicitamente alteradas nesta change.

## Implementation constraints

Seguir `AGENTS.md`, D7 e contrato exato de PP-08. Não testar que todas as células
são strings: somente textos devem ser literais; datas são nativas. Não usar
formatação automática de texto como fórmula. Identificação do paciente é
texto para preservar zeros. Datas civis não sofrem conversão de timezone;
instantes usam o fuso institucional antes de remover timezone para Excel.

Campos não aplicáveis são vazios, mas booleanos aplicáveis desconhecidos
informam Não informado. Não concatenar várias pendências em uma célula nem
exportar revisões ou observações históricas.

## Validation

### Focused validation

Executar os caminhos oficiais `unit` e `integration` de
`./scripts/test-in-container.sh`, com testes de workbook, HTTP e download;
executar checks estáticos pertinentes conforme `AGENTS.md`. O controller
executa novamente o quality-gate e integração finais após o aceite, conforme
grupo 5 de tasks; resultados anteriores a reparos não comprovam estado final.

### Project-required gates

Seguir os gates estáticos, Markdown e revisão de `AGENTS.md`. O gate integrado
do controller não substitui os testes/verificação de responsabilidade de S4.

### Runtime / verification

Jornada sintética no live_server: criar RNM e tratamento no mesmo episódio,
editar uma data, finalizar outra pendência, exportar em ambas as visões com
categoria/status e abrir os downloads com openpyxl. Conferir IDs, valores,
células de data, strings literais, primeira unidade, seleção completa e vazio
com cabeçalho. Cobrir os quatro perfis, inclusive assinatura, nas fixtures de
workbook/HTTP; não limitar a prova a RNM e tratamento.

Separar duas evidências: a serialização do rótulo Sistema usa fixture isolada,
como já faz a suíte de exportação; a saída confirmada real fecha a internação
e a exclui do XLSX atual, mesmo com status=all. Seu histórico permanece no
contexto, conforme S2/S3. Não reabrir artificialmente a internação nem ampliar
o recorte para fazer aparecer uma saída no download end-to-end.

Não exige Microsoft Excel instalado ou portal implantado. Não usar dados ou
arquivos de produção.

## Acceptance criteria

- [ ] R1: cabeçalho e linhas correspondem exatamente ao contrato de PP-08.
- [ ] R2: datas e booleanos distinguem valor conhecido, desconhecido e não aplicável.
- [ ] R3: filtros, modos, ambiguidade e paginação produzem o recorte correto.
- [ ] R4: textos não executam fórmulas; cache e ausência de resíduos são preservados.
- [ ] R5: download real abre corretamente e possui autofiltro/cabeçalho fixo.
- [ ] Gates focados e relatório demonstram o estado final deste slice.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se houver necessidade de mudar colunas ou
semântica aprovadas, expor novos dados, persistir arquivos sensíveis, alterar
recorte/identidade ou ampliar escopo materialmente. Falha de browser/ambiente
que impeça verification também é bloqueio, não motivo para declarar sucesso.

## Evidence report e handoff

Produzir `/tmp/sirhosp-slice-STRUCT-PEND-S4-report.md` conforme `AGENTS.md`, com
R1–R5 -> evidência, arquivos, RED/GREEN, comandos, download verificado, desvios,
levers, riscos e nota operacional sobre a mudança do XLSX. Registrar qual
prova veio de serialização isolada e qual veio da jornada real, sem confundi-las.

Quando autorizado, implementar somente este slice a partir das referências.
Não atualizar tasks, criar commit, push, merge, archive ou executar outro
slice. Retornar `READY_FOR_REVIEW` com `REPORT_PATH`, ou `BLOCKED_NEEDS_DECISION`
com evidências.
