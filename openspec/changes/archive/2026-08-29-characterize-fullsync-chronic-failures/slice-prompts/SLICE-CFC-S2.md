# CFC-S2 — Harness de laboratório com fixtures sintéticas

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. o change atual e `SLICE-CFC-S1.md` + relatório COMPLETE do S1;
3. delta `fullsync-failure-characterization/spec.md` (cenários de
   laboratório);
4. `automation/lab/` (convenções do modo laboratório) e um experimento
   existente como estilo;
5. `apps/ingestion/extractors/persistent_evolution_pdf.py` (deadlines,
   timeouts tipados) e `persistent_extraction_adapter.py` (classificação de
   falhas) apenas nos pontos exercitados;
6. `apps/ingestion/run_lifecycle.py` (mapeamento reason).

Estado: as hipóteses H1 (timeout por volume/deadline) e H2
(invalid_payload por conteúdo) estão formuladas no design, mas não são
reproduzíveis de forma controlada. Este slice entrega o harness; não altera
código operacional.

## Protocolo obrigatório

1. BASE_REF limpo; matriz requisito→arquivo→teste.
2. Confirmar S1 COMPLETE; baseline unit oficial.
3. RED para cada experimento, artefato de veredito e garantia
   sintética/isolamento.
4. GREEN mínimo: fixtures + runner + vereditos.
5. REFACTOR local; código laboratorial nunca importado por `apps/`.
6. Inspeções `rg` + gates; final unit exit 0 e passed >= baseline.
7. Relatório; marcar apenas 2.1–2.5; commit/push; STOP.

## Objetivo vertical

Harness `automation/lab/playwright_experiments/fullsync_failure_lab.py`
que roda as hipóteses contra o código real de extração/classificação com
fixtures 100% sintéticas e emite vereditos confirmáveis.

## Requisitos funcionais

### R1 — H1: timeout por volume/deadline

Fixture sintética de página de evoluções com lista longa (nº de itens
parametrizável) e deadline curto configurável, exercitando o fluxo real de
leitura/paginação. Resultado esperado: reason `timeout` com duração medida
registrada. Parâmetros registrados no veredito.

### R2 — H2: invalid_payload por conteúdo

Fixtures sintéticas de conteúdo violando validações conhecidas (ex.:
atributo vazio, estrutura inesperada), exercitando o classificador real.
Cada fixture registra qual validação disparou o mapeamento para
`invalid_payload`.

### R3 — Artefatos de veredito

Cada experimento emite JSON sintético com: `hypothesis`, `fixture`,
`params`, `measured_duration_seconds` (quando aplicável), `reason`,
`verdict` (`confirmed`/`refuted`/`inconclusive`), `notes` sanitizadas.
Runner consolida `verdicts.json`.

### R4 — Isolamento laboratorial

Fixtures sintéticas versionadas no repositório; harness nunca importado
por código operacional; nenhum acesso a produção, credenciais, dados
reais, HTML/PDF real; sem rede externa além do Playwright local headless;
testes sem browser real onde a validação for pura (classificação),
marcação explícita (`@pytest.mark`) para os que exigirem browser.

## Arquivos esperados e limite

Máximo de **4 arquivos rastreados**, além de `tasks.md`:

1. novo `automation/lab/playwright_experiments/fullsync_failure_lab.py`;
2. novas fixtures sintéticas (máx. 2 arquivos, ex.: JSON/HTML sintético);
3. novo `tests/unit/test_fullsync_failure_lab.py`.

Não editar `apps/` (adapter/pdf/run_lifecycle), models, migrations, workers
ou o command do S1.

## TDD obrigatório

### RED mínimo

1. H1 com deadline curto produz `timeout` e duração medida registrada;
2. H1 com deadline folgado não produz `timeout` (controle);
3. H2 cada fixture inválida mapeia para `invalid_payload` via classificador
   real, com validação disparada identificada;
4. H2 fixture válida (controle) não mapeia para `invalid_payload`;
5. `verdicts.json` com schema completo por experimento;
6. harness não importa nada de `apps/` além dos pontos reais exercitados
   (adapter/classificador) — e nada de `apps/` importa o harness;
7. fixtures contêm somente dados sintéticos (assert de sentinelas
   sintéticas; nenhuma string de produção).

### GREEN / REFACTOR

Runner puro de experimentos; duração medida com unidade explícita; veredito
determinístico dados os parâmetros; sem framework genérico além do
necessário (YAGNI).

## Checks de inspeção obrigatórios

```bash
rg -n "from apps\.|import apps\." automation/lab/playwright_experiments/fullsync_failure_lab.py
rg -rn "fullsync_failure_lab" apps/ tests/ --glob '!tests/unit/test_fullsync_failure_lab.py'
rg -n "timeout|invalid_payload|verdict|confirmed|refuted|inconclusive" \
  automation/lab/playwright_experiments/fullsync_failure_lab.py \
  tests/unit/test_fullsync_failure_lab.py
rg -n "SYNTH|sintetic|synthetic" automation/lab/playwright_experiments/
```

Interpretar: imports de `apps/` restritos ao código real exercitado; zero
import reverso de `apps/` para o laboratório; vereditos e reasons
presentes; sentinelas sintéticas visíveis nas fixtures.

## Gates oficiais obrigatórios

Os mesmos do S1 (check, unit, integration, lint, typecheck, quality-gate,
openspec strict, markdown lint).

## Critérios binários de sucesso

- [ ] R1–R4 cobertos RED/GREEN com controles positivos/negativos.
- [ ] H1 reproduz `timeout` com duração medida; H2 identifica validação.
- [ ] `verdicts.json` completo por experimento.
- [ ] Isolamento laboratorial provado (imports, fixtures sintéticas).
- [ ] Máximo quatro arquivos; `apps/` intocado.
- [ ] Gates exit 0; unit final >= baseline.

### Condições automáticas de INCOMPLETO

- S1/baseline/RED ausente ou falho;
- experimento sem controle (positivo/negativo);
- harness importa ou é importado por código operacional indevidamente;
- fixture com dado real/PHI/HTML/PDF real;
- `apps/` alterado sem bloqueio;
- arquivo extra/gate falho/relatório ausente/task prematura.

## Gates de autoavaliação

1. Qual teste prova que H1 é o deadline (e não outra causa)?
2. Qual controle negativo protege H2 de falso positivo?
3. Como se prova que fixtures são sintéticas?
4. Onde o veredito é decidido e por que é determinístico?
5. Por que cada arquivo é necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CFC-S2-report.md` (padrão do S1) com `Handoff
para verificador` R1–R4.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full
characterize-fullsync-chronic-failures change, SLICE-CFC-S2.md and the
COMPLETE S1 report. Implement ONLY S2. Follow the DeepSeek4-Flash protocol:
clean BASE_REF, official unit baseline, real RED with positive/negative
controls for every experiment, minimal GREEN, local refactor, mandatory rg
and all official gates, final unit exit 0 with passed >= baseline. Deliver
the synthetic lab harness reproducing timeout and invalid_payload against
real extraction/classification code; never touch apps/ operational code,
never use real data, never let operational code import the lab. Touch only
the listed files. Create /tmp/sirhosp-slice-CFC-S2-report.md with evidence
and verifier handoff. Any missing/failing item is INCOMPLETE with no task
update/commit. If complete, mark only S2, commit, push, reply
REPORT_PATH=..., then STOP.
```
