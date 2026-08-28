# RPAP-S6 — Padronizar falha do processador de censo

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md` e todo o change atual;
2. prompts/relatórios COMPLETE S1–S5;
3. deltas `census-snapshot-processing` e `adaptive-census-orchestration`;
4. `apps/census/management/commands/process_census_snapshot.py`;
5. `apps/census/orchestration.py`, especialmente a chamada do processador;
6. `apps/census/services.py` somente no contrato de resultado rejeitado;
7. `tests/unit/test_process_census_snapshot.py`;
8. `tests/unit/test_adaptive_census_orchestrator.py`.

Estado: o command chama o serviço e executa `sys.exit(1)` quando
`result["rejected"]` é verdadeiro. `run_single_cycle()` captura apenas
`Exception` ao chamar o processador; `SystemExit` pode escapar. O serviço e seus
efeitos de domínio não precisam mudar.

## Protocolo obrigatório para implementador DeepSeek4-Flash

1. Registre BASE_REF, árvore limpa e matriz requisito→arquivo→teste.
2. Confirme S1–S5 COMPLETE. Rode baseline unit oficial; qualquer falha bloqueia.
3. Escreva RED primeiro: `call_command` deve levantar `CommandError`, não
   `SystemExit`, e o orquestrador deve retornar `processing_failed`.
4. Implemente GREEN mínimo no command; não altere domínio ou capture
   `BaseException`.
5. Refatore só imports/comentários tocados com clean code, DRY e YAGNI.
6. Rode inspeções e todos os gates; final unit exit 0, zero failures/errors e
   passed_final >= baseline.
7. Relatório completo antes de marcar 6.1–6.6, commit/push e STOP.

## Objetivo vertical

Uma rejeição estruturada de snapshot deve atravessar `call_command` como
`CommandError`, ser convertida pelo orquestrador em `processing_failed`, liberar
o lock e deixar o processo/loop vivo, sem criar batch, filas ou movimentos.

## Requisitos funcionais

### R1 — Erro convencional

Importar e levantar `django.core.management.base.CommandError` no command para
toda resposta `rejected=True`. Mensagem sanitizada pode conter apenas cobertura
agregada já permitida; não incluir linhas/pacientes.

### R2 — Sem SystemExit no processador

Remover uso/import de `sys` se ficar sem função. Não usar `raise SystemExit`,
`exit()`, `os._exit()` ou `except BaseException`.

### R3 — Outcome do orquestrador

Com extração bem-sucedida e processador levantando `CommandError`,
`run_single_cycle()` retorna `outcome="processing_failed"`, `cycle_executed=True`
e libera advisory lock. A exceção não escapa.

### R4 — Zero efeito da rejeição

Testar que nenhum `CensusExecutionBatch`, admissions/demographics run ou
`PatientMovement` novo é criado. O serviço continua responsável por rejeitar
antes dos efeitos.

### R5 — Sucesso preservado

Processamento aceito continua exibindo métricas, atualizando movimentos e
permitindo outcome success. Extração `SystemExit` existente, se ainda suportada
na etapa anterior, fica fora deste slice.

## Arquivos esperados e limite

Máximo de **3 arquivos de código/teste rastreados**, além de `tasks.md`:

1. `apps/census/management/commands/process_census_snapshot.py`;
2. `tests/unit/test_process_census_snapshot.py`;
3. `tests/unit/test_adaptive_census_orchestrator.py`.

Não editar `orchestration.py`, `services.py`, models, migrations, workers, docs
ou deploy. O catch `Exception` existente deve aceitar `CommandError`; se não
aceitar conforme teste, pare e reporte bloqueio antes de adicionar quarto
arquivo.

## TDD obrigatório

### RED

Adicionar/ajustar testes sintéticos:

1. resultado rejeitado explícito via `call_command` levanta `CommandError`;
2. não levanta `SystemExit`;
3. sem batch/runs/movements na rejeição;
4. orchestrator com extração success + processor `CommandError` retorna
   `processing_failed` sem escape;
5. lock release ocorre;
6. one-shot converte failed outcome em status não zero pelo contrato atual;
7. caminho aceito continua success e chama movimentos.

RED deve falhar especificamente porque o command ainda usa `sys.exit(1)`.

### GREEN

Substituir a fronteira de erro e ajustar import. Não alterar o dict do serviço,
threshold de setores, ordem de movimentações ou taxonomy do orchestrator.

### REFACTOR

Remover comentário/import obsoleto apenas no arquivo tocado. Não harmonizar
todos os `sys.exit` do projeto nem fazer refactor amplo.

## Checks de inspeção obrigatórios

```bash
rg -n "CommandError|sys\.exit|SystemExit|exit\(|BaseException|import sys" \
  apps/census/management/commands/process_census_snapshot.py
