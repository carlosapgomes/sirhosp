# Tasks

## 1. Remoção do campo de busca — slice `slice-001-remover-busca-tipo.md`

Contrato do slice: `slices/slice-001-remover-busca-tipo.md`. Políticas:
`AGENTS.md` (não repetidas aqui).

- [x] 1.1 Ajustar testes primeiro e registrar evidência RED: HTTP passa a
      afirmar ausência de `type_search`/`id_type_search`; browser passa a
      afirmar `count == 0` para `#id_type_search` e reescreve a jornada RNM
      por seleção direta com rótulo (categoria automática preservada).
- [x] 1.2 Implementar a menor mudança: remover campo, label e hint do
      template; remover termo de busca do JS preservando o filtro por
      categoria e o listener categoria ← tipo; remover
      `aria-describedby="pending-type-hint"` de `forms.py`; layout da
      coluna da categoria ajustado para largura total.
- [x] 1.3 Validar: browser focado, `./scripts/test-in-container.sh
    quality-gate`, `./scripts/test-in-container.sh integration`,
      markdown lint nos `.md` tocados, `git diff --check` e
      `git diff HEAD --check`.
- [x] 1.4 Produzir relatório em
      `/tmp/sirhosp-slice-REMOVE-TYPE-SEARCH-S1-report.md` e retornar
      `READY_FOR_REVIEW`.
