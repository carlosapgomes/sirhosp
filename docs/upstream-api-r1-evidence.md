# Evidência R1 — a foto do censo aparece inteira ou não aparece

Pacote de evidência **R1** da change arquivada `sirhosp-upstream-api-v1`
(commit `9f2398e`), coletado em **2026-11-10** para destravar o go-live do
consumidor (`hgproxy`).

Este documento não altera contrato: ele registra o que foi executado, contra
qual código, com quais fixtures, o que ficou comprovado e o que continua fora
do escopo. O contrato de consumo permanece em `docs/upstream-api.md`.

## 1. Enunciado de R1 e por que ele importa

> **R1** — uma foto aparece na API inteira (exatamente um ciclo concluído) ou
> não aparece; ciclos `queued`, `running` e `failed` nunca são expostos.

O consumidor publica presença a partir da foto e deriva chegadas e partidas
comparando com o conjunto anterior (seção 6 de `docs/upstream-api.md`). Se a
API pudesse servir meio ciclo — linhas parcialmente gravadas, linhas de dois
ciclos misturadas ou linhas de um ciclo que ainda está rodando — o consumidor
registraria altas e saídas falsas em produção. Por isso R1 é o requisito que
autoriza o go-live: ele garante que a unidade de leitura é **o ciclo**, nunca a
linha.

R1 é a soma de quatro requisitos da spec
(`openspec/specs/upstream-read-api/spec.md`):

| Requisito da spec                          | O que exige                                                                      |
| ------------------------------------------ | -------------------------------------------------------------------------------- |
| Photo exposes only completed cycles        | a foto corresponde integralmente a um ciclo com `status = succeeded` e ≥ 1 linha |
| Missing photo answers not found            | sem ciclo concluído com linhas, a resposta é `404 no_snapshot`, nunca foto vazia |
| Empty census photo is a valid response     | ciclo concluído sem pacientes é `200` com `patients: []` e `row_count: 0`        |
| Invalid patient rows fail the photo closed | linha de paciente sem `nome` recusa a foto inteira com `500 internal_error`      |

Decisão de design correspondente: **D3** em
`openspec/changes/archive/2026-11-10-sirhosp-upstream-api-v1/design.md`
(persistência atômica + filtro de run elegível + desempate por `cycle_seq`).

## 2. Escopo, data e ambiente da coleta

| Item                | Valor                                                                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Data da coleta      | 2026-11-10, entre 18:43 e 19:13 (America/Bahia, `-03:00`)                                                                             |
| Commit avaliado     | `9f2398e4b9c942c8d63b98192dbc401d3c7eff42` (árvore de trabalho limpa durante a coleta)                                                |
| Artefato versionado | apenas este documento; nenhum código, teste, configuração, compose ou gunicorn foi alterado                                           |
| Python (container)  | 3.12.14                                                                                                                               |
| Imagem de aplicação | `sirhosp-test-test-runner` (`Dockerfile` target `prod`, conforme `compose.test.yml`)                                                  |
| Servidor HTTP       | gunicorn 25.3.0, `gthread`, 1 worker, iniciado por `docker/gunicorn-wrapper.sh` com `config/gunicorn.conf.py`                         |
| Banco da sonda      | banco **descartável e isolado** `r1_probe_evidence` em `postgres:16-alpine` (PostgreSQL 16.14), migrado do zero e descartado ao final |
| Banco dos testes    | banco de teste isolado do `scripts/test-in-container.sh` (porta 55435), recriado a cada execução                                      |
| Credencial          | token sintético de teste, valor omitido de propósito deste documento                                                                  |
| Dados               | somente fixtures sintéticas (ver seção 2.1); nenhum dado clínico real, URL real ou nome de sistema de origem                          |
| Validação deste doc | `./scripts/markdown-lint.sh` → 988 arquivos, 0 erros, em 2026-11-10 19:13 (`/tmp/upa-r1-pack/markdown-lint.log`)                      |

