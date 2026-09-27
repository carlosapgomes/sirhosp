# ADR-0012: Finalização estatística orquestrada pela drenagem adaptativa

## Status

Proposed — 2026-09-27.

## Contexto

A ADR-0010 moveu a recuperação D-1 para dentro do loop adaptativo porque apenas
ele conhece a janela real em que fila e batch estão livres. O change
`orchestrate-intraday-discharge-recovery` aplica a mesma propriedade à
recuperação intradiária de altas. A finalização estatística diária, porém, ainda
pertencia a um timer fixo às 07:30, e o `census_orchestrator` não recebia
`STATISTICS_ACTIVATION_DATE` pelo Compose: o container persistente não conhecia
a fronteira estatística, enquanto o preflight procurava evidências D-1 e hourly
nos journals dos services legados, não nos logs do orquestrador.

O relatório já oferece seleção censitária fail-closed, materialização atômica,
revisões idempotentes, `quality_warnings_json` e impressão digital das fontes.
Reutilizá-los evita migration, fila nova ou scheduler adicional.

## Decisão

1. **Propriedade.** O orquestrador adaptativo (`run_loop` de
   `apps/census/orchestration.py`) é o dono do encadeamento D-1 → drenagem →
   materialização. A recuperação D-1 continua dentro da janela `[01:00, 05:00)`
   e a recuperação intradiária continua por hora local; a finalização
   estatística é um passo pendente curto entre elas.
2. **Sequência.** Depois da tentativa D-1 única por data local, o loop captura
   `target_date = local_date - 1` como pendência em memória. A materialização
   ocorre na primeira iteração em que não existam runs `queued`/`running` nem
   `CensusExecutionBatch` aberto, antes da recuperação intradiária e do próximo
   ciclo censitário. A verificação de drenagem usa apenas os campos agregados de
   `OrchestratorDecision` e é independente do cooldown censitário.
3. **Datas e avisos.** A chamada é
   `materialize_daily_statistics --date <D-1>`, restrita à fronteira declarada.
   Uma falha ou `SystemExit` do D-1 publica a revisão com o aviso allowlisted
   `d1_recovery_incomplete`; um processo reiniciado após as 05:00 que não
   encontra revisão `ready` faz uma única tentativa com
   `d1_recovery_not_confirmed`. Sucesso D-1 no mesmo processo não envia aviso.
   Não há varredura de datas nem reconstrução anterior à ativação.
4. **Uma tentativa por processo.** A tentativa lógica é marcada antes do
   `call_command`; uma falha não repete a mesma data no processo atual, mas o
   restart pode repetir com segurança graças à idempotência e aos row locks já
   existentes. A ausência durável da revisão `ready` é o marcador de recuperação
   após a janela D-1.
5. **Configuração explícita.** O Compose entrega ao `census_orchestrator`
   `STATISTICS_ACTIVATION_DATE` (default vazio, fail-closed) e
   `STATISTICS_FINALIZATION_LOOKBACK_DAYS` (default 7, limitado). A fronteira
   ausente mantém o runtime estatístico inerte e nenhum outro serviço muda.
6. **Fallback manual.** Os services one-shot `sirhosp-historical-recovery`,
   `sirhosp-discharges` e `sirhosp-daily-statistics` permanecem disponíveis para
   operação manual, com `--finalize` limitado pela fronteira e pelo lookback. Os
   timers legados permanecem desabilitados/inativos no caminho primário. Este
   passo não cria daemon, fila, Celery, Redis ou tabela nova.
7. **Evidência agregada.** O loop emite apenas os marcadores canônicos
   `mode=d1-recovery result=success source=adaptive-orchestrator` e
   `mode=hourly-discharges result=success source=adaptive-orchestrator`, após o
   retorno bem-sucedido do respectivo `call_command`; nenhuma saída nominal de
   comando é capturada, replicada ou persistida.

## Alternativas consideradas

1. **Manter o timer fixo das 07:30.** Rejeitada: volta a adivinhar a drenagem e
   falha quando o orquestrador ainda encadeia batches, exatamente o problema da
   ADR-0010.
2. **Vários disparos por calendário entre 00:30 e 07:30.** Rejeitada:
   multiplica colisões sem observar fila e batch.
3. **Tabela de jobs ou fila dedicada para a pendência.** Rejeitada na fase 1: a
   revisão `ready` e a idempotência já oferecem recuperação suficiente e
   qualquer persistência nova amplia a superfície operacional.
4. **Materializar antes do D-1.** Rejeitada: publicaria sistematicamente antes da
   principal reconciliação diária e degradaria a revisão sem necessidade.
5. **Aplicar o aviso D-1 a `--finalize`.** Rejeitada: um único resultado
   observado não pode degradar todas as datas elegíveis da janela.

## Consequências

### Positivas

- A finalização deixa de depender de horário fixo: ocorre quando a fila está
  drenada e nenhum batch está aberto.
- Reutiliza materialização atômica, revisões idempotentes e avisos allowlisted,
  sem nova infraestrutura.
- A configuração estatística chega ao orquestrador de forma explícita e
  fail-closed, e os marcadores canônicos tornam a cadência natural auditável.

### Negativas e trade-offs

- O orquestrador ganha mais uma responsabilidade acoplada ao estado da fila.
- A publicação pode ocorrer de madrugada, então o relatório passa a depender do
  fechamento D-1 e não de um horário previsível.
- Limitações do fechamento censitário (dia sem abertura ou fechamento aceito)
  continuam impedindo a publicação e exigem investigação manual, não retry cego.

### Riscos e mitigações

- **Restart após a janela D-1:** ausência de revisão `ready` recria uma única
  pendência pessimista com `d1_recovery_not_confirmed`.
- **D-1 reocupa a fila:** a reavaliação de drenagem mantém a data pendente e
  adia hourly e censo.
- **Falha silenciosa:** o erro é reduzido à classe técnica e à data; a tentativa
  é consumida, o aviso é persistido na revisão e o loop segue.
- **Falso marcador de sucesso:** o marcador é emitido apenas após retorno
  bem-sucedido, com teste de falha dedicado.
- **Ativação indevida:** fronteira explícita, lookback limitado e nenhum backfill
  anterior à ativação.

### Dependências

- Change `orchestrate-d1-exit-recovery` (ODER): origem do passo D-1 in-process;
  seu timer legado permanece desabilitado/inativo.
- Change `orchestrate-intraday-discharge-recovery` (OIDR): origem do passo hourly
  e do marcador correspondente; o timer `:13` permanece fallback manual.
- Os deltas de ODER e OIDR devem ser sincronizados e arquivados antes do
  arquivamento de `orchestrate-adaptive-statistics-finalization`.
- O runbook e o preflight read-only dos slices posteriores do mesmo change
  consomem os marcadores canônicos definidos aqui.

### Rollback

Remover `STATISTICS_ACTIVATION_DATE` do `.env` ou restaurar a release anterior e
recriar somente o `census_orchestrator`, sem habilitar os timers legados. Como as
fontes clínicas não são alteradas e nenhuma tabela nova é criada, não há
restauração de banco nem limpeza de arquivos: revisões já materializadas
permanecem auditáveis e nenhuma data é reconstruída.

## Relações

- Change OpenSpec: `orchestrate-adaptive-statistics-finalization`.
- ADR-0010: recuperação D-1 orquestrada pelo ciclo adaptativo de censo.
- ADR-0011: projeção diária materializada e versionada para relatórios
  estatísticos.
- ADR-0009: reconciliação canônica de saídas e identidade longitudinal de
  internações.
