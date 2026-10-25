# RCD-S2 — Pino de caracterização `/beds` (título + ordenação alfabética)

## Handoff para implementador LLM com contexto zero

Leia integralmente, na ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. `openspec/changes/rename-enf-2b-card-display-name/proposal.md` e
   `design.md` (D4 é a decisão central deste slice);
3. Delta `openspec/changes/rename-enf-2b-card-display-name/specs/bed-status-capacity-view/spec.md`
   e, para base, `openspec/specs/bed-status-capacity-view/spec.md`;
4. `tests/unit/test_bed_status_view.py` — `test_cardio_shared_group_two_sources_capacity_once`
   (~:2334-2381) é o MODELO deste slice: helpers `self._v4_catalog(today,
groups)`, `self._run()`, `self._snapshot(...)`, `self._materialize(run.pk)`,
   `self._render(admin_client)` e o estilo de asserções sobre
   `response.context["units"]` e `response.content.decode()`;
5. `apps/census/occupancy.py` — SOMENTE LEITURA: `:4195` (ordenacao por
   `unit.title`, caminho v5; caminhos legados repetem o padrão em `:3369` e
   `:3642`) e `:3189-3206` (`_component_title` usa o `display_name` do
   grupo). Este change NÃO edita código de produção.

## Protocolo obrigatório

BASE_REF + árvore limpa; matriz requisito→arquivo→teste; este slice é de
**caracterização** (AGENTS.md §5): não há código de produção a escrever,logo
RED-TDD clássico não se aplica — a evidência obrigatória é o **controle de
mutação** descrito abaixo. Sem quality-gate global (tasks.md §4). Host-only
pytest é diagnóstico, não gate. Falha de verificação local ⇒ INCOMPLETO.

## Objetivo do slice

Fixar como regressão o comportamento observável em `/beds` que motiva o
change: com um catálogo vigente contendo `ENF-2B-CARD.display_name =
"Enfermaria 2B Cardio"`, a unidade renderiza exatamente o título
`Enfermaria 2B Cardio` (nunca o rótulo composto legado) e aparece entre os
pares `Enfermaria 2…` na ordenação alfabética por título.

**Escopo da prova (importante)**: o teste caracteriza a lógica COMPARTILHADA
de apresentação — título via `_component_title` + ordenação por título,
idêntica nos caminhos v4/v5. O helper `_v4_catalog` grava
`algorithm_version: "occupancy-v4"` (`test_bed_status_view.py:2041-2047`),
logo o teste NÃO exercita o branch v5/v6 literal; a aplicabilidade do v6 é
comprovada pelos testes de contrato do S1 e pela verificação operacional
pós-publicação (tasks.md §5.2).

## Requisitos verificáveis

- **R1 — Título exato**: com catálogo sintético de 3 grupos (`ENF-2A-HEMA`
  `Enfermaria 2A Oncohemato`; `ENF-2B-CARD` `Enfermaria 2B Cardio` com
  membros `719` + `2156` e capacidade 15; `ENF-2B-NEURO`
  `Enfermaria 2B Neuroclínica`), a unidade do Cardio exibe
  `unit.title == "Enfermaria 2B Cardio"` e a string `Cardioclinica /` NÃO
  aparece em `response.content`.
- **R2 — Posição alfabética**: `[u.title for u in units]` ==
  `["Enfermaria 2A Oncohemato", "Enfermaria 2B Cardio",
"Enfermaria 2B Neuroclínica"]` (ordenação por título coloca o Cardio junto
  dos pares do 2º andar).
- **R3 — Capacidade uma única vez**: `content.count("Capacidade: 15") == 1`
  para o grupo compartilhado 719+2156 (comportamento já pinado no teste
  modelo — preservar no novo cenário de 3 grupos).
- **R4 — Evidência de caracterização**: controle de mutação registrado no
  relatório (ver TDD abaixo).

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s)                | Teste/check                                                             |
| --------- | ------------------------------------- | ----------------------------------------------------------------------- |
| R1        | `tests/unit/test_bed_status_view.py`  | asserts `unit.title` e `"Cardioclinica /" not in content` no teste novo |
| R2        | `tests/unit/test_bed_status_view.py`  | assert da lista exata de títulos                                        |
| R3        | `tests/unit/test_bed_status_view.py`  | `content.count("Capacidade: 15") == 1`                                  |
| R4        | `/tmp/sirhosp-slice-RCD-S2-report.md` | registro do ciclo mutação→vermelho→reversão→verde                       |

