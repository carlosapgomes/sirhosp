# RPAP-S5 — Health check agregado e alertável

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md` e todo o change atual;
2. prompts/relatórios COMPLETE S1–S4;
3. delta `ingestion-pipeline-health/spec.md`;
4. `apps/ingestion/models.py`, `apps/census/models.py` e
   `apps/patients/models.py` apenas nos campos consultados;
5. `apps/clinical_docs/models.py` no modelo `ClinicalEvent`;
6. `apps/ingestion/run_lifecycle.py` para reasons sanitizados;
7. commands de stale recovery e adaptive census como estilo de saída;
8. `deploy/README.md` na seção criada por S4.

Estado: o banco já contém lifecycle/counters/stages suficientes, mas não há
one-shot fail-closed que agregue as invariantes do incidente. Este slice não
corrige falhas de evolução; torna-as mensuráveis por reason e threshold.

## Protocolo obrigatório para implementador DeepSeek4-Flash

1. Registre BASE_REF, árvore limpa e matriz requisito→arquivo→teste.
2. Confirme S1–S4 COMPLETE. Rode unit baseline oficial; falha/error bloqueia.
3. Escreva RED para cada invariante, threshold, amostra mínima, read-only e
   privacidade. RED deve falhar pela ausência/comportamento do health command.
4. Implemente GREEN mínimo em serviço de consulta + command fino.
5. Refatore apenas o novo código: cálculos puros, nomes/unidades explícitos,
   query count controlado, DRY, YAGNI e nenhuma regra escondida no output.
6. Não chamar Playwright, rede, alert provider ou comando mutante.
7. Rode inspeções/gates; final unit exit 0, zero failures/errors e passed >=
   baseline.
8. Relatório antes de marcar 5.1–5.6, commit/push e STOP.

## Objetivo vertical

Entregar `check_ingestion_pipeline_health`, command read-only que retorna zero
quando saudável e `CommandError` quando invariantes/limiares configurados falham,
sempre com saída agregada e sanitizada adequada a systemd.

## Requisitos funcionais

### R1 — Janela e validação

Aceitar `--window-hours` positivo (default 24),
`--settling-minutes` não negativo, `--max-active-age-minutes` positivo,
`--max-full-sync-failure-percent` entre 0 e 100 e
`--min-full-sync-terminal-sample` positivo. Argumento inválido falha antes de
query relevante/mutação.

### R2 — Invariantes clínicas batch-bound

Na janela e após settling:

- contar succeeded batch-bound `admissions_only` com `admissions_seen=0`;
- comparar por batch+patient em memória efêmera cada succeeded não vazio com
  existência de `full_sync`/`full_admission_sync` correspondente;
- detectar mais de um `demographics_only` batch-owned para o mesmo
  batch+patient.

Qualquer contagem positiva torna unhealthy. Nunca imprimir as chaves usadas.

### R3 — Fila e evoluções

Contar queued/running suportados e idade do mais antigo; exceder máximo torna
unhealthy. Para full-sync terminal, agregar succeeded/failed, eventos criados e
failed por reason. Taxa acima do máximo só alarma quando a amostra mínima é
atingida.

### R4 — Frescor opcional

Sempre calcular presença/idade agregada do último `PatientMovement.last_seen_at`,
`Admission.updated_at` e `ClinicalEvent.created_at`. Flags opcionais
`--max-movement-age-hours`, `--max-admission-age-hours` e
`--max-event-age-hours` positivas ativam alarmes; omitidas são informativas.
Ausência com threshold ativo é unhealthy.

### R5 — Exit e output

Healthy retorna normalmente; unhealthy imprime resumo fixo e levanta
`CommandError` sanitizado. Output traz somente nomes de métricas, counts,
percentuais, durations arredondadas, booleans e failure reasons allowlisted.
Proibir qualquer PK, parameters JSON, patient record, nome, texto, URL ou erro
bruto.

### R6 — Read-only e operação

Provar zero INSERT/UPDATE/DELETE e zero chamada externa. Documentar comando
one-shot, flags, interpretação, exemplo systemd genérico, critérios canários,
recovery dry-run/apply em lotes, drenagem, stop conditions, rollback e que
provider de alerta fica fora do escopo.

## Arquivos esperados e limite

Máximo de **4 arquivos rastreados**, além de `tasks.md`:

1. novo `apps/ingestion/pipeline_health.py`;
2. novo
   `apps/ingestion/management/commands/check_ingestion_pipeline_health.py`;
3. novo `tests/unit/test_ingestion_pipeline_health.py`;
4. `deploy/README.md`.

Não editar models, migrations, views, templates, workers, Compose/systemd units
ou settings. Se o model `ClinicalEvent` estiver em caminho diferente, apenas
importe; não edite. Não criar dependência ou provider.

## TDD obrigatório

### RED

Testar com dados sintéticos, no mínimo:

1. cenário saudável exit 0;
2. succeeded admissions batch vazio unhealthy;
3. full-sync ausente após settling unhealthy e antes do settling ignorado;
4. demographics duplicada por batch+patient unhealthy;
5. active age abaixo/acima;
6. full-sync failure rate abaixo/acima e amostra mínima;
7. reasons agregados e events_created somados;
8. freshness omitido informativo, ativado saudável/velho/ausente;
9. argumentos inválidos;
10. snapshots de contagem dos modelos antes/depois idênticos;
11. spies provam zero Playwright/rede/call_command;
12. sentinelas de run/batch/patient/admission/event/URL/text não aparecem em
    stdout, stderr ou CommandError.

### GREEN

Implementar value objects/dataclasses simples para configuração, métricas e
violations; queries ORM agregadas e comparação efêmera sem devolver chaves
clínicas. Command valida args, renderiza allowlist e decide exit.

### REFACTOR

Evitar mega-query ilegível, N+1, floats sem unidade, threshold mágico,
`except Exception` com texto bruto ou dicionário livre de output. Não construir
framework de alertas.

## Checks de inspeção obrigatórios

```bash
rg -n "window.hours|settling|max.active|min.full.sync|failure.percent|max.*age" \
  apps/ingestion/management/commands/check_ingestion_pipeline_health.py \
  apps/ingestion/pipeline_health.py
