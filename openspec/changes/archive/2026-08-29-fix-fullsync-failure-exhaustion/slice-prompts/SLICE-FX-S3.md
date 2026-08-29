# FX-S3 — Caracterização das validações de payload (H2b)

## Handoff para implementador LLM com contexto zero

Leia integralmente:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. `docs/adr/ADR-0008-fullsync-failure-characterization-decision.md`
   (H2 confirmado; item 3 da correção recomendada);
3. o change atual: `proposal.md`, `design.md` (seção **D3**), spec delta,
   `tasks.md`;
4. `apps/ingestion/extractors/persistent_evolution_pdf.py`:
   `_resolve_pdf_url_from_object`, `_resolve_pdf_url_from_viewer`,
   `assert_pdf_response_signature`, `extract_pdf_text`,
   `EvolutionPdfFlow._resolve_pdf_url`;
5. `apps/ingestion/extractors/persistent_extraction_adapter.py`:
   `_parse_evolutions_json`, `_extract_json_from_container`,
   `_EVOLUTION_DATA_DIV_ID`, `_EVOLUTION_DATA_CONTAINER_RE`;
6. `apps/ingestion/run_lifecycle.py`: `classify_failure_reason` (taxonomia
   — não muda);
7. `automation/lab/playwright_experiments/fixtures/fullsync_synthetic_content.json`
   (as 6 validações identificadas na investigação) e
   `tests/unit/test_fullsync_failure_lab.py` (padrão de fakes
   duck-typed).

Estado atual: as validações existem e funcionam, mas **não têm suíte de
caracterização própria** contra o código real — a garantia de que
"conteúdo genuinamente inválido" é distinto de "lacuna de parsing"
(ex.: atributo `data` vazio resgatável pelo viewer frame) está implícita.
A ADR-0008 exige a revisão com evidência, sem relaxar a taxonomia.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Idêntico ao FX-S1 (plano/matriz, BASE_REF, baseline unit oficial, GREEN
mínimo, inspeções `rg`, gates completos, relatório com evidência) — com
uma adaptação explícita para slice de caracterização (abaixo). **Qualquer
item falho = INCOMPLETO.**

**Adaptação do RED (obrigatória):** slice de caracterização pode terminar
verde (sem bug). Em vez de "RED real", exige-se **prova de sensibilidade**:
após a suíte passar, mute temporariamente o código (ex.: remova o fallback
do viewer em `_resolve_pdf_url`, ou desative uma validação), rode a suíte,
comprove que o teste correspondente **falha**, reverta a mutação, rode a
suíte novamente (verde) e registre tudo (mutação, falha, revert, verde).
Sem essa prova, o slice está INCOMPLETO.

## Objetivo do slice

Suíte de caracterização/regressão permanente cobrindo as 6 validações de
payload do design D3 contra o código real, com o veredito documentado:
**ou** um gap comprovado por RED é corrigido estritamente no escopo dele,
**ou** o veredito "sem lacuna de parsing" fica registrado com a suíte como
prova. Nenhuma mudança de taxonomia.

## Escopo funcional

- **R1 — Resgate viewer (data vazio):** página fake com `<object
  type="application/pdf" data="">` e frame com URL `.pdf` (e um caso com
  query `file=`) → `_resolve_pdf_url` resolve via viewer → fluxo prossegue
  (não falha).
- **R2 — Ausência genuína:** sem object e sem viewer →
  `EvolutionPdfError` ("could not be located") →
  `classify_failure_reason` → `invalid_payload`.
- **R3 — Assinatura de resposta:** resposta com `content-type:
  text/html` onde PDF esperado → `assert_pdf_response_signature` →
  `EvolutionPdfError` → `invalid_payload`; corpo sem `%PDF-` → idem.
- **R4 — JSON/container:** `_parse_evolutions_json` com JSON inválido e
  com raiz não-lista → `InvalidJsonError` → `invalid_payload`;
  `_extract_json_from_container` sem container →
  `SnapshotContainerMissingError` → `invalid_payload`.
- **R5 — Sensibilidade comprovada:** mutação temporária (mínimo: fallback
  do viewer) derruba o teste correspondente; revert comprovado.
- **R6 — Veredito registrado:** no relatório, tabela validação → teste →
  resultado (verde = sem lacuna; vermelho corrigido = gap + fix mínimo).

## Arquivos esperados (limite 3, além de `tasks.md`)

1. `tests/unit/test_evolution_payload_validation_characterization.py`
   (novo — a suíte);
