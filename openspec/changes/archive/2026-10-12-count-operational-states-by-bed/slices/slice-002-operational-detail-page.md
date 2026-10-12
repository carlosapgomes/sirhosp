# Slice 002 — Página de detalhe por setor

## Objetivo

Criar a página autenticada de detalhe dos estados operacionais, vinculada
ao measurement exato do card, mostrando por setor os casos de divergência,
repetição, ocupado + estado e linhas sem leito, com fechamento aritmético
contra o card e sem dados nominais.

## Requisitos cobertos

Delta `specs/bed-status-capacity-view/spec.md` (requirement ADDED
`V5 operational-states detail page`), todos os cenários:

- Detail is pinned to the exact measurement photo;
- Stale photo is flagged;
- Per-sector breakdown is complete;
- Arithmetic closes with the summary card;
- Historical row-based photo is explained;
- Detail page carries no nominal data;
- Anonymous access remains protected.

## Referências necessárias

- `AGENTS.md` — políticas globais e quality gate.
- `openspec/changes/count-operational-states-by-bed/design.md`
  (decisões D2 e D4).
- Slice 001 (classificador compartilhado e chaves schema 4 precisam estar
  aceitos).
- Código: `apps/census/views.py` (`bed_status_view` como padrão de view),
  `apps/census/urls.py`, `apps/census/occupancy.py`
  (`build_units_presentation`, `_v5_real_totals`), templates
  `census/bed_status.html` (padrão visual e de seções) e base do portal.
- `docs/dev-verification.md` — janela dev, dataset fictício, workers
  parados.
- Testes de referência: `tests/unit/test_bed_status_view.py`.

## Acceptance criteria

1. Rota `beds/estados-operacionais/?measurement=<id>` responde apenas
   autenticado; anônimo é redirecionado ao login.
2. Measurement inexistente ou não `occupancy-v5` responde 404, sem
   renderizar evidência operacional.
3. A página renderiza exclusivamente a foto do measurement informado
   (validado `occupancy-v5`), com horário de captura no cabeçalho; quando
   existe censo mais recente, exibe aviso e mantém a foto pedida.
4. Evidence agrupada por `(setor_codigo, setor)`: leitos inequívocos por
   estado, leitos divergentes com o conjunto de estados informados,
   repetidos colapsados (leito + estado + número de linhas), casos
   ocupado + estado, contagem de linhas sem leito.
5. Para measurement schema 4, a soma dos leitos inequívocos por estado
   iguala os badges do card da mesma foto; a contagem de divergentes
   iguala a linha do card (teste automático sobre a mesma foto
   sintética).
6. Para measurement schema 3, a página rotula que os badges daquela foto
   contaram linhas e lista os casos que explicam a diferença.
7. Nenhum nome de paciente ou prontuário aparece no HTML renderizado em
   nenhum caso (teste de ausência sobre payload sintético).
8. O link de acesso existe no card `Estados operacionais informados` da
   `/beds/` e carrega o measurement da foto corrente.
9. Custo de query constante: snapshots carregados em uma query do run; sem
   N+1 perceptível (verificação no relatório).

## Expected blast radius

- `apps/census/views.py` (nova view);
- `apps/census/urls.py` (nova rota);
- `apps/census/templates/census/bed_operational_detail.html` (novo);
- `apps/census/templates/census/bed_status.html` (link no card);
- `apps/census/occupancy.py` (apenas exposição/reuso do classificador do
  slice 001, se necessário);
- `tests/unit/test_bed_status_view.py` (ou arquivo novo de view).

Sem models, migrations ou persistência nova.

## Estratégia de teste/verification

- TDD de view/template com fixtures sintéticas (cenários 1–6).
- Verification de produto na janela dev autorizada (dataset fictício,
  workers parados, conforme `docs/dev-verification.md`): censo sintético
  com os quatro casos problemáticos; conferência manual card ↔ detalhe;
  evidência em `/tmp` sem dados reais.

## Comandos obrigatórios

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh quality-gate
./scripts/test-in-container.sh integration   # fronteiras de view/urls tocadas
./scripts/markdown-lint.sh                   # para todo .md alterado
```

## Condições de bloqueio

- Slice 001 não aceito.
- Necessidade de persistir identidade de linha (nome/prontuário) para
  renderizar o detalhe — o contrato exige evidência não nominal.
- Impossibilidade de executar a verification dev com dataset fictício
  confirmado.