Todos os logs citados estão em `/tmp/upa-r1-pack/` e foram gerados nesta
coleta, com data, comando e código de saída registrados no próprio arquivo.

### 2.1 Fixtures sintéticas usadas

| Identificador | Papel na sonda                                                     |
| ------------- | ------------------------------------------------------------------ |
| `0000001..3`  | pacientes do ciclo concluído `a` (3 linhas de paciente)            |
| `0000011/12`  | pacientes do ciclo concluído `d`, com o mesmo `captured_at` de `a` |
| `0000021`     | paciente do ciclo `b` (`running`, captura posterior)               |
| `0000031`     | paciente do ciclo `c` (`failed`, captura ainda posterior)          |
| `0000051/52`  | ciclo inválido (`0000052` sem `nome`)                              |

Nomes: `PACIENTE EXEMPLO ...`. Setores: `CLINICA MEDICA`, `UTI ADULTO`,
`OMEGA`. Linhas de leito vago usam `prontuario` vazio e `nome` `DESOCUPADO`.
Nenhum valor corresponde a paciente, leito, setor ou origem real.

## 3. Camada 1 — persistência atômica do ciclo

`apps/census/management/commands/extract_census.py:267-280` promove, dentro de
**uma única** `transaction.atomic()`:

- as linhas do ciclo (`CensusSnapshot.objects.bulk_create(snapshots)`, linha
  268);
- a métrica de estágio de persistência aceita (linhas 269-275);
- a promoção do run a `succeeded` com `finished_at` (linhas 276-280).

O comentário imediatamente acima do bloco (linhas 264-266) registra a intenção:
"a failure after insertion rolls back the whole new set". Ou seja, o commit
publica **linhas + estado `succeeded` juntos**; um erro posterior desfaz as
linhas. Os caminhos de falha anteriores à inserção marcam o run como `failed`
sem gravar linhas (`_reject_persistence`,
`apps/census/management/commands/extract_census.py:323-350`; gate de
completude em `:205-230`).

Invariante de escritor único verificada na coleta: as **únicas** ocorrências de
criação de `CensusSnapshot` em `apps/` estão em `extract_census.py` (linha 234,
instanciação, e linha 268, `bulk_create`). Nenhum outro módulo grava linhas do
censo; `apps/services_portal`, `apps/statistics_reports` e `apps/ingestion`
apenas leem.

Consequência para o consumidor: não existe estado intermediário observável em
que um ciclo tenha linhas publicadas e run ainda não promovido. O leitor vê o
ciclo inteiro (linhas + `succeeded`) ou o ciclo anterior.

## 4. Camada 2 — filtro de run elegível, ciclo inteiro e desempate

`apps/upstream_api/photo.py` seleciona o ciclo e `apps/upstream_api/views.py`
serializa a resposta:

| Garantia                                                               | Onde está no código                |
| ---------------------------------------------------------------------- | ---------------------------------- |
| somente `intent = census_extraction`                                   | `apps/upstream_api/photo.py:55`    |
| somente `status = succeeded` (nunca `queued`/`running`/`failed`)       | `apps/upstream_api/photo.py:56`    |
| ao menos uma linha de snapshot (run sem linhas não é elegível)         | `apps/upstream_api/photo.py:58-59` |
| ordem `MIN(captured_at)` DESC e, no empate, pk do run DESC             | `apps/upstream_api/photo.py:58-60` |
| linhas lidas por `ingestion_run_id` do run servido (nunca mistura)     | `apps/upstream_api/photo.py:76`    |
| só pacientes (`prontuario` não vazio) e ordem estável                  | `apps/upstream_api/photo.py:77-78` |
| linha de paciente sem `nome` recusa a foto inteira (`InvalidPhotoRow`) | `apps/upstream_api/photo.py:79-80` |
| `cycle_seq` é o pk do run servido                                      | `apps/upstream_api/photo.py:93`    |
| sem run elegível → `404 no_snapshot`                                   | `apps/upstream_api/views.py:83-84` |
| `row_count` = número de pacientes devolvidos                           | `apps/upstream_api/views.py:88`    |
| `InvalidPhotoRow` e falha inesperada → `500 internal_error` genérico   | `apps/upstream_api/views.py:91-96` |
| registro de falha só com método, rota e status                         | `apps/upstream_api/views.py:67-74` |
| logger de acesso sanitizado ligado ao gunicorn                         | `config/gunicorn.conf.py:74`       |
| filtro de `django.request` para o target `/api/v1`                     | `config/settings.py:161-167`       |

