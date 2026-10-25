# PEND-S4 — Exportação XLSX autenticada

## Identity

- Change: `track-inpatient-pending-items`.
- Task: `tasks.md`, 4.1.
- Dependência: PEND-S3 aceito.
- Estado: contrato proposto, executar somente após aprovação.

## Objective

Permitir a qualquer usuário autenticado exportar o estado atual de todas as pendências correspondentes aos filtros, uma linha por pendência, sem histórico ou arquivos clínicos residuais.

## Read first

Paths relativos à raiz do repositório:

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/changes/track-inpatient-pending-items/proposal.md`.
- `openspec/changes/track-inpatient-pending-items/design.md` — D2, D3 e D7–D9.
- `openspec/changes/track-inpatient-pending-items/specs/pending-items-portal/spec.md` — PP-02, PP-04, PP-05, PP-08 e PP-09.
- `openspec/changes/track-inpatient-pending-items/specs/inpatient-pending-items/spec.md` — PI-04 e PI-06.
- `apps/pending_items/` e queries/testes entregues pelos slices anteriores.
- `apps/services_portal/views.py::censo_export_xlsx`, `openspec/specs/censo-current-list-export/spec.md`.
- `tests/integration/test_pending_items_browser.py`, `pyproject.toml` e `compose.test.yml`.

## Requirements

| ID  | Contrato observável                                                                                                              | Evidência planejada                                                                                                                                   |
| --- | -------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | PP-08/PI-04: todo autenticado exporta, sem exigir grupo; anônimo não recebe dados.                                               | HTTP de integrante, leitor, superusuário sem grupo e anônimo; download real pelo leitor.                                                              |
| R2  | PP-02/04/08: todos os resultados do recorte conservador compartilhado, uma linha por pendência, ignorando apenas paginação/modo. | Comparar workbook/queryset nas duas visões e em várias páginas; filtros/autores, duas abertas, leitos conflitantes e duplicatas equivalentes da foto. |
| R3  | PP-05/08: colunas aprovadas, primeira unidade/fallback e estado/autoria atuais, sem versões históricas.                          | Abrir bytes com openpyxl e inspecionar cabeçalhos, valores, quantidade de linhas e datas.                                                             |
| R4  | PP-08/09: workbook válido/literal, sem arquivo clínico residual e com Cache-Control private/no-store, inclusive vazio.           | Tipos de célula com fórmulas, MIME/download, diretivas de cache, memória e ausência de writes de negócio/arquivo.                                     |

## Expected blast radius

- Módulo de exportação, endpoint e botão do agregado em `apps/pending_items/`, reutilizando queries existentes.
- Testes unitários de workbook, `tests/integration/test_pending_items_export.py` e extensão do browser.
- Documentação mínima da permissão/colunas onde necessária, sem alterar o exportador de censo.
- Sem migrations novas, biblioteca adicional, permissão restritiva nova, mudança de histórico/FSM, exportação de versões ou importação.

## Failing-before plan

Acrescentar teste RED de download por leitor e de comparação de mais resultados que uma página: o endpoint/botão XLSX de pendências ainda não existe. Antes da serialização, definir expectativas dos valores e do tipo literal de células com texto sintético potencialmente executável. Não usar somente a extensão do nome como prova de planilha correta.

## Implementation constraints

Seguir `AGENTS.md` e D8; endpoint autenticado, não restrito ao grupo. Reusar seleção/ordenação/filtros canônicos sem chamar view HTML nem concatenar o conteúdo dos grupos de paciente. Usar openpyxl/BytesIO já presentes e timezone institucional; nenhum arquivo temporário clínico no servidor.

Não exportar histórico nem aplicar limite da página visível. Não corrigir falhas por alterar o contrato da listagem ou dos indicadores. Campos vindos de usuário ou sistema fonte devem permanecer texto literal, inclusive quando iniciados por caracteres interpretáveis como fórmula.

## Validation

### Focused validation

- `tests/unit/test_pending_items_export.py` e `tests/integration/test_pending_items_export.py`.
- Cenários com zero resultados, múltiplas páginas, pendências do mesmo paciente, finalizadas selecionadas, primeira unidade desconhecida, último autor Sistema e filtros de criação/atualização.
- Provar exclusão dos mesmos casos ambíguos do painel/indicadores, deduplicação de repetições equivalentes e Cache-Control com private/no-store nos downloads com dados e vazios.
- Regressão de queries/painel e XLSX de censo, sem novas dependências.

### Project-required gates

Executar validações focadas pelo caminho oficial de `AGENTS.md`, com integração obrigatória e markdown lint quando aplicável. O controller executa adicionalmente o gate final completo e a integração após todos os slices, conforme `tasks.md`; isso não autoriza o worker a atualizar tarefas ou iniciar outro trabalho.

### Runtime / verification evidence

Pelo browser isolado, fazer login como leitor fora do grupo, aplicar filtros no agregado por paciente e baixar o XLSX pelo controle real. Ler o arquivo baixado e confrontar com o resultado esperado além da página atual. Repetir em modo por pendência e confirmar a mesma seleção. Registrar caminho de evidência apenas com fixtures sintéticas; não usar portal implantado.

## Acceptance criteria

- [ ] R1: leitor e superusuário sem grupo exportam, mas continuam sem permissão de escrita; anônimo não recebe arquivo.
- [ ] R2: filtros/modos/todas as páginas correspondem ao workbook, uma linha por pendência, excluindo ambiguidades e sem duplicação por foto equivalente.
- [ ] R3: colunas, primeira unidade, estados/autores e datas são corretos, sem histórico exportado.
- [ ] R4: workbook vazio/válido, texto literal, ausência de resíduo/efeito em negócio e diretivas private/no-store de Cache-Control estão demonstrados.
- [ ] Download real e validações obrigatórias passam; relatório existe.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` diante de contradição, nova decisão de produto/arquitetura, expansão material, quebra de compatibilidade, persistência/FSM não prevista ou risco clínico, de segurança, privacidade ou integridade. Não restringir exportação ao grupo, vazar histórico ou persistir arquivo no servidor como workaround. Falha de verification confiável bloqueia o aceite.

## Evidence report

Produzir `/tmp/sirhosp-slice-PEND-S4-report.md` conforme `AGENTS.md`, incluindo R1–R4 → evidência, arquivos/motivos, RED/GREEN, comandos/exit status, download/browser, desvios, levers e riscos reais, sem dados reais ou cópia do diff.

## Worker handoff

Implementar somente este slice aprovado, com falha prévia, menor mudança, validações e relatório. Não atualizar tasks, commitar, publicar, arquivar ou iniciar outro slice. Terminar com `READY_FOR_REVIEW` e `REPORT_PATH=/tmp/sirhosp-slice-PEND-S4-report.md`, ou `BLOCKED_NEEDS_DECISION` com evidência.
