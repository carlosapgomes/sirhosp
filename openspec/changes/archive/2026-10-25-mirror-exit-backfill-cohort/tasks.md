# Tasks: mirror-exit-backfill-cohort

## 1. SLICE-BME-S1 — Coorte mirror no planner (plano e dry-run)

- [x] 1.1 RED: testes da coorte no planner (elegível única-fechada-na-janela;
      ambígua → manual `discharges:mirror_ambiguous`; paciente ausente →
      `discharges:mirror_patient_not_found`; internação aberta não é mirror;
      ordem duplicates→discharges→mirror→deaths; contagem com `--limit`;
      linha `cohort=mirror_exits` no dry-run do comando)
- [x] 1.2 GREEN: `MirrorExitItem`/coorte em `apps/patients/backfill.py` +
      linha de saída no comando `reconcile_admission_history`
- [x] 1.3 Verificação local + gates do slice

## 2. SLICE-BME-S2 — Apply e rollback da coorte mirror

- [x] 2.1 RED: apply cria evento `reconciled`/`hospital_discharge` com
      `reason_code="mirror_exit"` e batch em `details_json`; evidência vira
      `reconciled`; `Admission` intacta; idempotência; rollback por batch e
      por operação restaura `pending`; saída agregada sem identidade
- [x] 2.2 GREEN: estende `apply_backfill_plan` e o rollback às mirror items
- [x] 2.3 Verificação local + gates do slice

## 3. Encerramento (controller)

- [x] 3.1 Review independente por slice (worker fresh + reviewer fresh;
      fix cycle P0/P1 máx. 2 rodadas) — S1: ACCEPT 1ª; S2: BLOCK 1ª (2×P1)
      → ACCEPT 2ª
- [x] 3.2 Gate final do change (quality-gate completo)
- [x] 3.3 Release e plano de ativação: dry-run → canário 50 mirror →
      lotes ≤100 → conferência do gráfico histórico (a lacuna
      abril/agosto deve fechar)
      (Ativação executada 2026-10-25 em produção, com escopo honesto
      registrado: o cenário mudou desde a proposta — a coorte mirror
      havia sido parcialmente aplicada em 08/set/2026 (57 eventos) e
      restava elegível apenas 1 item mirror + 145 altas exatas. Sequência
      executada: dry-run completo → backup custom validado
      `backups/sirhosp-backfill-mirror-20261025T141511Z.dump` (1,09 GB,
      `pg_restore --list` OK) → canário `--limit 50` (batch
      `fb14d1ca-3967-436e-9d51-07caac958fb6`, 50 altas exatas) → lote
      `--limit 96` (batch `8af1db1b-c692-480f-bf5a-9e18a7c1a323`, 95
      exatas + 1 mirror). Verificação final: todas as coortes elegíveis
      = 0; eventos `mirror_exit` 57→58; pendências abril 1317→1286 e
      agosto 1091→998. **A lacuna abril/agosto não fechou por completo**
      — a massa restante (2.284 pendências em abril/agosto) está no
      bucket de revisão manual (6.489 itens: patient_not_found 1751,
      mirror_patient_not_found 1664, admission_not_found 1249,
      deaths:date_only 777, stale_confirmation 738, ambiguous 288,
      multiple_episodes 21), explicitamente fora do escopo desta change
      ("counted for manual review only"). Fechamento completo da lacuna
      exige decisão futura sobre a massa manual — outro change.)
