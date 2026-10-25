# Tasks — `rename-enf-2b-card-display-name`

## 1. RCD-S1 — Catálogo v6 (rename ENF-2B-CARD) + testes de contrato

- [x] 1.1 Árvore limpa; `BASE_REF` = `765c186` registrado; baseline oficial
      registrado (`./scripts/test-in-container.sh unit` — 3591 passed no
      commit base) ANTES de editar.
- [x] 1.2 RED: testes v6 novos em `tests/unit/test_sector_capacity_catalog.py`
      (apenas adições: constantes/helpers + testes) falhando pelo motivo
      certo — arquivo `sector_capacity_catalog_v6.json` inexistente
      (`FileNotFoundError`), sem quebrar testes v3/v4/v5 existentes.
- [x] 1.3 GREEN: criar `apps/census/data/sector_capacity_catalog_v6.json`
      conforme design D2 (cópia v5 + rename + `source_reference` próprio) —
      máximo 2 arquivos no diff.
- [x] 1.4 Verificação local: `tests/unit/test_sector_capacity_catalog.py`
      completo verde no container (158 passed; contratos v3/v4/v5 e
      `EXPECTED_DISPLAY_NAMES` intactos); `ruff check` exit 0 e formatter
      sem drift incremental (drift pré-existente do BASE_REF, precedente
      Emenda B).
- [x] 1.5 Relatório `/tmp/sirhosp-slice-RCD-S1-report.md` (RED/GREEN, snippets
      antes/depois, comandos + exit codes, SHA-256 do v6
      `3f7a02ea3637a09e4a4b58c4c1139e44b0302d75b6b04555cfb6e30b70d8cabb`,
      handoff do verificador); 1.1–1.5 marcados após verde. Review round 1:
      `Merge verdict: OK with notes`, zero findings.

## 2. RCD-S2 — Pino de caracterização `/beds` (título + ordenação alfabética)

- [x] 2.1 Novo teste de caracterização em `tests/unit/test_bed_status_view.py`
      (apenas adições, espelhando
      `test_cardio_shared_group_two_sources_capacity_once`): título exato
      `Enfermaria 2B Cardio` e posição junto dos pares `Enfermaria 2…` na
      ordenação por título (`test_cardio_renamed_group_sorts_with_enfermaria_2b_peers`,
      +64 linhas).
- [x] 2.2 Evidência de caracterização: teste verde no container + controle de
      mutação registrado (baseline exit 0 → ordem invertida exit 1 → reversão
      exit 0). RED-TDD clássico não se aplica (sem código de produção a
      escrever) — justificativa no slice.
- [x] 2.3 `ruff check` exit 0; formatter sob Emenda A (tasks §7): prova de
      zero drift incremental (50/50 hunks do BASE_REF, nenhum hunk nas
      adições); arquivo completo 113 passed no container; relatório
      `/tmp/sirhosp-slice-RCD-S2-report.md`; 2.1–2.3 marcados após verde.
      Review: round 1 `BLOCK` (1×P1 formatação) → Emenda A + prova → round 2
      `Merge verdict: OK with notes`.

## 3. RCD-S3 — Runbook de publicação + prova local de dry-run

- [x] 3.1 `activation-runbook.md` do change completo (pré-condições, comandos
      exatos com data futura, idempotência, pós-condições, proibições/rollback)
      — revisado contra o comando real executado; nenhum ajuste necessário.
- [x] 3.2 Prova local: `activate_sector_capacity_catalog --dry-run` do v6 em
      container com data futura distante (`2099-01-01`) — exit 0, totais
      43/48/47, 39 standard, 4 unrated, 666/666, nada persistido
      (`CapacityCatalogVersion`/`CapacityGroupDefinition` 0 → 0; a cobertura
      de aliases 48/48 fica comprovada pelos testes de contrato do S1 — o
      comando não imprime essa métrica no stdout).
- [x] 3.3 `./scripts/markdown-lint.sh` sem erros nos `.md` do change;
      relatório `/tmp/sirhosp-slice-RCD-S3-report.md` (saída integral do
      dry-run). Review round 1: `Merge verdict: OK`, zero findings.

## 4. Verificação final do change

- [x] 4.1 Verificação independente satisfeita slice a slice por reviewer
      read-only de contexto fresh: RCD-S1 round 1 `OK with notes` (zero
      findings); RCD-S2 round 1 `BLOCK` (1×P1 formatação) → Emenda A + prova
      → round 2 `OK with notes`; RCD-S3 round 1 `OK` (zero findings).
- [x] 4.2 `./scripts/test-in-container.sh quality-gate` (check + unit +
      lint + mypy) exit 0; mypy "Success: no issues found in 416 source
      files"; unit **3601 passed** = baseline 3591 + 9 (S1) + 1 (S2);
      integration **701 passed** (suíte completa).
