# Tasks: harden-targeted-evolution-full-sync

> Implementação em cinco slices verticais por DeepSeek4-Flash com contexto
> zero. Cada slice tem prompt completo em `slice-prompts/SLICE-HTEFS-S<n>.md`.
> Ordem recomendada: S1 → S2 → S3 → S4 → S5. Um terceiro LLM verifica o
> relatório e o diff antes do próximo slice. Arquivamento somente após S5
> verificado e autorização do operador.

## 1. HTEFS-S1 — Ativação resiliente da ação Evolução

- [x] 1.1 Inspecionar `click_evolucao`, seletores do modal, deadlines e testes;
      executar baseline unit oficial.
- [x] 1.2 RED: cobrir clique normal, timeout de actionability com fallback DOM,
      modal já aberto, pós-condição ausente e sanitização.
- [x] 1.3 GREEN mínimo e REFACTOR local: duas estratégias, uma pós-condição,
      deadline compartilhado e erros tipados.
- [x] 1.4 Executar inspeções, gates oficiais e markdown lint; gerar
      `/tmp/sirhosp-slice-HTEFS-S1-report.md`; marcar somente 1.x; STOP.

## 2. HTEFS-S2 — Seleção estrita da internação alvo

- [x] 2.1 Confirmar S1 verificado; inspecionar propagação
      worker → adapter → bridge e fixtures sintéticas de internações.
- [x] 2.2 RED: cobrir alvo ativo entre sobrepostas, chave volátil, desempate por
      dica compatível, ambiguidade/ausência fail-closed, detalhe estrito e modo sem
      `admission_id` preservado.
- [x] 2.3 GREEN mínimo e REFACTOR: contexto alvo mínimo, seletor puro e nenhuma
      identidade dinâmica em logs/erros.
- [x] 2.4 Executar inspeções, gates oficiais e markdown lint; gerar
      `/tmp/sirhosp-slice-HTEFS-S2-report.md`; marcar somente 2.x; STOP.

## 3. HTEFS-S3 — Cobertura e commit incremental por chunk

- [x] 3.1 Confirmar S2 verificado; inspecionar model/migrations, planner,
      chunker canônico, transações e contadores do worker.
- [x] 3.2 RED: provar que evento isolado não cobre data, vazio confirmado cobre,
      primeiro chunk sobrevive à falha do segundo, falha de persistência/coverage
      reverte o chunk e retry pula cobertura já confirmada.
- [x] 3.3 GREEN mínimo: model + migration, união de intervalos no planner e
      transação idempotente por chunk alvo; sem backfill.
- [x] 3.4 Executar testes de migration/inspeções, gates oficiais e markdown
      lint; gerar `/tmp/sirhosp-slice-HTEFS-S3-report.md`; marcar somente 3.x;
      STOP.

## 4. HTEFS-S4 — Guard automático fixo de 60 minutos

- [x] 4.1 Confirmar S3 verificado; inspecionar auto-enqueue compartilhado,
      histórico terminal, `next_retry_at`, elegibilidade e batch.
- [x] 4.2 RED: falha recente difere até `failed_at + 60 min`; prazo vencido e
      sucesso posterior não diferem; manual ignora; retry interno +60s permanece.
- [x] 4.3 GREEN mínimo e REFACTOR: política pura/consulta única no serviço
      compartilhado, sem model, contador, scheduler ou backoff exponencial.
- [x] 4.4 Executar inspeções, gates oficiais e markdown lint; gerar
      `/tmp/sirhosp-slice-HTEFS-S4-report.md`; marcar somente 4.x; STOP.

## 5. HTEFS-S5 — Subetapas e progresso sanitizados

- [x] 5.1 Confirmar S4 verificado; inspecionar stage metrics, adapter, bridge,
      callback opcional e superfícies de saída.
- [x] 5.2 RED: transições por enum, localização da falha, totais de chunks
      parciais/completos, callback ausente e sentinelas sensíveis ausentes.
- [x] 5.3 GREEN mínimo e REFACTOR: protocolo opcional, enum fechado e detalhes
      agregados; falha de telemetria não altera extração/taxonomia.
- [x] 5.4 Revisar diff integral e rastreabilidade specs→testes; executar gates,
      `openspec validate harden-targeted-evolution-full-sync --strict` e markdown
      lint.
- [x] 5.5 Gerar `/tmp/sirhosp-slice-HTEFS-S5-report.md`; marcar somente 5.x;
      aguardar verificação por terceiro LLM e autorização para arquivar; STOP.
