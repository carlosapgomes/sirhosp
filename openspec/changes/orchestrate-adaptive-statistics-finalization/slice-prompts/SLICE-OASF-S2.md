# SLICE-OASF-S2 — Pipeline adaptativo D-1 → estatísticas

## Handoff de entrada (contexto zero)

Comece somente após OASF-S1 aceito. Leia:

1. `AGENTS.md`;
2. `design.md`, decisões D1, D2, D4, D5 e D8 deste change;
3. o ADDED requirement em
   `specs/adaptive-census-orchestration/spec.md`;
4. ADR-0010 e `apps/census/orchestration.py` completos;
5. `tests/unit/test_orchestrator_quiet_window_d1.py`;
6. os changes abertos `orchestrate-d1-exit-recovery` e
   `orchestrate-intraday-discharge-recovery`, especialmente seus estados
   terminais de timer;
7. `compose.hospital.yml` e o contrato de settings das duas variáveis
   estatísticas.

A implementação de OASF-S1 já fornece os dois avisos permitidos. Não modifique
o preflight ou runbooks operacionais neste slice.

## Objetivo

Depois da tentativa D-1 natural, o loop guarda D-1 como data estatística
pendente e chama sua materialização exatamente uma vez na primeira drenagem
segura, antes do hourly e do próximo censo. Se o D-1 falhou, passa o aviso
`d1_recovery_incomplete`. Após 05:00, um processo reiniciado sem pendência usa a
ausência de revisão `ready` como marcador durável e tenta uma vez com
`d1_recovery_not_confirmed`. O Compose entrega a fronteira e o lookback ao
orquestrador de forma fail-closed.

## Requisitos verificáveis

- **R1:** sucesso D-1 com fila ainda drenada produz ordem `d1 → statistics →
  hourly → cycle`, usando a data Bahia anterior explícita.
- **R2:** se a reavaliação pós-D-1 encontrar run ativo ou batch aberto, nenhuma
  chamada estatística ocorre; a data fica pendente e é chamada uma vez na
  primeira iteração drenada posterior.
- **R3:** uma pendência pode ser processada mesmo quando somente o cooldown
  censitário torna `eligible=False`; fila ativa, batch aberto, stale blocker ou
  circuit breaker continuam bloqueando.
- **R4:** falha/`SystemExit` D-1 chama a data com
  `d1_recovery_incomplete`; sucesso não envia o aviso.
- **R5:** falha/`SystemExit` da materialização registra apenas tipo técnico e
  data, consome a tentativa no processo e não impede hourly/censo.
- **R6:** mesma data não repete no mesmo processo; restart dentro da janela pode
  repetir com segurança.
- **R7:** sucessos D-1 e hourly emitem seus marcadores agregados canônicos
  somente após retorno bem-sucedido; falha jamais emite `result=success`.
- **R8:** `census_orchestrator` recebe `STATISTICS_ACTIVATION_DATE` vazia por
  default e `STATISTICS_FINALIZATION_LOOKBACK_DAYS` limitada, sem expor
  credenciais ou alterar outros serviços.
- **R9:** ADR-0012 registra propriedade, sequência, fallback, dependências dos
  changes D-1/hourly e rollback.
- **R10:** a partir das 05:00, D-1 elegível sem revisão `ready` e ainda não
  tentado pelo processo cria uma única pendência e materializa na primeira
  drenagem com `d1_recovery_not_confirmed`, sem executar D-1 fora da janela.
- **R11:** a partir das 05:00, revisão `ready`, fronteira ausente ou D-1 anterior
  à ativação não criam pendência nem chamada estatística.

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1–R7, R10–R11 | `apps/census/orchestration.py` | novo `test_orchestrator_daily_statistics.py` e regressão quiet-window/hourly |
| R8 | `compose.hospital.yml` | teste estático no novo módulo de teste |
| R9 | ADR-0012 e índice | Markdown lint e inspeção do índice |

## Escopo e blast radius