O filtro é defesa em profundidade sobre a atomicidade da camada 1: mesmo que a
persistência deixasse de ser atômica, o leitor só serviria runs `succeeded`
com linhas. A leitura é sempre **por run id**, o que impede qualquer mistura de
ciclos — inclusive o caso teórico de dois ciclos com o mesmo `captured_at`, em
que o desempate por pk mantém `cycle_seq` distinto e a foto do ciclo mais novo
não é perdida pelo consumidor.

## 5. Evidência por teste

Todos os comandos abaixo rodaram nos containers oficiais
(`./scripts/test-in-container.sh`, `compose.test.yml`), com o banco de teste
isolado, em 2026-11-10. Logs em `/tmp/upa-r1-pack/`.

### 5.1 Execução focada em R1 (T1)

Comando exato (equivale ao que o `scripts/test-in-container.sh` executa, com
`-v` para registrar caso por caso):

```bash
export POSTGRES_PORT=55435
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml up -d db
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm test-runner \
  bash -lc "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -v \
  tests/unit/test_upstream_api_photo_query.py \
  tests/integration/test_upstream_api_photo_http.py"
```

O script oficial não aceita filtro de arquivos; a execução focada usou o mesmo
`docker compose ... run test-runner` que ele executa, no mesmo banco de teste
isolado, replicando a limpeza prévia de sessões residuais e a recriação do banco
`test_sirhosp`.

Resultado: **31 passed**, código de saída **0**, em 2026-11-10 18:43 (`-03:00`).
Log: `/tmp/upa-r1-pack/focused-r1-tests.log`; código de saída:
`/tmp/upa-r1-pack/focused-r1-tests.exit`.

#### 5.1.1 Unit — `tests/unit/test_upstream_api_photo_query.py` (11 casos)

| Caso                                                                      | O que prova                                                                                     | Resultado 2026-11-10 |
| ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | -------------------- |
| `test_no_eligible_run_yields_no_photo`                                    | sem run elegível (só `running`/`queued`/`failed`) não há foto: `build_current_photo()` é `None` | PASS                 |
| `test_newest_capture_wins`                                                | o ciclo de captura mais recente vence                                                           | PASS                 |
| `test_running_and_failed_cycles_never_surface`                            | linhas de ciclo `running` (captura posterior) e `failed` nunca aparecem na foto                 | PASS                 |
| `test_succeeded_run_without_rows_is_not_eligible`                         | run `succeeded` sem linhas não é elegível                                                       | PASS                 |
| `test_rows_without_a_run_never_surface`                                   | linha legada com `ingestion_run` nulo nunca surge                                               | PASS                 |
| `test_capture_order_wins_over_finish_order`                               | ordem de captura decide; `finished_at` é ignorado                                               | PASS                 |
| `test_shared_captured_at_resolves_by_run_primary_key_without_mixing_rows` | empate resolvido pelo pk maior e **todas** as linhas vêm do mesmo run (sem mistura)             | PASS                 |
| `test_cycle_seq_is_the_served_run_primary_key`                            | `cycle_seq` é o pk do run servido, inteiro (não booleano)                                       | PASS                 |
| `test_cycles_sharing_one_captured_at_carry_distinct_cycle_seqs`           | ciclos empatados no `captured_at` têm `cycle_seq` distintos                                     | PASS                 |
| `test_cycle_without_patient_rows_still_carries_its_cycle_seq`             | ciclo só com leitos vagos serve foto vazia e mantém identidade (`cycle_seq`)                    | PASS                 |
| `test_non_census_intents_are_not_eligible`                                | `intent != census_extraction` nunca é elegível                                                  | PASS                 |

