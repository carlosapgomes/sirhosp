# CFL-S1 — Rótulos de achados sem jargão de TI

## Handoff para implementador LLM com contexto zero

Leia integralmente, na ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md` (raiz do repositório);
2. `openspec/changes/clarify-patient-flow-labels/proposal.md`,
   `design.md` e `tasks.md`;
3. delta `openspec/changes/clarify-patient-flow-labels/specs/patient-flow-findings/spec.md`;
4. `apps/ingestion/patient_flow_findings.py` — SOMENTE as 2 strings de
   label em `_FINDING_SPECS` mudam; NADA mais do arquivo;
5. `tests/integration/test_censo_patient_flow_findings.py` — o dicionário
   de rótulos esperados (entrada residual, linha ~72) e a constante
   `MIRROR_LABEL` (linha ~839);
6. `tests/integration/test_patient_flow_findings_surfaces.py` — a constante
   `LABEL_RESIDUAL` (linha ~47). O arquivo de observabilidade importa o
   label direto de `_FINDING_SPECS` e NÃO deve ser editado.

Pré-condição: working tree limpa sobre o commit base aprovado (tip do
`master` no momento do handoff). Change independente — não depende de
nenhum change ativo.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Idêntico aos slices MSA/TCF: BASE_REF + árvore limpa; baselines oficiais
ANTES de editar (unit e integration do commit base — registre os valores
REAIS, pois outros changes podem ter alterado as contagens; exit 0); matriz
requisito→arquivo→teste; RED real; GREEN mínimo; inspeções `rg`; gates
completos (`quality-gate`, `integration`,
`openspec validate clarify-patient-flow-labels --strict`,
`./scripts/markdown-lint.sh`) com passed >= baseline; relatório
evidencial. Qualquer item falho ⇒ INCOMPLETO sem marcar `tasks.md`/commit.

## Objetivo do slice

Dois rótulos visíveis de achados mudam para linguagem hospitalar (decisões
do operador, 2026-09-01 — "legado" e "espelho" são jargão de TI):

- `suspected_legacy_residual`: "Suspeita de paciente residual no legado" →
  **"Suspeita de paciente residual"**;
- `mirror_stale_admission`: "Suspeita de admissão órfã no espelho" →
  **"Suspeita de internação antiga em aberto ou alta não detectada"**
  (o "ou" cobre as duas causas-raiz sem afirmar nenhuma).

Ajuste estritamente apresentacional: códigos internos, severidades,
flags de revisão manual, regras e queries permanecem byte-a-byte
idênticos. Zero persistência envolvida (achados são computados
on-the-fly).

## Escopo funcional

- **R1** — `apps/ingestion/patient_flow_findings.py`: únicos textos
  alterados no arquivo são as 2 strings de label em `_FINDING_SPECS`
  (`CODE_SUSPECTED_LEGACY_RESIDUAL` e `CODE_MIRROR_STALE_ADMISSION`).
  Nenhuma outra linha do serviço muda.
- **R2** — `tests/integration/test_censo_patient_flow_findings.py`: o pino
  do rótulo residual atualiza para o novo texto e `MIRROR_LABEL` atualiza
  para o novo texto do mirror. Nenhuma outra edição.
- **R3** — `tests/integration/test_patient_flow_findings_surfaces.py`:
  `LABEL_RESIDUAL` atualiza para o novo texto. Nenhuma outra edição.
- **R4** — Verificação de vazamento: após o GREEN, `rg "residual no
  legado"` e `rg "órfã no espelho"` em `apps/ tests/ openspec/specs/
  docs/ deploy/` retornam ZERO ocorrências (archives de
  `openspec/changes/archive/` são imutáveis e não contam).

## Arquivos esperados e limite

Máximo de **3 arquivos** (exatamente os R1–R3). Qualquer outro arquivo no
diff ⇒ INCOMPLETO. Precisando de mais, pare e peça emenda ao planner.

## TDD obrigatório

### RED

1. Edite APENAS os 2 arquivos de teste (R2, R3) para o novo texto;
2. Rode o subconjunto:
   `pytest -q tests/integration/test_censo_patient_flow_findings.py
   tests/integration/test_patient_flow_findings_surfaces.py`;
3. Registre as falhas: asserções de label esperam o texto novo e falham
   contra a constante antiga (motivo: label divergente — confirme nas
   mensagens `assert ... == 'Suspeita de paciente residual'`).

### GREEN

Altere a única string em `_FINDING_SPECS` (R1). Subconjunto verde; rode a
suíte completa.

### REFACTOR

Nenhum — mudança de uma string com pinos de teste; qualquer refactor aqui é
desvio de escopo.

## Checks de inspeção obrigatórios

```bash
rg -n "Suspeita de paciente residual" apps/ingestion/patient_flow_findings.py \
  tests/integration/test_censo_patient_flow_findings.py \
  tests/integration/test_patient_flow_findings_surfaces.py