```yaml
expected_files:
  - apps/census/orchestration.py
  - tests/unit/test_orchestrator_daily_statistics.py
  - tests/unit/test_orchestrator_quiet_window_d1.py
  - compose.hospital.yml
  - docs/adr/ADR-0012-finalizacao-estatistica-orquestrada-pela-drenagem-adaptativa.md
  - docs/adr/README.md
allowed_incidental_files: []
max_changed_files: 6
out_of_scope:
  - deploy/daily-statistics-activation-preflight.sh
  - deploy/systemd/
  - deploy/README.md
  - apps/statistics_reports/**, concluído em OASF-S1
  - models, migrations e novos daemons
```

Pare se precisar de persistência adicional, lock novo, Celery/Redis, alteração
da janela D-1 ou mais de seis arquivos.

## Forma esperada da implementação

- Reutilize a data local calculada pelo relógio injetável.
- Marque a tentativa D-1 antes de chamá-la, como no contrato atual.
- Capture sucesso/falha sem inspecionar texto nominal do comando.
- Guarde pendência pequena em memória: data-alvo e aviso opcional.
- A partir das 05:00, se a data ainda não foi tentada no processo, consulte
  apenas se D-1 elegível possui `DailyStatisticsReport` `ready`; não faça sweep
  de datas nem crie modelo.
- Separe “drenagem segura” de “elegibilidade para novo censo”; não duplique uma
  query ampla se os campos agregados de `OrchestratorDecision` bastarem.
- Marque a tentativa estatística antes do `call_command`.
- Chame `materialize_daily_statistics --date YYYY-MM-DD`; use
  `d1_recovery_incomplete` em falha observada e `d1_recovery_not_confirmed` na
  recuperação pós-05:00.
- Reavalie estado depois do D-1. Se ele ocupou a fila, não execute hourly nem
  abra censo nessa iteração.
- Emita markers canônicos distintos para D-1 e hourly somente no retorno de
  sucesso.
- Não capture ou replique stdout dos comandos.

## Plano TDD

### RED

Crie o novo módulo de teste e ajuste somente as expectativas diretamente
afetadas no teste quiet-window. Execute:

```bash
uv run pytest -q \
  tests/unit/test_orchestrator_daily_statistics.py \
  tests/unit/test_orchestrator_quiet_window_d1.py
```

Esse comando host-only é diagnóstico focado de RED/GREEN, não gate oficial.
Falhas esperadas: ausência da chamada estatística, ordem antiga e Compose sem as
variáveis. Registre as falhas comportamentais antes da implementação.

Inclua todos os cenários R1–R11, inclusive duas iterações para fila ocupada,
cooldown sem fila, boundaries 04:59/05:00 Bahia, restart pós-05:00 com e sem
revisão pronta, materialização já tentada no mesmo processo, ativação ausente,
D-1 falho, materialização falha e markers D-1/hourly não emitidos em falha.

### GREEN / refactor

Implemente a FSM mínima no loop e as duas variáveis no override do serviço
Compose. Reexecute o mesmo comando até verde. Não mova responsabilidades para
management commands nem altere `run_single_cycle` sem necessidade demonstrada.

### Verificação local do slice

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
openspec validate orchestrate-adaptive-statistics-finalization --strict
```

## Critérios de aceitação

- [ ] R1–R11 comprovados.
- [ ] Não há chamada repetida enquanto a fila permanece bloqueada.
- [ ] Materialização antecede hourly/censo após a drenagem.
- [ ] Falhas não emitem sucesso falso nem derrubam o loop.
- [ ] Compose vazio mantém o runtime estatístico inerte.
- [ ] Diff dentro dos seis arquivos.
- [ ] `/tmp/sirhosp-slice-OASF-S2-report.md` completo e sem dados sensíveis.

## Contrato de handoff

Não altere `tasks.md`, não commita e não antecipe OASF-S3. Se o comportamento
real do runtime D-1 exigir uma fila persistente não prevista, pare e registre a
evidência; não crie infraestrutura. O reviewer deve desafiar especialmente
ordem, reavaliação, cooldown, recuperação pós-05:00, uma tentativa por processo
e falsos marcadores D-1/hourly.