Nome do teste novo: `test_cardio_renamed_group_sorts_with_enfermaria_2b_peers`
(imediatamente após `test_cardio_shared_group_two_sources_capacity_once`),
reusando os helpers existentes. Códigos sintéticos para os pares (ex.:
`"9001"` para 2A Hema e `"9002"` para 2B Neuro, um snapshot ocupado em cada),
capacidades à escolha do implementador (ex.: 10 e 12) — o essencial é a
ordem alfabética dos três títulos.

## Arquivos esperados e limite

Máximo de **1 arquivo**:

1. `tests/unit/test_bed_status_view.py` (apenas adições).

`allowed_incidental_files`: nenhum. Fora de escopo (proibido): qualquer
arquivo em `apps/`, templates, URLs, fixtures, outros testes. Precisando de
outro arquivo, pare e peça emenda.

## TDD obrigatório (caracterização com controle de mutação)

RED-TDD clássico não se aplica: não há código a implementar — o comportamento
já emerge de `occupancy.py:4195` + `display_name` (design D4). O novo teste
DEVE passar de primeira; a prova de que ele guarda o comportamento é a
mutação controlada:

1. Escreva o teste; rode o comando focado (abaixo) — resultado esperado:
   exit 0 (baseline da caracterização).
2. Controle de mutação: inverta TEMPORARIAMENTE a ordem esperada em R2 (ex.:
   `["Enfermaria 2A Oncohemato", "Enfermaria 2B Neuroclínica",
"Enfermaria 2B Cardio"]`) — o mesmo comando DEVE falhar (exit != 0),
   provando que o teste detecta ordem errada. Registre a saída.
3. Reverta a expectativa — o comando volta a exit 0.

Comando focado:

```bash
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml up -d db
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm \
  test-runner bash -lc "uv run --no-sync pytest -q -p no:cacheprovider \
  tests/unit/test_bed_status_view.py -k test_cardio_renamed_group_sorts_with_enfermaria_2b_peers"
```

### GREEN / verificação local

1. Mesmo comando do focado — exit 0 (após reversão da mutação).
2. Regressão próxima: arquivo completo
   `tests/unit/test_bed_status_view.py` no container — exit 0.
3. Lint: `uv run ruff check tests/unit/test_bed_status_view.py` — exit 0.
   Para `ruff format --check`: exit 0 OU, quando houver drift pré-existente
   do BASE_REF, prova de **zero drift incremental** (mesmos hunks do commit
   base, nenhum hunk tocando as linhas adicionadas; precedente Emenda B do
   change arquivado `2026-09-21-censo-residual-finding-filter`, ver Emenda A
   em `tasks.md` deste change).

Não rode a suíte completa nem o quality-gate global dentro do slice.

## Critérios de aceitação

- [ ] Teste novo presente, apenas adição, espelhando o teste modelo;
- [ ] R1–R3 asserções presentes e verdes (exit 0);
- [ ] Ciclo de mutação completo registrado (vermelho com ordem invertida,
      verde após reversão);
- [ ] Nota de escopo da caracterização registrada no relatório (branch v4
      sintético; não prova o branch v5/v6 literal);
- [ ] Diff = 1 arquivo; zero mudança em `apps/`;
- [ ] Relatório `/tmp/sirhosp-slice-RCD-S2-report.md` com comandos, exit
      codes e evidências da mutação.

## Bloqueios conhecidos

- Se o teste novo falhar sem mutação (ex.: unidade não mapeada, título
  inesperado), NÃO ajuste código de produção: reporte INCOMPLETO com a saída
  exata (isso indicaria premissa D4 falsa ⇒ escalonamento humano).
- Se helpers do teste modelo (~:2334) tiverem mudado de nome/assinatura,
  siga o estado atual do arquivo e registre a diferença no relatório.
