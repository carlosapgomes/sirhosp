# MSA-S2 — Situação corrente na aba patients de `/metrica-ingestao`

## Handoff para implementador LLM com contexto zero

Leia integralmente, na ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. `openspec/changes/disambiguate-mirror-stale-admission/proposal.md`,
   `design.md` e `tasks.md`;
3. `openspec/specs/ingestion-run-metrics-portal/spec.md` (base) e o delta
   `specs/ingestion-run-metrics-portal/spec.md` do change;
4. relatório COMPLETE de MSA-S1 (`/tmp/sirhosp-slice-MSA-S1-report.md`) e o
   commit aprovado (BASE_REF obrigatoriamente o commit do S1);
5. `apps/services_portal/views.py` — `_get_latest_batch_failure_stats`
   (fonte única da tabela "Pacientes com Falha Final") e os imports já
   existentes de `PatientFindingInput`/`build_patient_flow_findings`;
6. `apps/services_portal/templates/services_portal/ingestion_metrics.html`
   — bloco `{% elif active_tab == 'patients' %}` (tabela de pacientes com
   falha final) e o padrão de badge acessível usado nas outras superfícies
   (`apps/services_portal/templates/services_portal/censo.html`);
7. `tests/integration/test_patient_flow_findings_observability.py` (casa dos
   testes do portal de ingestão; fixtures sintéticas de batch/run/stage);
8. `apps/census/models.py` — `CensusSnapshot` (foto, `prontuario`,
   `setor`, `setor_codigo`) e `PatientMovement` (para fixtures do novo
   achado quando pertinente).

## Protocolo obrigatório para implementador DeepSeek4-Flash

Idêntico ao MSA-S1: BASE_REF + árvore limpa; baselines oficiais ANTES de
editar (`unit` 3187+ΔS1, `integration` 474+ΔS1 — registre os valores reais
do commit base); matriz requisito→arquivo→teste; RED real; GREEN mínimo;
inspeções `rg`; gate completo (`quality-gate`, `integration`,
`openspec validate disambiguate-mirror-stale-admission --strict`,
`./scripts/markdown-lint.sh`) com passed >= baseline; relatório evidencial.
Qualquer falha ⇒ INCOMPLETO sem marcar `tasks.md`/commit.

## Objetivo do slice

A tabela "Pacientes com Falha Final" da aba patients de `/metrica-ingestao`
ganha uma coluna "Situação" mostrando o rótulo do achado corrente do
paciente (qualquer um dos seis códigos do classificador, incluindo o novo
`mirror_stale_admission`) com o mesmo tratamento de badge acessível das
outras superfícies; paciente sem achado corrente (incluindo quem saiu do
censo) exibe célula vazia, sem placeholder. Classificação bulk, sem N+1,
sem dado sensível novo, auth intacta.

## Contexto técnico atual

- `_get_latest_batch_failure_stats` (apps/services_portal/views.py): lê
  `FinalRunFailure` do último lote terminado e monta
  `failure_patients: list[dict]` com `patient_record`, `intent`,
  `failed_at`, `attempts_exhausted`; retorna também os cards derivados do
  S5. É a única fonte do bloco patients do template.
- O template renderiza a tabela com 4 colunas fixas; o padrão de badge
  acessível a copiar (com `role="status"`, `title` e
  `visually-hidden` para revisão manual) está em `censo.html`
  (badge de finding) e em `bed_status.html`.
- `build_patient_flow_findings(inputs, now=...)` já importado em
  `views.py`; inputs exigem `prontuario`, `patient_id` (pk de `Patient` por
  `patient_source_key`), `sector`, `sector_codigo` — provenientes da foto
  mais recente do censo (`CensusSnapshot` por `captured_at` máximo).
- Paciente fora do censo atual não entra nos inputs ⇒ sem achado (projeção
  corrente) — comportamento desejado, não um erro.

## Escopo funcional

- **R1** — `_get_latest_batch_failure_stats` anexa `"finding"` a cada linha
  de `failure_patients`: resolve os `patient_record` distintos contra a
  foto mais recente do censo (uma query da foto + uma query das rows dos
  registros), resolve pks de `Patient` (uma query) e chama
  `build_patient_flow_findings` uma única vez (orçamento interno fixo de 5
  queries). Nenhuma regra duplicada; nenhum cálculo local de achado.
- **R2** — Template: coluna "Situação" com badge idêntico às outras
  superfícies (`role="status"`, `title`, tratamento warning quando
  `requires_manual_review`, texto visível = `finding.label`); sem achado ⇒
  célula vazia (nenhum "—", nenhum placeholder).
- **R3** — Defaults preservados: sem lote/falhas, página renderiza como hoje
  (`_empty_batch_stats` não precisa de finding — lista já vazia); anonymous
  continua redirecionado; aba runs/dashboard intocadas.
- **R4** — Orçamento bounded: render da aba patients com 1 vs 20 pacientes
  com falha delta de queries fixo e pequeno (≤ 10 no CaptureQueriesContext);
  nenhuma query no loop do template.
- **R5** — Privacidade: o bloco novo expõe apenas o label constante;
  sentinelas sintéticas (record/nome/URL/HTML) continuam ausentes do HTML;
  nenhum campo novo além de `finding` nos dicts.

## Arquivos esperados e limite

Máximo de **3 arquivos**:

1. `apps/services_portal/views.py`;
2. `apps/services_portal/templates/services_portal/ingestion_metrics.html`;
3. `tests/integration/test_patient_flow_findings_observability.py`
   (apenas adições).

Fora de escopo (proibido): classificador
(`apps/ingestion/patient_flow_findings.py`), censo/beds/admissões, health,
workers, models/migrations, URLs, `censo.html`, dependências. Precisando de
outro arquivo, pare e peça emenda.

