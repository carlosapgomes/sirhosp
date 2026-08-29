# Tasks: fix-fullsync-failure-exhaustion

> Implementação slice a slice por DeepSeek4-Flash com contexto zero.
> Cada slice tem prompt próprio em `slice-prompts/SLICE-FX-S<n>.md`.
> Ordem: FX-S1 → FX-S2 → FX-S3 → FX-S4. Verificação por terceiro LLM
> entre slices; arquivamento somente após FX-S4 verificado e autorizado
> pelo operador.

## 1. FX-S1 — Retry por classe de falha: fail-fast de payload determinístico

- [x] 1.1 Confirmar contexto: ADR-0008, design D1, `run_lifecycle.py`,
  `_mark_run_failed` dos dois workers; baseline unit oficial.
- [x] 1.2 RED: política pura (`invalid_payload` não-retryável, demais
  retryáveis); `_mark_run_failed` de cada worker — `InvalidJsonError`
  termina fail-fast na 1ª tentativa (sem requeue, com `FinalRunFailure` e
  fechamento de batch); `EvolutionPdfTimeoutError` mantém requeue com
  backoff (regressão); log fail-fast sanitizado.
- [x] 1.3 GREEN mínimo + REFACTOR (guarda única por worker, sem duplicar
  ramo terminal).
- [x] 1.4 Inspeções `rg` obrigatórias + gates oficiais; unit final >=
  baseline.
- [x] 1.5 Relatório `/tmp/sirhosp-slice-FX-S1-report.md`; marcar 1.x;
  commit/push; STOP.

## 2. FX-S2 — Orçamento de tempo por volume nas janelas de evolução

- [x] 2.1 RED: função pura `evolution_window_budget_seconds` (base,
  crescimento por dia, teto, datas inválidas sanitizadas, determinismo);
  worker persistente passa o orçamento por janela no laço de
  `extract_evolutions` (sem `timeout=120` fixo).
- [x] 2.2 GREEN mínimo + REFACTOR (função pura sem Django; call site
  único).
- [x] 2.3 Inspeções `rg` obrigatórias (call site sem literal 120 no laço;
  bounded preservado no fluxo) + gates oficiais; unit final >= baseline.
- [x] 2.4 Relatório `/tmp/sirhosp-slice-FX-S2-report.md`; marcar 2.x;
  commit/push; STOP.

## 3. FX-S3 — Caracterização das validações de payload (H2b)

- [x] 3.1 RED/characterização: suíte cobrindo as 6 validações do design D3
  contra código real, incluindo resgate viewer-frame para `data` vazio e
  ausência genuína; cada validação com teste próprio mapeando
  `invalid_payload`.
- [x] 3.2 Prova de sensibilidade: mutação temporária (quebrar fallback do
  viewer e/ou uma validação) faz a suíte falhar; reverter e registrar.
- [x] 3.3 Correção apenas de gap comprovado por RED (se houver);
  comportamento verde = veredito "sem lacuna" registrado com evidência.
- [x] 3.4 Inspeções `rg` + gates oficiais; unit final >= baseline.
- [x] 3.5 Relatório `/tmp/sirhosp-slice-FX-S3-report.md`; marcar 3.x;
  commit/push; STOP.

## 4. FX-S4 — Regressão laboratório, nota operacional e verificação final

- [x] 4.1 Confirmar FX-S1–S3 COMPLETE; baseline unit oficial.
- [x] 4.2 Re-executar o laboratório CFC (`fullsync_failure_lab.py`):
  vereditos H1/H2 inalterados com deadlines experimentais; controles
  passando; registrar artefato.
- [x] 4.3 Nota operacional em `deploy/README.md` (§6.3): novo
  comportamento do retry/orçamento e como observá-lo pelos agregados
  existentes (sem contrato novo).
- [x] 4.4 Revisão de diff total (PHI/identificadores/migrations/
  dependências) + todos os gates + `openspec validate --strict` + markdown
  lint.
- [x] 4.5 Relatório `/tmp/sirhosp-slice-FX-S4-report.md`; marcar 4.x;
  aguardar verificação de terceiro LLM; parar (arquivamento exige
  autorização explícita do operador).
