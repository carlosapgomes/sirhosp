# MSA-S1 — Split da regra 5 do classificador com recência de movimento

## Handoff para implementador LLM com contexto zero

Leia integralmente, na ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md` (raiz do repositório);
2. `openspec/changes/disambiguate-mirror-stale-admission/proposal.md`,
   `design.md` e `tasks.md`;
3. `openspec/specs/patient-flow-findings/spec.md` (specs bases já promovidas
   pela RC17);
4. `apps/ingestion/patient_flow_findings.py` (arquivo a modificar);
5. `apps/census/models.py` — somente o model `PatientMovement`
   (`patient` FK, `sector`, `first_seen_at`, `last_seen_at`);
6. `tests/integration/test_censo_patient_flow_findings.py` (casa atual dos
   testes do classificador e da superfície `/censo`; fixtures sintéticas).

Pré-condição: change `recognize-patient-flow-findings` já arquivado e em
produção (RC17). Este slice não depende de nenhum change ativo.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Este slice será implementado por um modelo rápido com tendência a concluir
cedo demais. Siga literalmente. **Se qualquer item falhar, o slice está
INCOMPLETO**: não marque `tasks.md`, não faça commit/push e responda com
bloqueio + evidência.

1. Registre `BASE_REF=$(git rev-parse HEAD)` e árvore limpa
   (`git status --short` vazio) antes de editar.
2. Rode os baselines oficiais ANTES de editar:
   `./scripts/test-in-container.sh unit` (esperado: 3187 passed, exit 0) e
   `./scripts/test-in-container.sh integration` (esperado: 474 passed,
   exit 0). Cole exit code e resumo no relatório. Falha no baseline = pare
   e reporte BLOQUEADO.
3. Escreva a matriz `Requisito → arquivo(s) → teste(s)` no relatório antes
   de codar.
4. RED real primeiro: apenas o arquivo de testes novo/estendido; rode o
   subconjunto alvo e registre falhas pelo motivo esperado. Teste que passa
   antes da implementação não prova nada — corrija-o.
5. GREEN mínimo: implemente somente o necessário; sem refactor amplo, sem
   antecipar o MSA-S2.
6. Rode as inspeções `rg` obrigatórias (abaixo) e interprete cada resultado.
7. Rode o gate completo: `./scripts/test-in-container.sh quality-gate`,
   `./scripts/test-in-container.sh integration`,
   `openspec validate disambiguate-mirror-stale-admission --strict`,
   `./scripts/markdown-lint.sh`. Todos exit 0, zero failures/errors,
   passed >= baseline (integration deve crescer com os testes novos).
8. Relatório com evidência em `/tmp/sirhosp-slice-MSA-S1-report.md`
   (estrutura na seção "Relatório obrigatório"), incluindo
   `Handoff para verificador`. `Status: COMPLETE` somente com tudo provado.

## Objetivo do slice

Um paciente do censo com admissão interna ativa há 48 h ou mais, sem
evolução há 48 h e **com entrada em setor nos últimos 48 h** passa a receber
o novo achado `mirror_stale_admission` ("Suspeita de admissão órfã no
espelho", warning, revisão manual) em `/censo`, `/beds` e na página de
admissões — **sem alterar nenhuma superfície** (o novo rótulo flui pelo DTO
fechado já renderizado genericamente). Sem movimento recente (ou movimento
com timestamp futuro), o comportamento atual `suspected_legacy_residual`
permanece intacto. Regras 1–4 e prioridade D5 intocadas.

## Contexto técnico atual

- `apps/ingestion/patient_flow_findings.py`: serviço bulk read-only;
  `classify_patient_finding` (função pura, prioridade D5) e
  `build_patient_flow_findings` (4 queries bulk: DOBs, admissões, máximos de
  eventos, outcomes de stage). Regra 5 atual:

  ```python
  if hours >= 48:
      window_start = now - _EVENT_WINDOW
      if (
          active_admission_last_event_at is None
          or active_admission_last_event_at < window_start
      ):
          return _finding(CODE_SUSPECTED_LEGACY_RESIDUAL)
  ```

- `_FINDING_SPECS` mapeia código → (label, severity, requires_manual_review);
  `ALL_FINDING_CODES` fecha o conjunto.
- Superfícies (`/censo`, `/beds`, admissões) renderizam
  `finding.label`/`requires_manual_review` genericamente — não devem ser
  tocadas.
- `PatientMovement` (apps/census): ledger por paciente/setor com
  `first_seen_at` (entrada no setor). Já alimentado pelo processamento do
  censo; nenhum writer novo é necessário.
- Fixtures existentes do arquivo de testes NÃO criam `PatientMovement`; os
  testes atuais da regra 5 continuam verdes (movimento ausente ⇒ residual).

## Escopo funcional

- **R1** — Novo código fechado `mirror_stale_admission` em
  `_FINDING_SPECS`/`ALL_FINDING_CODES`: label "Suspeita de admissão órfã no
  espelho", `SEVERITY_WARNING`, `requires_manual_review=True`; constante
  `CODE_MIRROR_STALE_ADMISSION`.
- **R2** — Função pura ganha parâmetro
  `latest_movement_at: datetime | None = None`; split da regra 5: com as
  condições atuais satisfeitas (admissão ativa ≥ 48 h; sem evento em 48 h),
  `now - 48h <= latest_movement_at <= now` ⇒ `mirror_stale_admission`;
  ausente, anterior a 48 h ou futuro (dado inválido tratado como ausente) ⇒
  `suspected_legacy_residual`. Nova constante
  `_MOVEMENT_WINDOW = timedelta(hours=48)`.
- **R3** — `build_patient_flow_findings` ganha a quinta query bulk:
  `Max("first_seen_at")` por `patient_id` da coorte em `PatientMovement`,
  repassada ao classificador puro. Orçamento fixo 4→5; docstring do módulo
  atualizada; nenhuma query em loop; pacientes sem movimento têm
  `latest_movement_at=None`.
- **R4** — Regressões preservadas: regras 1–4 idênticas; sem movimento o
  resultado é exatamente o atual; suíte existente verde sem edições de
  teste (exceto adições).
- **R5** — Auto-aparição comprovada por teste de caracterização: paciente
  com admissão órfã + movimento novo exibe o novo label na página `/censo`
  (renderização desktop e mobile já cobertas pelo padrão de badge genérico;
  basta o label constar no HTML autenticado) sem nenhuma alteração em
  views/templates.

## Arquivos esperados e limite

Máximo de **2 arquivos**:

1. `apps/ingestion/patient_flow_findings.py`;
2. `tests/integration/test_censo_patient_flow_findings.py` (apenas adições).

Fora de escopo (proibido tocar): views/templates de qualquer app, models,
migrations, workers, `pipeline_health.py`, `process_ingestion_runs*.py`,
portal, URLs, dependências. Se um teste exigir outro arquivo, pare e peça
emenda ao planner.

## TDD obrigatório

### RED (todos devem falhar pelo motivo certo antes da implementação)

1. serviço: admissão ativa 72 h, sem eventos, `PatientMovement` com
   `first_seen_at` 1 h atrás ⇒ mapa contém o novo código com label/severity/
   review corretos (hoje retorna `suspected_legacy_residual` ⇒ falha);
2. `/censo`: mesma fixture renderiza "Suspeita de admissão órfã no espelho"
   no HTML autenticado (hoje renderiza o rótulo antigo ⇒ falha);
3. split: movimento 3 dias atrás ⇒ mantém `suspected_legacy_residual`;
4. split: `first_seen_at` 1 h no futuro ⇒ mantém
   `suspected_legacy_residual`;
5. orçamento: `build_patient_flow_findings` sobre coorte com movimentos usa
   no máximo 5 queries (CaptureQueriesContext; hoje a nova query não existe
   ⇒ o teste do teto 5 com movimento presente falha ao não encontrar a
   evidência nova — use asserção `<= 5`).

### GREEN

Implementar R1–R3 minimamente; R4/R5 provados pela suíte existente + teste
de caracterização.

### REFACTOR

Local apenas: extrair helper do predicado de janela de movimento se
melhorar leitura; sem framework novo, sem generalização especulativa (YAGNI).

## Checks de inspeção obrigatórios

```bash
rg -n "mirror_stale_admission|admissão órfã" \
  apps/ingestion/patient_flow_findings.py \
  tests/integration/test_censo_patient_flow_findings.py