rg -n "internação antiga em aberto ou alta não detectada" \
  apps/ingestion/patient_flow_findings.py \
  tests/integration/test_censo_patient_flow_findings.py
rg -n "residual no legado|órfã no espelho" apps/ tests/ openspec/specs/ \
  docs/ deploy/ ; echo "exit=$? (1 = zero ocorrências)"
git diff --stat   # → exatamente 3 arquivos
git diff apps/ingestion/patient_flow_findings.py   # → apenas as 2 linhas de label
```

## Critérios binários de sucesso

- [ ] Baselines reais do commit base registrados (exit 0, resumos).
- [ ] RED reproduzido com falhas de divergência de label (evidência colada).
- [ ] Novos rótulos nas 5 ocorrências (3 residual + 2 mirror).
- [ ] Diff do serviço = 2 linhas (as strings); testes = só os pinos.
- [ ] Zero ocorrências dos textos antigos fora de archives (rg exit 1).
- [ ] quality-gate + integration + openspec strict + markdown-lint exit 0,
      passed >= baseline (contagens idênticas às do base: nenhum teste
      adicionado/removido, apenas textos de pino atualizados).
- [ ] Máximo 3 arquivos; relatório com handoff para verificador.

### Condições automáticas de INCOMPLETO

- qualquer linha do serviço alterada além das 2 strings de label;
- qualquer outro arquivo no diff (inclusive archives, specs já promovidas,
  docs, e o arquivo de observabilidade que importa de `_FINDING_SPECS`);
- contagem de testes alterada (testes não são adicionados/removidos, só
  pinos atualizados);
- baseline/RED/gate ausentes ou sem evidência; `tasks.md` marcado com
  pendência; markdown lint silenciado; relatório sem snippets/handoff.

## Gates de autoavaliação

1. Quais testes provam que os novos rótulos aparecem em TODAS as superfícies
   (censo, beds, admissões, aba patients) sem nenhuma mudança de superfície?
2. O que prova que o comportamento classificador é byte-a-byte idêntico
   (códigos/severidades/revisão)?
3. Onde está a evidência de que nenhum dado persistido é afetado?
   (estrutural: achados on-the-fly — cite o teste/spec que garante não
   persistência.)
4. Por que a contagem de testes NÃO muda neste slice?
5. Por que o arquivo de observabilidade não é editado e qual mecanismo o
   mantém correto após o rename?

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-CFL-S1-report.md` com: status; BASE_REF e árvore;
matriz requisito→arquivo→teste; baselines; RED (comandos, falhas, motivos);
GREEN; snippets antes/depois (as 3 ocorrências); inspeções `rg`
interpretadas; pytest baseline vs final; gates; respostas aos gates;
riscos; `Handoff para verificador` com arquivos, comandos de rerun e
checklist R1–R4. Sem dados reais de pacientes.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md and openspec/changes/clarify-patient-flow-labels/{proposal.md,design.md,tasks.md,slice-prompts/SLICE-CFL-S1.md} first. Implement ONLY CFL-S1 following the DeepSeek4-Flash protocol: BASE_REF and clean tree, real baselines from the base commit, requirement matrix, RED (test pins updated to the new labels "Suspeita de paciente residual" and "Suspeita de internação antiga em aberto ou alta não detectada" failing against the old constants), GREEN changing exactly two label strings in _FINDING_SPECS of apps/ingestion/patient_flow_findings.py, mandatory rg inspections proving zero occurrences of "residual no legado" and "órfã no espelho" outside archives and a diff of exactly three files (the observability test file imports labels from _FINDING_SPECS and must NOT be edited), full quality gate, openspec strict and markdown lint with passed >= baseline and unchanged test counts. Any extra file or line changed means INCOMPLETE without marking tasks.md or committing. On success mark only 1.1-1.5, create /tmp/sirhosp-slice-CFL-S1-report.md with RED/GREEN evidence, before/after snippets, baseline-vs-final counts, gate outputs and verifier handoff, commit, push, reply REPORT_PATH=..., then STOP.
```
