# Tasks

Cada slice possui contrato próprio em `slices/`. Executar na ordem; o
controller (`/slice-loop` ou `/change-loop`) só avança após aceite do
reviewer. Políticas globais em `AGENTS.md` — não repetidas aqui.

## 1. Preflight

- [x] 1.1 Registrar `BASE_REF`, confirmar working tree adequada e rodar
  `./scripts/test-in-container.sh quality-gate` como baseline; registrar
  resultado no relatório do primeiro slice

## 2. Slice 001 — Estados operacionais por leito (materialização + card)

Contrato: `slices/slice-001-operational-positions.md`

- [x] 2.1 Verificar consumidores existentes de
  `operational_rows_by_status` antes de qualquer edição (busca no repo);
  consumidores já mapeados e a preservar: card e ponte de reconciliação
  do template `bed_status.html`; resultado registrado no relatório —
  qualquer consumidor adicional é condição de bloqueio
- [x] 2.2 RED: testes unitários de materialização provando contagem por
  leito (repetido colapsa; divergente excluído e contado em leitos e
  linhas; ocupado + marcador diverge; variantes do mesmo estado
  concordam; sem leito fora do badge; fechamento aritmético por linhas
  contra `operational_rows_by_status`; schema 4 com chave antiga
  preservada) rodando focado em container e falhando
- [x] 2.3 GREEN: extrair o classificador por chave compartilhado, alterar
  `_calculate_v5`, allowlist e `_reconciliation_v5_json` (schema 4);
  `_v5_real_totals` com fallback schema 3 sem híbridos; testes focados +
  `./scripts/test-in-container.sh unit` verdes
- [x] 2.4 RED→GREEN: testes de view/template do card (badges por leito,
  linha condicional de divergentes, foto schema 3 mantém números por
  linha, nada nominal)
- [x] 2.5 Gerar `/tmp/sirhosp-slice-001-report.md` e validar Markdown
  alterado com `./scripts/markdown-lint.sh`

## 3. Slice 002 — Página de detalhe por setor

Contrato: `slices/slice-002-operational-detail-page.md`

- [x] 3.1 RED: testes de view da página de detalhe (vínculo ao measurement
  exato, agrupamento por setor, casos por setor, fechamento aritmético
  com o card na mesma foto, rótulo de semântica histórica para schema 3,
  aviso de foto não mais recente, anonimato redirecionado, ausência de
  nome/prontuário no payload) falhando
- [x] 3.2 GREEN: view `@login_required`, rota
  `beds/estados-operacionais/`, template
  `census/bed_operational_detail.html` e link no card, reusando o
  classificador do slice 001; testes focados verdes
- [ ] 3.3 Verification de produto com dataset sintético no portal dev
  (portal implantado, workers parados): cenário com leito repetido,
  divergente, ocupado+estado e sem leito; conferir card ↔ detalhe;
  evidência sem dados reais

  > Deferrido pelo operador (Opção B, 2026-10-12): slice aceito com
  > evidência de código (reviewer `OK with notes`, gates verdes);
  > verification de produto pendente para janela dev futura.
- [x] 3.4 Gerar `/tmp/sirhosp-slice-002-report.md` e validar Markdown
  alterado com `./scripts/markdown-lint.sh`

## 4. Gate final

- [x] 4.1 `./scripts/test-in-container.sh quality-gate` no estado final;
  `./scripts/test-in-container.sh integration` quando exigido pelas
  fronteiras tocadas; registrar evidências

  > Executado no estado final (unit 4238/check/ruff/mypy ✅; integration
  > 950 ✅ + 2 falhas pré-existentes em WIP não commitado de outra sessão,
  > comprovadas no base ref — não atribuíveis à change). Evidência:
  > /tmp/sirhosp-final-gate.log.
