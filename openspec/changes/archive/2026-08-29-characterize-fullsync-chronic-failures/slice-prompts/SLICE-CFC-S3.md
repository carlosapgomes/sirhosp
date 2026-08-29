# CFC-S3 — Relatório, ADR de decisão e runbook operacional

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. o change atual, `SLICE-CFC-S1.md`, `SLICE-CFC-S2.md` e relatórios
   COMPLETE S1–S2;
3. delta `fullsync-failure-characterization/spec.md` (requisito de
   decisão);
4. skill `adr-generator` (`.pi/skills/adr-generator/SKILL.md`) e as duas
   ADRs mais recentes como padrão;
5. saída do command S1 e `verdicts.json` do S2 (contratos de entrada);
6. `deploy/README.md` §6.1 como estilo de runbook operacional.

Estado: existe a caracterização (S1) e a reprodução (S2), mas não há
consolidação em artefato de decisão nem procedimento operacional
documentado. Este slice não executa nada em produção.

## Protocolo obrigatório

1. BASE_REF limpo; matriz requisito→arquivo→teste.
2. Confirmar S1–S2 COMPLETE; baseline unit oficial.
3. RED para gerador de relatório e validador de ADR.
4. GREEN mínimo; REFACTOR local.
5. Inspeções `rg` + gates (inclui markdown lint); unit final >= baseline.
6. Relatório; marcar apenas 3.1–3.6; commit/push; STOP.

## Objetivo vertical

Gerador de relatório de caracterização (a partir da saída do command S1),
template/validador de ADR de decisão (vereditos + recomendação) e runbook
operacional em `deploy/README.md`.

## Requisitos funcionais

### R1 — Gerador de relatório

Lê a saída do command S1 (stdout estruturado) e produz relatório Markdown
com seções fixas: coorte, reasons, timing por estágio, histograma horário,
contraste. Somente agregados; falha fechado se a entrada contiver
sentinela de identidade (scanner reutilizado do padrão S5/S1).

### R2 — ADR de decisão

Template ADR (skill adr-generator) com campos obrigatórios: contexto
(agregados), hipóteses com veredito (`confirmed`/`refuted`/`inconclusive`)
e evidência associada (seção do relatório + `verdicts.json`), causa(s)
comprovada(s), correção recomendada (change futuro) OU próximo experimento
quando nada for confirmado, e alternativas rejeitadas. Validador exige:
nenhum identificador/conteúdo clínico; todo veredito com evidência;
recomendação presente.

### R3 — Runbook operacional

Seção própria em `deploy/README.md`: como rodar a caracterização em
produção (one-shot read-only, flags, interpretação, exemplo systemd
opcional), como rodar o laboratório (pré-requisitos, comandos, artefatos),
e nota explícita de que este change não tem qualquer mutação (`--apply`
não existe aqui).

### R4 — Privacidade transversal

Relatório, ADR e runbook contêm somente agregados; nenhum dado
sensível; markdown lint sem erros e sem inibições.

## Arquivos esperados e limite

Máximo de **4 arquivos rastreados**, além de `tasks.md`:

1. novo `apps/ingestion/management/commands/generate_fullsync_failure_report.py`
   (gerador fino) OU script puro em `scripts/` — decidir pelo design e
   manter testável;
2. novo `docs/adr/ADR-00XX-fullsync-failure-characterization-decision.md`
   (template preenchível, numeração via skill);
3. `deploy/README.md` (seção nova);
4. novos testes unitários do gerador/validador.

Não editar S1/S2, models, migrations, workers ou health check.

## TDD obrigatório

### RED mínimo

1. gerador produz relatório com as cinco seções a partir de stdout de
   exemplo do S1;
2. gerador falha fechado com sentinela de identidade na entrada;
3. validador de ADR aprova template preenchido corretamente;
4. validador rejeita: veredito sem evidência, recomendação ausente,
   identificador presente;
5. runbook menciona comando/flags/artefatos e a ausência de mutação.

### GREEN / REFACTOR

Parsing puro, sem I/O de rede; templates como constantes; validador com
mensagens de erro sanitizadas.

## Checks de inspeção obrigatórios

```bash
rg -n "section|cohort|reasons|stage|hourly|contrast" <gerador> <testes>
rg -n "confirmed|refuted|inconclusive|evidence|recommendation" docs/adr/ADR-00XX-*.md
rg -n "characterize_fullsync_failures|fullsync_failure_lab|--apply|read.only" deploy/README.md
rg -n "markdownlint-disable" docs/ deploy/ ; echo "deve retornar vazio"
```

## Gates oficiais obrigatórios

Os mesmos do S1 + markdown lint obrigatório (arquivos `.md` novos).

## Critérios binários de sucesso

- [ ] R1–R4 cobertos RED/GREEN.
- [ ] Relatório com cinco seções a partir da saída real do S1.
- [ ] ADR validado por regras objetivas (veredito+evidência+recomendação).
- [ ] Runbook completo com nota de ausência de mutação.
- [ ] Máximo quatro arquivos; S1/S2 intocados.
- [ ] Gates exit 0; unit final >= baseline; markdown lint limpo.

### Condições automáticas de INCOMPLETO

- S1–S2/baseline/RED ausente ou falho;
- gerador aceita entrada com identidade;
- ADR sem veredito com evidência ou sem recomendação;
- qualquer PHI/identificador em relatório/ADR/runbook;
- S1/S2 alterado; arquivo extra; gate falho; relatório ausente; task
  prematura.

## Gates de autoavaliação

1. Qual teste prova que o gerador rejeita identidade na entrada?
2. O que o validador exige para `confirmed` versus `inconclusive`?
3. Por que o runbook deixa explícito que não há mutação?
4. Como o relatório liga cada veredito à evidência?
5. Por que cada arquivo é necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CFC-S3-report.md` (padrão dos anteriores) com
`Handoff para verificador` R1–R4.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full
characterize-fullsync-chronic-failures change, SLICE-CFC-S3.md and the
COMPLETE S1-S2 reports. Implement ONLY S3. Follow the DeepSeek4-Flash
protocol: clean BASE_REF, official unit baseline, real RED for the report
generator and ADR validator contracts, minimal GREEN, local refactor,
mandatory rg and all official gates plus markdown lint, final unit exit 0
with passed >= baseline. Deliver the characterization report generator, the
decision ADR template/validator and the operational runbook; fail closed on
identity sentinels; never touch S1/S2 code. Touch only the listed files.
Create /tmp/sirhosp-slice-CFC-S3-report.md with evidence and verifier
handoff. Any missing/failing item is INCOMPLETE with no task update/commit.
If complete, mark only S3, commit, push, reply REPORT_PATH=..., then STOP.
```
