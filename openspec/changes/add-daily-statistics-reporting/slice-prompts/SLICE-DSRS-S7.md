# SLICE-DSRS-S7 — XLSX e auditoria de exportação

## Handoff de entrada

Você inicia com contexto zero após DSRS-S6 aceito. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, `proposal.md`, as decisões 8–10 de `design.md`, os
requisitos de XLSX e auditoria, e os relatórios S1–S6 em `/tmp`. Implemente
somente exportação da revisão exibida e log agregado. Não persista arquivos e
não adicione correções manuais.

## Objetivo

Gerar um XLSX seguro e reproduzível da mesma projeção da página, com uma folha
por setor, todas as seções fixas e registro de usuário/data/revisão somente
depois de o arquivo estar pronto para ser servido.

## Requisitos verificáveis

- **R1:** exportação exige `export_daily_statistics`, independente da permissão
  de consulta, e usa `private, no-store`.
- **R2:** workbook contém uma folha por agrupamento oficial, nome válido/único e
  nome completo dentro da folha.
- **R3:** cada folha contém, na ordem, internações, transferências de entrada,
  óbitos, transferências de saída, altas, eventos com origem ou destino não
  identificado e pacientes finais.
- **R4:** seções vazias permanecem com quantidade zero; linhas usam mesmos
  campos e ordenação natural da página.
- **R5:** textos iniciados por `=`, `+`, `-` ou `@` não são interpretados como
  fórmula.
- **R6:** workbook é criado em memória, não deixa arquivo persistido e usa nome
  seguro baseado somente na data/revisão.
- **R7:** sucesso registra usuário, horário, data selecionada, revisão e
  contagens agregadas; falha anterior à resposta não registra sucesso.
- **R8:** logs e auditoria não armazenam nome, prontuário ou conteúdo das linhas.

## Escopo e blast radius

```yaml
expected_files:
  - apps/statistics_reports/models.py
  - apps/statistics_reports/migrations/0003_statistics_export_log.py
  - apps/statistics_reports/export.py
  - apps/statistics_reports/views.py
  - apps/statistics_reports/urls.py
  - apps/statistics_reports/templates/statistics_reports/daily_report.html
  - tests/integration/test_daily_statistics_export.py
allowed_incidental_files: []
out_of_scope:
  - CSV, PDF ou arquivos persistidos
  - mudanças no materializador de eventos
  - ajustes manuais ou approval flow
  - deploy/systemd e produção
```

Limite: sete arquivos. Se DSRS-S4 já tiver usado o número `0003`, ajuste apenas
o número da migration, sem reescrever migrations aplicadas. Pare se a geração
exigir nova dependência ou armazenamento em disco.

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1 | view/urls | permissão separada e headers |
| R2–R6 | `export.py` | abrir workbook, folhas, seções, sort e segurança |
| R7–R8 | model/migration/view | sucesso/falha e conteúdo agregado do log |

## Plano de testes

### RED

Adicione os testes primeiro e execute:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_daily_statistics_export.py
```

Falha esperada: endpoint/exporter/log inexistentes.

### GREEN / verificação local

Implemente o mínimo e repita o RED. Depois:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_daily_statistics_page.py
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

## Critérios de aceitação

- [ ] R1–R8 cobertos por RED→GREEN.
- [ ] XLSX reaberto por `openpyxl` preserva estrutura e texto seguro.
- [ ] Nenhum arquivo ou PHI fica em log/auditoria.
- [ ] Relatório criado em `/tmp/sirhosp-slice-DSRS-S7-report.md`.
- [ ] Migration, checks e Markdown alterado passam.