#### 5.1.2 Integration — `tests/integration/test_upstream_api_photo_http.py` (20 casos)

Casos que provam R1 diretamente:

| Caso                                                                    | O que prova                                                                                                    | Resultado 2026-11-10 |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | -------------------- |
| `test_missing_photo_answers_404_no_snapshot[queued]`                    | ciclo `queued` sozinho → `404 no_snapshot` com `Cache-Control: no-store`                                       | PASS                 |
| `test_missing_photo_answers_404_no_snapshot[running]`                   | ciclo `running` sozinho → `404 no_snapshot`                                                                    | PASS                 |
| `test_missing_photo_answers_404_no_snapshot[failed]`                    | ciclo `failed` sozinho → `404 no_snapshot`                                                                     | PASS                 |
| `test_empty_completed_photo_is_200_with_no_patients`                    | ciclo concluído sem pacientes → `200`, `patients: []`, `row_count: 0`, `cycle_seq` presente                    | PASS                 |
| `test_invalid_patient_row_fails_the_whole_photo`                        | uma linha de paciente sem `nome` recusa a foto inteira: `500 internal_error` sem identificadores nem traceback | PASS                 |
| `test_repeated_polls_are_identical_and_persist_nothing`                 | dois polls sem escrita devolvem conteúdo byte-idêntico e não criam/alteram linhas                              | PASS                 |
| `test_photo_returns_patient_rows_with_the_exact_row_contract`           | foto com 1 paciente + 1 leito vago: `row_count = 1`, contrato de linha exato                                   | PASS                 |
| `test_photo_exposes_the_served_cycle_seq`                               | `cycle_seq` do ciclo servido presente na resposta HTTP                                                         | PASS                 |
| `test_cycle_seq_distinguishes_cycles_sharing_one_captured_at`           | dois ciclos com o mesmo `captured_at`: serve o de maior pk e não mistura linhas                                | PASS                 |
| `test_repeated_polls_repeat_the_captured_at_and_cycle_seq_pair`         | o par (`captured_at`, `cycle_seq`) é estável entre polls                                                       | PASS                 |
| `test_rows_order_by_sector_code_bed_and_prontuario`                     | ordem determinística das linhas do ciclo                                                                       | PASS                 |
| `test_duplicate_row_keys_order_by_primary_key_and_stay_stable`          | chaves duplicadas ordenam por pk, estável entre polls                                                          | PASS                 |
| `test_sector_pairs_sharing_one_code_stay_distinct`                      | pares (`setor_codigo`, `setor`) preservados; nenhuma linha do ciclo é colapsada                                | PASS                 |
| `test_patient_without_a_bed_keeps_an_empty_leito`                       | paciente sem leito mantém `prontuario`/`nome` e `leito` vazio (linha não é descartada)                         | PASS                 |
| `test_source_timestamps_stay_null_when_the_source_informed_only_a_date` | `source_*_at` nulo quando a origem só informou data (sem horário fabricado)                                    | PASS                 |
| `test_invalid_row_failure_logs_method_route_and_status_only`            | a falha de linha inválida registra só método, rota e status                                                    | PASS                 |
| `test_unexpected_failure_logs_method_route_and_status_only`             | falha inesperada registra só método, rota e status (sem dado bruto)                                            | PASS                 |

Casos do mesmo arquivo que exercitam a fronteira adjacente (não são R1, mas
rodaram na mesma execução):

| Caso                                                         | O que prova                                                   | Resultado 2026-11-10 |
| ------------------------------------------------------------ | ------------------------------------------------------------- | -------------------- |
| `test_unauthenticated_post_is_refused_with_401_not_csrf_403` | POST sem credencial responde `401`, não `403` de CSRF         | PASS                 |
| `test_authenticated_post_answers_405_and_keeps_no_store`     | método não permitido responde `405` mantendo `no-store`       | PASS                 |
| `test_flagged_portal_session_is_not_redirected_on_the_api`   | sessão de portal com troca de senha pendente não desvia a API | PASS                 |