rg -n "\.create\(|\.save\(|\.update\(|\.delete\(|bulk_|call_command|subprocess|playwright|requests|http" \
  apps/ingestion/pipeline_health.py \
  apps/ingestion/management/commands/check_ingestion_pipeline_health.py
rg -n "parameters_json|patient_source|prontuario|nome|content|error_message|pk|_id" \
  apps/ingestion/pipeline_health.py \
  apps/ingestion/management/commands/check_ingestion_pipeline_health.py
rg -n "healthy|empty|missing.*full|demograph|active.*age|sample|fresh|sentinel|read.only" \
  tests/unit/test_ingestion_pipeline_health.py
rg -n "check_ingestion_pipeline_health|systemd|threshold|aggregate|alert" \
  deploy/README.md
```

Interpretar ocorrências: acesso efêmero a `parameters_json` pode ser necessário
para correspondência, mas valor nunca deve sair do serviço; `_id`/PK não pode
integrar DTO/output; não pode haver método mutante ou rede.

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

- [ ] R1–R6 cobertos RED/GREEN.
- [ ] Três invariantes batch-bound falham corretamente.
- [ ] Queue age e full-sync rate respeitam thresholds/sample.
- [ ] Failure reasons/events e frescor são agregados.
- [ ] Command é read-only e sem ações externas.
- [ ] Saída/erro não contêm nenhuma sentinela identificável.
- [ ] Docs explicam uso sem configurar provider real.
- [ ] Máximo quatro arquivos; sem model/migration/infra nova.
- [ ] Gates exit 0; unit final >= baseline sem failures/errors.

### Condições automáticas de INCOMPLETO

- S1–S4/baseline/RED ausente ou falho;
- qualquer invariante/threshold sem teste;
- taxa alarma abaixo da amostra mínima;
- freshness omitido torna unhealthy;
- serviço/command muta DB ou chama fonte/rede;
- saída inclui qualquer ID, parâmetro, sentinela ou texto clínico;
- erro bruto/URL/credential pode escapar;
- model/migration/provider/infra é adicionado;
- arquivo extra/gate falho/relatório ausente/task prematura.

## Gates de autoavaliação

1. Quais testes provam cada causa unhealthy?
2. Como settling evita falso positivo de full-sync ainda não criado?
3. Como amostra mínima protege a taxa?
4. Onde chaves batch+patient deixam de existir antes do output?
5. Como foi provado read-only e sem rede?
6. Qual teste scanner prova privacidade?
7. Por que cada arquivo é necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-RPAP-S5-report.md` com Status, BASE_REF, matriz,
RED/GREEN, snippets, formato/allowlist, inspeções, prova read-only/privacidade,
baseline/final, gates, rerun, arquivos/justificativas, riscos e
`Handoff para verificador` R1–R6.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, all repair-persistent-admissions-pipeline
artifacts, SLICE-RPAP-S5.md and COMPLETE S1-S4 reports. Implement ONLY S5.
Follow the DeepSeek4-Flash protocol: clean BASE_REF, official unit baseline,
real RED for every invariant/threshold/privacy/read-only contract, minimal
GREEN, local clean-code/DRY/YAGNI refactor, mandatory rg and every official
gate, final unit exit 0 with zero failures/errors and passed >= baseline. Add a
one-shot aggregate check_ingestion_pipeline_health service/command and a
canary/recovery/rollback runbook; never mutate DB, call source/network, output
identifiers or add alert provider, models, migrations or infrastructure. Touch
only four listed files. Create
/tmp/sirhosp-slice-RPAP-S5-report.md with evidence and verifier handoff. Any
missing/failing item is INCOMPLETE with no task update/commit. If complete, mark
only S5, commit, push, reply REPORT_PATH=..., then STOP.
```