## TDD obrigatório

### RED (falhando pelo motivo certo antes da implementação)

1. aba patients: lote terminado com `FinalRunFailure` de paciente que tem
   achado corrente (fixture: foto de censo + RN 2 dias sem admissão ⇒
   "RN aguardando registro"; e/ou admissão órfã + `PatientMovement` nova ⇒
   "Suspeita de admissão órfã no espelho") ⇒ label visível no HTML
   autenticado (hoje: ausente ⇒ falha);
2. paciente com falha mas fora do censo atual ⇒ sem placeholder/erro, célula
   vazia, HTTP 200;
3. revisão manual: achado `requires_manual_review` (ex.: companion em 3A)
   renderiza o tratamento warning e o texto acessível de revisão;
4. orçamento: 1 vs 20 pacientes com falha delta ≤ 10 queries;
5. anonymous: redirect `/login/` preservado na página com `?tab=patients`.

### GREEN

R1–R2 minimamente; R3–R5 pela estrutura existente + testes.

### REFACTOR

Local: helper privado para montar os inputs da coorte de falha se reduzir
duplicação; reutilizar sempre o serviço do classificador; sem duplicar
regra, label ou janela (DRY/YAGNI).

## Checks de inspeção obrigatórios

```bash
rg -n "build_patient_flow_findings|PatientFindingInput" \
  apps/services_portal/views.py
rg -n "Situação|patient.finding|requires_manual_review" \
  apps/services_portal/templates/services_portal/ingestion_metrics.html
rg -n "mirror_stale_admission|_MOVEMENT_WINDOW|classify_patient_finding" \
  apps/services_portal/views.py \
  apps/services_portal/templates/services_portal/ingestion_metrics.html
rg -n "CensusSnapshot|FinalRunFailure" apps/services_portal/views.py
git diff --check && git diff --stat
```

Interprete: a view chama apenas o serviço (sem regra local de achado — o
terceiro rg deve retornar vazio); o template tem exatamente a coluna/loop
novos com o padrão de badge; nenhuma outra superfície ou arquivo mudou.

## Critérios binários de sucesso

- [ ] Baselines do commit do S1 registrados (exit 0, resumos colados).
- [ ] RED com os 5 itens falhando pelo motivo esperado.
- [ ] Coluna "Situação" com label corrente e badge acessível idêntico.
- [ ] Sem achado ⇒ célula vazia; sem placeholder; sem erro.
- [ ] Uma chamada bulk do classificador por render; delta ≤ 10 queries.
- [ ] Classificador intocado (rg vazio para regras no portal).
- [ ] Auth/defaults/aba runs intactos; sem PHI novo.
- [ ] quality-gate + integration + openspec strict + markdown-lint exit 0,
      passed >= baseline.
- [ ] Máximo 3 arquivos; relatório completo com handoff para verificador.

### Condições automáticas de INCOMPLETO

- classificador ou qualquer superfície fora do escopo alterada;
- regra/label/janela duplicados no portal em vez de reutilizar o serviço;
- placeholder renderizado para paciente sem achado;
- N+1 por linha (query no loop) ou orçamento estourado;
- auth relaxada; aba runs/dashboard regredida;
- baseline/RED/gate ausentes ou sem evidência; suíte editada em vez de
  estendida; `tasks.md` marcado com pendência; arquivo extra; markdown lint
  silenciado; relatório sem snippets/handoff.

## Gates de autoavaliação

1. Quantas queries o render da aba patients adiciona e qual teste prova o
   teto?
2. Por que o paciente fora do censo atual fica sem rótulo e qual teste
   imobiliza esse comportamento?
3. Onde se prova que o portal não duplicou nenhuma regra do classificador?
4. Qual fixture gera o novo achado `mirror_stale_admission` no teste da
   coluna e por que ela passa pelo serviço sem alterá-lo?
5. Como o teste de privacidade prova que nada além do label constante foi
   exposto?

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-MSA-S2-report.md` com: status; BASE_REF (= commit
S1 aprovado) e árvore; matriz requisito→arquivo→teste; baselines; RED
(comandos, falhas, motivos); GREEN; snippets antes/depois de view e
template; inspeções `rg` interpretadas; pytest baseline vs final; gates;
respostas aos gates; riscos; `Handoff para verificador` com arquivos,
comandos de rerun e checklist R1–R5. Sem dados reais.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md and openspec/changes/disambiguate-mirror-stale-admission/{proposal.md,design.md,tasks.md,slice-prompts/SLICE-MSA-S2.md} first, plus the approved MSA-S1 commit as BASE_REF. Implement ONLY MSA-S2 following the DeepSeek4-Flash protocol: baselines before editing, requirement matrix, real RED for the patients-tab situation column (current finding label with the shared accessible badge; empty cell and no placeholder when the patient has no current finding; anonymous redirect preserved; bounded query delta), minimal GREEN in at most three files (apps/services_portal/views.py, apps/services_portal/templates/services_portal/ingestion_metrics.html, additions to tests/integration/test_patient_flow_findings_observability.py), local refactor reusing the classifier service with zero duplicated rules, mandatory rg inspections, full quality gate, openspec strict and markdown lint. The classifier and all other surfaces must remain untouched. If anything fails, report INCOMPLETE without marking tasks.md or committing. On success mark only 2.1-2.5, create /tmp/sirhosp-slice-MSA-S2-report.md with RED/GREEN evidence, before/after snippets, baseline-vs-final counts, gate outputs and verifier handoff, commit, push, reply REPORT_PATH=..., then STOP.
```