### 5.2 Suítes completas (T2, T3)

| Execução | Comando exato                                | Resultado em 2026-11-10                             | Log                                      |
| -------- | -------------------------------------------- | --------------------------------------------------- | ---------------------------------------- |
| T2       | `./scripts/test-in-container.sh unit`        | `4699 passed`, saída **0** (18:43–18:50)            | `/tmp/upa-r1-pack/unit-suite.log`        |
| T3       | `./scripts/test-in-container.sh integration` | `1188 passed, 36 failed`, saída **1** (18:50–19:03) | `/tmp/upa-r1-pack/integration-suite.log` |

**Nenhum** teste de `tests/integration/test_upstream_api_*` falhou em T3
(verificado por `grep '^FAILED' | grep upstream` → vazio; todos os 20 casos da
foto passaram dentro da suíte completa).

As 36 falhas de T3 são de outra área e **não são evidência sobre R1**:
`test_summary_parallel_pipeline.py` (15), `test_summary_two_phase_orchestration.py`
(20) e `test_summary_worker_lifecycle.py` (1). Todas falham com o mesmo erro de
ambiente no container de teste:
`RuntimeError: No LLM API key found. Set SUMMARY_PHASE1_API_KEY or LLM_API_KEY
(or OPENAI_API_KEY) in your environment.` — ou seja, ausência de chave de LLM no
`compose.test.yml`. A coleta **não** alterou nem corrigiu nada nessa área; o
estado é o do commit `9f2398e`, idêntico ao que o gate final da change veria
neste ambiente.

## 6. Sonda de runtime (prova de mecanismo ponta a ponta)

Objetivo: provar R1 no caminho real HTTP — gunicorn com a configuração do
repositório, incluindo o logger sanitizado — sobre um banco descartável com
fixtures sintéticas, sem tocar em banco de desenvolvimento ou produção.

| Item             | Valor                                                                                                                      |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Data             | 2026-11-10, 19:07:48–19:08:01 (`-03:00` no transcript do driver; container em UTC)                                         |
| Processo         | `docker/gunicorn-wrapper.sh` → gunicorn 25.3.0, `config/gunicorn.conf.py`, 1 worker `gthread`, `bind 0.0.0.0:8000` interno |
| Banco            | `r1_probe_evidence`, criado vazio, migrado do zero, descartado após a coleta                                               |
| Token            | sintético, valor omitido                                                                                                   |
| Transcript       | `/tmp/upa-r1-pack/probe-run.log` (código de saída `0`, em `probe-run.exit`)                                                |
| Scripts          | `/tmp/upa-r1-pack/probe.sh`, `/tmp/upa-r1-pack/driver.py`                                                                  |
| Asserções        | **38** no driver (38 PASS / 0 FAIL) + **13** no lado host (13 PASS / 0 FAIL)                                               |
| Log de asserções | `/tmp/upa-r1-pack/probe-assertions.log` (host)                                                                             |
| Região de log    | `/tmp/upa-r1-pack/probe-gunicorn-region.log` (extração do log emitido pelo gunicorn)                                       |
| Teardown         | `/tmp/upa-r1-pack/teardown.log` (`DROP DATABASE r1_probe_evidence` + `compose down`, saída 0)                              |

Comando exato da sonda:

```bash
export POSTGRES_PORT=55435
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml up -d db
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml \
  exec -T db psql -U sirhosp -d postgres \
  -c 'DROP DATABASE IF EXISTS "r1_probe_evidence";' \
  -c 'CREATE DATABASE "r1_probe_evidence";'
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm \
  -e POSTGRES_DB=r1_probe_evidence -e UV_NO_SYNC=1 \
  -e SIRHOSP_UPSTREAM_API_TOKEN=<token sintetico> \
  -e GUNICORN_WORKERS=1 -e GUNICORN_THREADS=1 \
  -v /tmp/upa-r1-pack:/probe:ro \
  test-runner bash /probe/probe.sh
bash /tmp/upa-r1-pack/host-assertions.sh   # asserções sobre o log emitido
```