rg -n "_MOVEMENT_WINDOW|latest_movement_at|first_seen_at" \
  apps/ingestion/patient_flow_findings.py
rg -n "PatientMovement" apps/ingestion/patient_flow_findings.py
rg -n "CensusSnapshot|views|template" apps/ingestion/patient_flow_findings.py
git diff --check && git diff --stat
```

Interprete: o novo código aparece exatamente no serviço e nos testes; a
query de movimento é bulk com `patient_id__in`; o serviço não importa
views/templates; nenhum outro arquivo mudou.

## Critérios binários de sucesso

- [ ] Baselines registrados (3187 unit / 474 integration, exit 0).
- [ ] RED reproduzido com os 5 itens falhando pelo motivo esperado.
- [ ] Novo código/label/severity/review corretos e fechados.
- [ ] Split determinístico (48 h; futuro ⇒ ausente).
- [ ] Quinta query bulk; orçamento fixo 5; sem N+1.
- [ ] Regras 1–4 e prioridade intactas (suíte existente verde, zero edits).
- [ ] `/censo` exibe o novo label sem mudança de superfície.
- [ ] quality-gate + integration + openspec strict + markdown-lint exit 0,
      passed >= baseline.
- [ ] Máximo 2 arquivos; relatório completo com handoff.

### Condições automáticas de INCOMPLETO

- baseline/RED/gate ausente ou sem evidência colada;
- suíte existente editada/removida ao invés de estendida;
- regra 1–4 ou prioridade alterada;
- movimento futuro aceito como recente;
- orçamento ultrapassado ou query no loop;
- superfície (view/template) alterada para exibir o rótulo;
- `tasks.md` marcado com pendência; arquivo extra; markdown lint silenciado;
  relatório sem snippets antes/depois ou sem handoff para verificador.

## Gates de autoavaliação

1. Qual par de testes prova o split nas duas direções (≤ 48 h vs > 48 h)?
2. Onde o teste prova que timestamp futuro é tratado como ausente?
3. Qual teste prova que o orçamento continua fixo com movimentos presentes?
4. Por que nenhuma superfície precisou mudar e qual teste comprova?
5. Qual regressão garante que `suspected_legacy_residual` sem movimento é
   byte-a-byte o comportamento anterior?

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-MSA-S1-report.md` com: status; BASE_REF e árvore;
matriz requisito→arquivo→teste; baselines com exit/resumo; RED (comandos,
testes falhando, motivo); GREEN; snippets antes/depois do serviço; inspeções
`rg` interpretadas; pytest baseline vs final (exit, passed, failed, errors);
gates completos; respostas aos gates de autoavaliação; riscos; e
`Handoff para verificador` com arquivos alterados, comandos exatos de rerun
e checklist R1–R5. Sem dados reais de pacientes.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md and openspec/changes/disambiguate-mirror-stale-admission/{proposal.md,design.md,tasks.md,slice-prompts/SLICE-MSA-S1.md} first. Implement ONLY MSA-S1 following the DeepSeek4-Flash protocol in the slice: BASE_REF and clean tree, official unit/integration baselines (3187/474), requirement matrix, real RED for the movement-window split (new mirror_stale_admission label with movement <=48h; legacy residual preserved without movement or with future timestamps), minimal GREEN in at most two files (apps/ingestion/patient_flow_findings.py + tests/integration/test_censo_patient_flow_findings.py additions only), local clean-code/DRY/YAGNI refactor, mandatory rg inspections, full quality gate, openspec strict and markdown lint. Surfaces (views/templates) must NOT change; the new label must appear on /censo through the existing generic rendering, proven by a characterization test. If any baseline/RED/gate fails, or the suite is edited instead of extended, report INCOMPLETE without marking tasks.md or committing. On success mark only 1.1-1.5 in tasks.md, create /tmp/sirhosp-slice-MSA-S1-report.md with RED/GREEN evidence, before/after snippets, baseline-vs-final pytest counts, gate outputs and verifier handoff, commit, push, reply REPORT_PATH=..., then STOP.
```