- [x] 4.3 `openspec validate rename-enf-2b-card-display-name --strict`
      válido; `./scripts/markdown-lint.sh` 0 erros (785 arquivos).
- [x] 4.4 Diff acumulado 765c186..HEAD revisado: 3 arquivos, +847/−0
      (JSON v6 novo + adições em 2 arquivos de teste); sem PHI (única
      ocorrência dos termos é a asserção de marcadores proibidos no teste
      novo); catálogos históricos (initial/corrected/v3/v4/v5)
      byte-preserved (0 linhas de diff); nenhum arquivo de produção alterado.

## 5. Ação operacional pós-deploy (operador — fora do gate de código)

- [x] 5.1 Com o release deployado e saudável em produção, operador publica o
      v6 conforme `activation-runbook.md`, com `--effective-from` na data
      futura aprovada (dry-run → publicar → retry idempotente).
      — Executado em 2026-09-22 pelo agente sob supervisão do operador
      (pane 9 tmux, root@eon): deploy `v0.1.0-rc.30` (drenagem 655 → 0 0 em
      ~19 min, backup 899.998.675 bytes validado, `No migrations to apply.`,
      smokes OK incl. `beds/` 302); SHA-256 do v6 conferido na imagem;
      dry-run `2026-09-23` → `validado (dry-run)` 43/48/47/39/4/666/666;
      publicação → linha única `2026-09-23 3f7a02ea3637 occupancy-v5
    groups=43`; retry → `já publicado (idempotente)`; produtores
      retomados sem erros. Evidências:
      `docs/releases/2026-09-22_v0.1.0-rc.30.md`.
- [x] 5.2 No primeiro dia local da vigência: confirmar que o censo do dia usa
      v6 e que `/beds` exibe `Enfermaria 2B Cardio` junto das demais
      enfermarias do 2º andar; dias anteriores preservam o rótulo antigo.
      (Confirmação do operador 2026-10-21 + verificação read-only em
      produção: v6 `effective_from=2026-09-23` ativa; grupo do catálogo 6
      `Enfermaria 2B Cardio`; catálogos 1–5 preservam
      `Cardioclinica / Enfermaria 2B Cardio`.)

## 6. Revisão do plano (pré-implementação, 2026-09-22)

Ciclo de revisão independente por reviewer read-only (contexto fresh) sobre
os artefatos deste change, antes de qualquer implementação:

- **Round 1 — `Merge verdict: BLOCK`** (2×P1, 2×P2): F-01 (P1) dry-run não
  imprime a métrica de aliases 48/48 (ela vive em `ActivationResult`, não no
  stdout — `activate_sector_capacity_catalog.py:63-77`); F-02 (P1) faltava
  teste explícito para `source_reference` (distinto, ≤255, sem marcadores
  sensíveis); F-03 (P2) âncora do sort era `:4276`, correto é `:4195`
  (legados `:3369`/`:3642`); F-04 (P2) documentar que o pino de `/beds`
  (S2) cobre a lógica compartilhada via helper v4 sintético, não o branch
  literal v5/v6.
- **Round 2 — `Merge verdict: BLOCK`** (F-01 parcial + novo P2): o cenário
  de dry-run na spec delta ainda atribuía aliases 48/48 ao stdout; `tasks.md`
  §3.2 idem. Corrigidos spec (`aliased_membership_count` como contrato) e
  §3.2 (nota de origem da asserção).
- **Round 3 — `Merge verdict: OK`**: pendências resolvidas com evidência
  caminho:linha; nenhuma atribuição indevida restante; consistência interna
  preservada; sem novos findings.

Validadores após o ciclo: `openspec validate rename-enf-2b-card-display-name
--strict` válido; `./scripts/markdown-lint.sh` sem erros.

## 7. Emendas e notas de execução (autorizadas/registradas pelo parent)

- **Emenda A — critério de formatação ruff** (durante RCD-S2, review round
  1 `BLOCK` por P1): os slices exigiam literalmente `ruff format --check`
  exit 0, mas `tests/unit/test_sector_capacity_catalog.py` e
  `tests/unit/test_bed_status_view.py` têm drift de formatação pré-existente
  do BASE_REF `765c186` (ruff 0.15.10 no host). Aplicado o critério já
  estabelecido no repo pelo change arquivado
  `2026-09-21-censo-residual-finding-filter` (tasks.md §3, Emenda B):
  `ruff check` exit 0 obrigatório; `ruff format --check` pode falhar SOMENTE
  por drift pré-existente, com prova de **zero drift incremental** (mesmos
  hunks do commit base, nenhum hunk tocando as adições). Os textos dos
  slices S1/S2 foram emendados para codificar esse critério; reformatação
  integral dos arquivos permanece proibida (violaria "apenas adições").
- **Nota de infraestrutura**: porta host 55433 ocupada por container de
  outro projeto neste ambiente; comandos de teste executados com
  `POSTGRES_PORT=55434` (contorno operacional, sem decisão de produto).