### 6.1 Estados semeados

| Estado   | Run                                    | Conteúdo                                                                                                     |
| -------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `a`      | pk 1, `succeeded`, `census_extraction` | `captured_at 08:00 -03:00`; 4 linhas, sendo 3 de paciente (`0000001..3`) e 1 leito vago (`prontuario` vazio) |
| `b`      | pk 2, `running`                        | 1 paciente (`0000021`) com `captured_at 10:00 -03:00` (posterior a `a`)                                      |
| `c`      | pk 3, `failed`                         | 1 paciente (`0000031`) com `captured_at 12:00 -03:00` (posterior a `b`)                                      |
| `d`      | pk 4, `succeeded`                      | 2 pacientes (`0000011`, `0000012`) com o **mesmo** `captured_at` de `a`                                      |
| inválido | pk 5, `succeeded`                      | 2 pacientes, um deles (`0000052`) com `nome` vazio                                                           |

Os ciclos `b` e `c` existem no banco com captura **mais recente** que a foto
servida: a exclusão vem do filtro de elegibilidade, não da ausência de dados.

### 6.2 Fases, respostas e assertivas

| Fase      | Requisição (sintética)                                              | Resposta                                 | Assertivas centrais                                                                                                                                                |
| --------- | ------------------------------------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| r1-0      | `GET /api/v1/inpatients/current` sem credencial                     | `401 unauthorized`, `no-store`           | gate Bearer ativo no processo real                                                                                                                                 |
| r1-1      | foto com token, banco com `a` + `b` + `c`                           | `200`; `cycle_seq 1`, `row_count 3`      | foto = ciclo `a`; `row_count` = nº de pacientes; nenhuma linha de `b`/`c`; todas as linhas servidas compartilham o `captured_at` da foto; `b`/`c` existem no banco |
| r1-2      | foto com token, depois de semear `d` (mesmo `captured_at` de `a`)   | `200`; `cycle_seq 4`, `row_count 2`      | desempate pelo maior pk; `captured_at` inalterado; nenhuma linha de `a` misturada; dois ciclos empatados no banco                                                  |
| r1-2b/1-3 | dois polls adicionais sem escrita                                   | `200`, bytes idênticos                   | identidade (`captured_at`, `cycle_seq`) estável                                                                                                                    |
| r1-4      | foto com query string sintética (`?prontuario=...&token=sintetico`) | `200`, bytes idênticos ao poll sem query | query não altera a foto; e o log emitido não contém query nem identificador                                                                                        |
| r1-5      | foto após rebaixar todos os runs `succeeded` para `failed`          | `404 no_snapshot`, `no-store`            | linhas continuam no banco (8 linhas) ⇒ ausência de **elegibilidade**, não de dado; erro sem corpo de foto                                                          |
| r1-6      | foto com ciclo concluído contendo linha de paciente sem `nome`      | `500 internal_error`, `no-store`         | falha fechada da foto inteira; mensagem genérica, sem traceback, sem tipo de exceção e sem prontuário                                                              |

Trechos do transcript (todos sintéticos):

```text
[19:07:59] RESP r1-1-foto-ciclo-concluido status=200 cache-control=no-store
[19:07:59] BODY r1-1-foto-ciclo-concluido {"captured_at": "2026-09-06T11:00:00+00:00", "cycle_seq": 1, "row_count": 3, "patients": [... 0000001, 0000002, 0000003 ...]}
[19:07:59] BODY r1-2-foto-empate-captured_at {"captured_at": "2026-09-06T11:00:00+00:00", "cycle_seq": 4, "row_count": 2, "patients": [... 0000011, 0000012 ...]}
[19:07:59] BODY r1-5-foto-sem-ciclo-elegivel {"error": {"code": "no_snapshot", "message": "No completed census snapshot is available."}}
[19:07:59] BODY r1-6-foto-com-linha-invalida {"error": {"code": "internal_error", "message": "Internal error."}}
```

