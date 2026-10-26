# Tasks: reconcile-date-only-deaths

## 1. SLICE-DD-S1 — Matching date-only no planner

- [x] 1.1 RED: testes do matcher date-only (única casa em D 00:00 local;
      múltipla → `ambiguous`; sem paciente → `patient_not_found`; sem
      internação compatível → `admission_not_found`; borda
      admissão/óbito no mesmo D; datetime completo inalterado como
      regressão); `deaths:date_only` deixa de ser reason de revisão;
      linha `cohort=deaths` do dry-run reflete a nova elegibilidade
- [x] 1.2 GREEN: matching por data local (D1) no caminho de óbito +
      planner estendido
- [x] 1.3 Verificação local + gates do slice (worker: 101 unit + 17
      integração afetados; controller: quality-gate completo 4363 passed;
      reviewer ACCEPT com 2 P2 — help-text corrigido e gates executados)

## 2. SLICE-DD-S2 — Apply/rollback com marcador de precisão

- [x] 2.1 RED: apply de item date-only fecha a internação em D 00:00
      `America/Bahia` com evento `exit_type=death` e marcador
      `death_exit.precision="date"` (+ data local) em `details_json`;
      rollback por batch e por operação restaura o estado anterior;
      idempotência; agregações por data local insensíveis à hora
      portadora; indicadores de altas seguem sem óbitos
- [x] 2.2 GREEN: marcador no caminho de apply do item de óbito (D2/D4)
- [x] 2.3 Verificação local + gates do slice

## 3. Encerramento (controller)

- [x] 3.1 Review independente por slice (worker fresh + reviewer fresh;
      fix cycle P0/P1 máx. 2 rodadas — DD-S1: ACCEPT 1ª; DD-S2: 3 rounds
      com arbitragem do operador no round 3, finding final refutado pela
      invariante de irreversibilidade, limpeza ACCEPT)
- [x] 3.2 Gate final do change (quality-gate completo + integration)
      (2026-10-25 em ba37b89: unit 4393, integration 1067, ruff, mypy,
      check — evidence/final-gate.md)
- [x] 3.3 Release e ativação delimitada dos históricos: dry-run → backup →
      canário 50 → lotes ≤100 até drenar → conferência (episódios
      fechados por morte com marcador; indicadores de altas inalterados;
      `deaths:date_only` zerado como revisão); registro honesto
      (ambiguidades restantes contadas, não perseguidas)
      (2026-10-25: rc.41 publicada e deployada; dry-run classificou os
      777 = 57 aplicáveis + 511 já-fechados + 209 manual; canário 50 +
      lote 7 aplicados e conferidos; evidência em
      `docs/releases/2026-10-25_v0.1.0-rc.41.md`)

## Sequência e autoridade

Slices executáveis por worker fresh; referências em `design.md` (D1–D6) e
nas specs delta. Guardrails do backfill (dry-run default, cap, label,
backup-ref, rollback) são inalterados e obrigatórios. Ativação em
produção somente com autorização explícita do operador.