2. `apps/ingestion/extractors/persistent_evolution_pdf.py` (somente se um
   RED comprovado exigir correção mínima; senão intocado);
3. `apps/ingestion/extractors/persistent_extraction_adapter.py` (idem).

Proibido: taxonomia (`run_lifecycle.py`), workers, models/migrations,
laboratório `automation/` (as fixtures do lab são apenas leitura).

## TDD obrigatório

### Ordem (caracterização)

1. Escrever a suíte R1–R4 com fakes duck-typed (mesma técnica dos testes
   do lab; sem browser/rede).
2. Rodar: verde = comportamento correto pinado; vermelho = gap real →
   corrigir minimamente (o teste vira o RED do fix).
3. Prova de sensibilidade R5 (mutar → falha → reverter → verde).
4. REFACTOR local da suíte (fixtures/fakes DRY, sem duplicar builders).

### Regras

- Cada validação com teste próprio e nome explícito
  (`test_<validação>_maps_to_invalid_payload` etc.).
- Sentinelas sintéticas no conteúdo (`SYNTH-FX-S3`) para provar que
  mensagens/erros não ecoam conteúdo.
- Sem alterar assinaturas/mensagens existentes exceto no gap comprovado.

## Checks de inspeção obrigatórios

```bash
rg -n "SYNTH-FX-S3" tests/unit/test_evolution_payload_validation_characterization.py | wc -l
rg -n "invalid_payload" tests/unit/test_evolution_payload_validation_characterization.py | wc -l
rg -n "classify_failure_reason" tests/unit/test_evolution_payload_validation_characterization.py
git diff --stat HEAD   # após revert da mutação: sem resíduo de mutação
```

Interprete: sentinelas presentes em cada fixture de conteúdo;
classificação via `classify_failure_reason` real em cada caso; diff final
sem traço da mutação temporária.

## Gates de autoavaliação

1. Qual teste pinna o resgate viewer para `data` vazio (R1)?
2. Qual prova de sensibilidade foi feita e qual teste caiu com a mutação?
3. Houve gap comprovado? Qual e qual foi a correção mínima (ou por que
   "sem lacuna")?
4. O que garante que a taxonomia não mudou?
5. Por que cada arquivo é necessário?

## Critérios de sucesso binários

- [ ] R1–R6 cobertos; 6 validações cada uma com teste próprio.
- [ ] Sensibilidade comprovada (mutação → falha → revert → verde).
- [ ] Veredito registrado na tabela do relatório.
- [ ] Taxonomia intocada (rg sem mudança em `run_lifecycle.py`).
- [ ] Máximo 3 arquivos; extractores só se gap comprovado.
- [ ] Gates exit 0; unit final >= baseline.

### Condições automáticas de INCOMPLETO

- validação sem teste próprio;
- sensibilidade ausente (sem mutação/revert registrados);
- mutação não revertida (resíduo no diff);
- taxonomia/worker/model tocados;
- fix além do gap comprovado;
- arquivo extra; gate falho; relatório sem tabela de veredito; task
  prematura.

## Relatório obrigatório

`/tmp/sirhosp-slice-FX-S3-report.md` (padrão FX-S1) + tabela de veredito
R6 + evidência completa da prova de sensibilidade.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, docs/adr/ADR-0008-fullsync-failure-characterization-decision.md and the full fix-fullsync-failure-exhaustion change (proposal.md, design.md section D3, specs delta, tasks.md, slice-prompts/SLICE-FX-S3.md). Implement ONLY FX-S3. Follow the DeepSeek4-Flash protocol with the characterization adaptation: plan matrix, clean BASE_REF, official unit baseline, characterization suite R1-R6 against the real code with duck-typed fakes (viewer-frame rescue for empty data attribute, genuine absence, response signature, JSON/container validations, each mapping to invalid_payload via the real classifier, synthetic sentinels in content), sensitivity proof by temporary mutation (break the viewer fallback, show the test fails, revert, show green, register everything), narrow fix ONLY for a proven gap, mandatory rg inspections, all official gates with final unit exit 0 and passed >= baseline. Never touch taxonomy, workers, models or migrations; extractors only if a test-proven gap requires the minimal fix. Touch only the listed files. Create /tmp/sirhosp-slice-FX-S3-report.md with full evidence, verdict table and verifier handoff. Any missing/failing item is INCOMPLETE with no task update/commit. If complete, mark only 3.x, commit, push, reply REPORT_PATH=..., then STOP.
```