O `captured_at` servido aparece em `+00:00` porque o banco devolve o instante
em UTC; o offset é explícito, como a spec exige. O instante é o semeado
(`2026-09-06T08:00:00-03:00`), e a comparação da sonda é feita por instante,
não por string.

### 6.3 Sanitização do log emitido

Região emitida pelo gunicorn (9 requisições, 1 registro de acesso por
requisição), extraída em `/tmp/upa-r1-pack/probe-gunicorn-region.log`:

```text
Unauthorized: /api/v1/inpatients/current
GET /api/v1/inpatients/current 401
Unauthorized: /api/v1/inpatients/current
GET /api/v1/inpatients/current 401
GET /api/v1/inpatients/current 200
GET /api/v1/inpatients/current 200
GET /api/v1/inpatients/current 200
GET /api/v1/inpatients/current 200
GET /api/v1/inpatients/current 200
Not Found: /api/v1/inpatients/current
GET /api/v1/inpatients/current 404
upstream_api method=GET route=/api/v1/inpatients/current status=500
Internal Server Error: /api/v1/inpatients/current
GET /api/v1/inpatients/current 500
```

Assertivas de sanitização (todas PASS em `probe-assertions.log`):

- 9 registros de acesso, exatamente 1 por requisição (2×401, 5×200, 1×404, 1×500);
- nenhum registro `/api/v1` contém `?`, `prontuario=`, `token=`, prontuário,
  nome de paciente ou nome de setor;
- o token sintético não aparece no log emitido;
- registros de erro do framework saem com a rota fixa (`Not Found:` /
  `Internal Server Error: /api/v1/inpatients/current`) e o registro da aplicação
  sai como `upstream_api method=GET route=... status=500`;
- todo identificador presente no transcript pertence ao conjunto declarado de
  fixtures sintéticas (seção 2.1) — nenhum identificador estranho ao conjunto.

## 7. O que esta evidência **não** prova

Limitações explícitas, para que o consumidor e o operador não superestimem o
pack:

1. **Concorrência real de leitura durante o commit não foi exercitada.** Não
   houve leitura HTTP concorrente com uma transação de persistência em
   andamento (isso exigiria pausar a transação no meio). A garantia é
   estrutural: a promoção de linhas + `succeeded` ocorre em uma única
   `transaction.atomic()` (`extract_census.py:267-280`), então um leitor externo
   vê o estado anterior ou o posterior, nunca o intermediário; e o filtro de
   elegibilidade (`photo.py:51-63`) exclui qualquer run não promovido. A sonda
   comprova o efeito observável (nunca meio ciclo), não a corrida em si.
2. **A sonda não executou `extract_census` contra a origem real.** Os estados
   foram semeados via ORM respeitando as invariantes do pipeline (linhas ligadas
   ao run + run promovido a `succeeded`). A promoção atômica é evidenciada por
   código (seção 3) e pelos testes/integrações existentes, não por uma extração
   real nesta coleta.
3. **`queued` não apareceu na sonda de runtime.** A sonda cobriu `running` e
   `failed`; `queued` é coberto pelos testes parametrizados
   (`test_missing_photo_answers_404_no_snapshot[queued]`) e pelo filtro de
   status, que trata os três estados de forma idêntica.
4. **Sem volume, latência ou carga.** Não há prova de comportamento com N
   grande de linhas, múltiplos consumidores simultâneos ou polling concorrente.
5. **Sem proxy reverso, TLS ou segmentação de rede.** A seção 8.1 de
   `docs/upstream-api.md` atribui isso ao operador; nada aqui valida a borda.
6. **As 36 falhas da suíte de integração completa não foram investigadas nem
   corrigidas** (ausência de chave de LLM no ambiente de teste, área de
   sumários). Elas não tocam `apps/upstream_api` e não alteram a evidência de R1,
   mas o gate final da change neste ambiente continua vermelho por esse motivo.
