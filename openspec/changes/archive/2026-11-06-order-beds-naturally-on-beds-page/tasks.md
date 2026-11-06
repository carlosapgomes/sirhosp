# Tasks

## 1. Ordenação natural dos leitos em /beds/

- [x] 1.1 Registrar a evidência de falha antes: testes de ordenação
      natural (v5 pacientes, v5 operacionais, v4 posições, legado posições
      e lista de leitos do paciente) falhando contra o código anterior —
      verificar com `uv run pytest --ds=config.test_settings -q
tests/unit/test_bed_status_view.py::TestBedStatusBedOrdering`
- [x] 1.2 Extrair a chave de ordenação natural para
      `apps/census/bed_ordering.py` e reexportá-la em
      `apps/statistics_reports/events.py` — verificar pelos testes de
      ordenação do relatório de estatísticas continuarem passando
- [x] 1.3 Aplicar a chave às listas do collapsible em
      `apps/census/occupancy.py` (v5: pacientes, operacionais, incompletas;
      v4 e legado: posições) — verificar com a classe
      `TestBedStatusBedOrdering` passando

## 2. Verificação

- [x] 2.1 Rodar `./scripts/test-in-container.sh quality-gate` e
      `./scripts/test-in-container.sh integration` — verificar ambos
      passando no estado final