rg -n -B 8 -A 18 "process_census_snapshot" apps/census/orchestration.py
rg -n "CommandError|SystemExit|processing_failed|CensusExecutionBatch|PatientMovement|lock" \
  tests/unit/test_process_census_snapshot.py \
  tests/unit/test_adaptive_census_orchestrator.py
rg -n "rejected" apps/census/management/commands/process_census_snapshot.py \
  apps/census/services.py
```

Esperado: zero saída process-level no command; catch existente permanece;
testes provam efeitos e lock; serviço não foi editado.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate repair-persistent-admissions-pipeline --strict
./scripts/markdown-lint.sh
```

## Critérios binários de sucesso

- [ ] R1–R5 cobertos RED/GREEN.
- [ ] Rejeição usa `CommandError`, nunca `SystemExit`.
- [ ] Orchestrator retorna `processing_failed` e libera lock.
- [ ] Rejeição cria zero batch/run/movement.
- [ ] Caminho aceito permanece success.
- [ ] Exatamente três arquivos esperados; domínio/orchestrator não editados.
- [ ] Gates exit 0 e unit final >= baseline sem failures/errors.

### Condições automáticas de INCOMPLETO

- S1–S5/baseline/RED ausente ou falho;
- `sys.exit`/SystemExit permanece no processador;
- `BaseException` é capturado;
- serviço/orchestrator é alterado sem bloqueio;
- rejeição cria efeito ou escapa do ciclo;
- sucesso/movimentos regressam;
- teste é enfraquecido para aceitar ambos os erros;
- arquivo extra, dado sensível, gate falho, relatório ausente ou task prematura.

## Gates de autoavaliação

1. Qual teste distingue `CommandError` de `SystemExit`?
2. Qual teste prova `processing_failed` e lock release?
3. Como foi provado zero efeito clínico/operacional?
4. Qual teste preserva sucesso e movimentos?
5. Por que `orchestration.py` não precisou mudar?
6. Por que cada arquivo alterado é necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-RPAP-S6-report.md` com Status, BASE_REF, matriz,
RED/GREEN, snippets, inspeções, prova de effects/lock, baseline/final, todos os
gates, rerun, arquivos/justificativas, riscos e `Handoff para verificador`
R1–R5.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full
repair-persistent-admissions-pipeline change, SLICE-RPAP-S6.md and COMPLETE
S1-S5 reports. Implement ONLY S6. Follow DeepSeek4-Flash protocol: clean
BASE_REF, official unit baseline, real RED proving current SystemExit mismatch,
minimal GREEN using CommandError, local clean-code/DRY/YAGNI refactor,
mandatory rg and all official gates, final unit exit 0 with zero failures/errors
and passed >= baseline. Preserve census service, accepted path, movements and
orchestrator taxonomy; never catch BaseException. Touch only the command and two
listed tests. Create /tmp/sirhosp-slice-RPAP-S6-report.md with evidence and
verifier handoff. Any missing/failing item is INCOMPLETE with no task
update/commit. If complete, mark only S6, commit, push, reply REPORT_PATH=...,
then STOP.
```