7. **`UV_NO_SYNC=1` no harness.** No container `test-runner` (imagem `prod`,
   `venv` de root), `uv run` do wrapper tentaria sincronizar dependências de
   desenvolvimento e falharia por permissão. A coleta exportou `UV_NO_SYNC=1`
   para o `uv run` do wrapper rodar sem sync. É artefato do harness de teste: o
   `docker/gunicorn-wrapper.sh` e o `config/gunicorn.conf.py` não foram
   alterados.
8. **Portal fora de escopo.** O comportamento de `/beds/` (que usa
   `Max("captured_at")`, sem filtro de status) não foi verificado nem alterado.
9. **Não é autorização de go-live por si só.** Token, rede e proxy continuam
   sendo responsabilidade do operador; a checklist da seção 8 lista o que falta.

## 8. Checklist de ativação do consumidor (`hgproxy`)

O que o consumidor ainda precisa fazer antes de publicar presença em produção:

- [ ] Receber o token por canal privado do operador, gravando-o em arquivo com
      permissão `600` (seção 3 de `docs/upstream-api.md`); nunca em log,
      ticket, repositório ou variável de perfil compartilhado.
- [ ] Configurar `BASE_URL` interna e o token, e confirmar `401` sem credencial
      e `200` com credencial (seções 9.2 e 9.3 do guia).
- [ ] Implementar a deduplicação pelo par (`captured_at`, `cycle_seq`): par
      igual é **no-op**; par novo processa a foto inteira (seção 6 do guia).
- [ ] Tratar `404 no_snapshot` como ausência de dado (não como censo vazio),
      `500 internal_error` como indisponibilidade com backoff, e foto vazia
      (`patients: []`, `row_count: 0`) como ciclo concluído válido.
- [ ] Não inferir nada de `cycle_seq` além da ordem entre ciclos servidos
      (valor opaco, crescente, igual ao pk do run).
- [ ] Aplicar a mesma disciplina de log do servidor: sem payload, nome ou
      prontuário em log da aplicação consumidora.
- [ ] Definir a janela de polling (sugestão de 2 h) e alerta de staleness
      (`now - captured_at` crescente).
- [ ] Fazer a primeira observação assistida de uma transição real de ciclo: o
      par muda uma vez, a foto nova chega inteira e o processamento publica
      chegadas/partidas coerentes. Esta sonda prova o mecanismo; a primeira
      transição em produção com dado real é observação operacional, não
      evidência desta coleta.
- [ ] Aceitar explicitamente as lacunas do contrato: internações mais curtas que
      o intervalo de polling podem não aparecer; não há backfill de fotos;
      estado em `404` persistente deve ser escalado ao operador.
- [ ] Saber que um `500 internal_error` persistente pode significar linha
      inválida recusando a foto inteira (falha fechada, D10) — nesse caso
      acionar o operador em vez de retentar indefinidamente.

## 9. Referências

- Spec: `openspec/specs/upstream-read-api/spec.md` (requisitos de foto,
  `no_snapshot`, foto vazia e linha inválida).
- Design: `openspec/changes/archive/2026-11-10-sirhosp-upstream-api-v1/design.md`
  (D3, D6, D10).
- Slices: `.../slices/slice-001-photo-endpoint.md` (R5/R7) e
  `.../slices/slice-004-cycle-sequence-field.md` (`cycle_seq`).
- Código: `apps/upstream_api/photo.py`, `apps/upstream_api/views.py`,
  `apps/upstream_api/access_log.py`,
  `apps/census/management/commands/extract_census.py`.
- Configuração: `config/gunicorn.conf.py`, `config/settings.py`.
- Contrato do consumidor: `docs/upstream-api.md` (seções 4, 6, 7, 9 e 10).
- Evidência bruta desta coleta: `/tmp/upa-r1-pack/` (`focused-r1-tests.log`,
  `unit-suite.log`, `integration-suite.log`, `probe-run.log`,
  `probe-assertions.log`, `probe-gunicorn-region.log`, `teardown.log`,
  `markdown-lint.log`, `RUN-METADATA.txt`).
