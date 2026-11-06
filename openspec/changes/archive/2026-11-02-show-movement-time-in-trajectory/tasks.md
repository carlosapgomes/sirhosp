# Tasks

## 1. SMT-S1 — Hora de origem persistida no movimento

Contract: [slice-001-persist-movement-source-time](slices/slice-001-persist-movement-source-time.md).
Dependências: `extract-daily-census-from-dom` aceito (rc.44 em produção).
Requirements R1–R3 e aceite estão no contrato.

- [x] 1.1 Demonstrar RED do upsert sem hora (snapshot com
      `source_movement_at` produz movimento NULL) e da política de
      atualização; usar snapshots sintéticos, sem dados reais — SMT-S1 R1/R2.
- [x] 1.2 Adicionar somente o campo opcional e a migração aditiva sem
      backfill; verificar GREEN com hora verbatim do snapshot, timezone e
      movimento date-only válido — SMT-S1 R1.
- [x] 1.3 Implementar a propagação no upsert com a política
      último-com-hora-vence/never-null-erase; verificar criação, refresh,
      ganho-tarde e preservação, com PostgreSQL isolado — SMT-S1 R2.
- [x] 1.4 Verificar não-backfill e integridade: movimentos históricos
      permanecem NULL; constraint única e regressões de ECD-S1/S2/S3
      verdes — SMT-S1 R3.
- [x] 1.5 Executar validações/gates pertinentes e produzir
      `/tmp/sirhosp-slice-SMT-S1-report.md`; verificar aceite antes de
      SMT-S2.

Aceite técnico SMT-S1: `ACCEPTED`, uma revisão independente `OK` (zero
P0/P1/P2). RED genuíno (7 unitários + 8 integrações falhando no estado
anterior) e GREEN com os quatro casos da política D2 comprovados em
PostgreSQL isolado (criar, atualizar, ganhar hora depois, preservar).
Migração `0026` aditiva sem backfill/índice; histórico permanece NULL.
Gates finais: quality gate 4.487 unitários, ruff, mypy; integração separada
1.090 testes. Delta atribuível de 6 arquivos sobre árvore limpa `9efc32d`,
sem commit. Sem acesso a dados reais ou produção.
Relatório: `/tmp/sirhosp-slice-SMT-S1-report.md`; revisão e evidências:
`/tmp/sirhosp-orca-sequence-a3IUbz9l/slices/SMT-S1/`.

## 2. SMT-S2 — Hora exibida na Trajetória quando disponível

Contract: [slice-002-show-movement-time-in-trajectory](slices/slice-002-show-movement-time-in-trajectory.md).
Dependência: SMT-S1 aceito. Requirements R1–R4 e aceite estão no contrato.

- [x] 2.1 Demonstrar RED da view/template com movimentos mistos (com e sem
      hora) usando fixtures sintéticos — SMT-S2 R1/R2.
- [x] 2.2 Incluir a hora no contexto de trajetória e renderizar
      condicionalmente (`d/m/Y H:i` vs `d/m/Y`, `America/Bahia`); verificar
      GREEN, degradação sem placeholder e ordenação — SMT-S2 R1/R2.
- [x] 2.3 Verificar durações date-based inalteradas na presença de horas e
      regressões de trajetória/portal — SMT-S2 R3.
- [x] 2.4 Verificação de produto (portal dev com dataset fictício ou
      template test) da renderização mista em uma única trajetória —
      SMT-S2 R4.
- [x] 2.5 Executar quality gate final, integração separada e Markdown;
      produzir `/tmp/sirhosp-slice-SMT-S2-report.md`; submeter à revisão
      antes de aceite, commit ou publicação.

Aceite técnico SMT-S2: `ACCEPTED`, uma revisão independente `OK with
notes`, zero P0/P1 e duas notas P2 não bloqueadoras (fixture de teste com
`America/Sao_Paulo` em vez de `America/Bahia` — mesmo offset hoje; hora
exibida na coluna Entrada da tabela-resumo, permanecendo o card compacto
data-only por menor mudança). RED genuíno de renderização mista e
caracterização de durações; gates finais quality gate 4.491 unitários e
integração separada 1.090 testes. Delta atribuível de 3 arquivos (views,
`_patient_trajectory.html`, teste) sobre o SMT-S1 aceito intacto.
Relatório: `/tmp/sirhosp-slice-SMT-S2-report.md`; revisão e evidências:
`/tmp/sirhosp-orca-sequence-a3IUbz9l/slices/SMT-S2/`.

Ambos os slices aceitos tecnicamente. Commit/publicação dependem de
autorização separada.
