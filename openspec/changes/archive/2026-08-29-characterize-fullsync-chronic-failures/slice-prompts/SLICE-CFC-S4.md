# CFC-S4 — Execução operacional e verificação final

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. o change atual, todos os slice prompts CFC e relatórios COMPLETE S1–S3;
3. o runbook criado no S3 (`deploy/README.md`, seção de caracterização);
4. relatórios RPAP-S5/S6/S7 como padrão de verificação final.

Estado: ferramental pronto (S1 caracterização, S2 laboratório, S3
relatório/ADR). Este slice executa a caracterização em produção
(read-only), roda o laboratório, consolida a ADR e verifica o change — sem
implementar qualquer correção.

## Protocolo obrigatório

1. BASE_REF limpo; confirmar S1–S3 COMPLETE; baseline unit oficial.
2. Executar a caracterização em produção conforme runbook (one-shot
   read-only, janela 7d default); registrar a saída agregada.
3. Executar os experimentos de laboratório (H1/H2); registrar
   `verdicts.json`.
4. Consolidar relatório (gerador S3) e preencher a ADR com vereditos e
   recomendação; commit da ADR preenchida com somente agregados.
5. Revisar diff total do change (PHI, identificadores, dados reais,
   migrations, dependências).
6. Todos os gates + `openspec validate --strict` + markdown lint.
7. Relatório final; marcar 4.1–4.5; aguardar verificação de terceiro LLM
   antes de qualquer arquivamento (nunca arquivar sem autorização do
   operador).

## Objetivo vertical

Evidência coletada, causa decidida (ou hipóteses refutadas com próximo
experimento definido) e change pronto para verificação — abrindo a
proposta do change de correção quando houver causa comprovada.

## Requisitos funcionais

### R1 — Execução read-only em produção

Caracterização executada com sucesso na janela 7d; contagens de models
antes/depois idênticas (verificação pós-execução por agregados); saída
registrada sem identidade.

### R2 — Vereditos de laboratório registrados

`verdicts.json` com H1/H2 (e controles) executados; durações e reasons
presentes; inconclusivo registrado como tal quando aplicável.

### R3 — ADR preenchida com evidência

Cada hipótese com veredito e evidência vinculada; recomendação de correção
(ou próximo experimento); zero identidade/conteúdo clínico.

### R4 — Change de correção aberto quando causa comprovada

Se alguma hipótese for `confirmed`: criar a proposta OpenSpec do change de
correção (somente proposal/design/specs/tasks, sem implementar), com a ADR
como rastreabilidade.

### R5 — Verificação final

Diff do change limpo (sem PHI/identificadores/dados reais/migrations/
dependências não autorizadas); gates exit 0; openspec strict; markdown
lint; relatório final em `/tmp/sirhosp-slice-CFC-S4-report.md`.

## Arquivos esperados e limite

Máximo de **3 arquivos rastreados**, além de `tasks.md`:

1. ADR preenchida (`docs/adr/ADR-00XX-...md` — arquivo criado no S3);
2. artefato de vereditos consolidados do laboratório (se precisar ser
   versionado; JSON sintético);
3. proposal do change de correção (se R4 aplicar — dentro de
   `openspec/changes/<novo-change>/`, gitignored, sem commit).

Nenhum código operacional alterado.

## TDD obrigatório

Sem TDD novo (slice operacional). Prova por evidência registrada: saídas
de comandos, agregados antes/depois, `verdicts.json`, ADR validada pelo
validador do S3 (deve aprovar).

## Checks de inspeção obrigatórios

```bash
# na estação de trabalho, sobre o diff do change:
git diff --name-only <BASE_REF>..HEAD
rg -n "PRIV-|prontuario [0-9]|patient_record=" docs/adr/ADR-00XX-*.md ; echo "vazio"
./scripts/markdown-lint.sh
```

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate characterize-fullsync-chronic-failures --strict
./scripts/markdown-lint.sh
```

## Critérios binários de sucesso

- [ ] Caracterização de produção executada read-only e registrada.
- [ ] Laboratório executado com vereditos (ou inconclusivo documentado).
- [ ] ADR preenchida, validada e sem identidade.
- [ ] Change de correção proposto quando houver causa comprovada.
- [ ] Diff limpo; gates exit 0; relatório final criado.
- [ ] Nenhum arquivamento sem verificação de terceiro LLM + autorização do
      operador.

### Condições automáticas de INCOMPLETO

- S1–S3 não COMPLETE;
- caracterização muta produção (contagens divergem);
- veredito sem evidência ou recomendação ausente na ADR;
- identificador/PHI em qualquer artefato;
- correção implementada neste change (fora de escopo);
- gate falho; relatório ausente; task prematura; arquivamento sem
  autorização.

## Gates de autoavaliação

1. Como foi provado que a execução em produção não mutou nada?
2. Qual veredito cada hipótese recebeu e com qual evidência?
3. O que a ADR recomenda e qual change ela abre?
4. O que ficou inconclusivo e qual é o próximo experimento?
5. Por que nenhuma correção foi implementada aqui?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CFC-S4-report.md` com Status, evidências (somente
agregados), vereditos, recomendação, gates, riscos e `Handoff para
verificador` R1–R5.

## Prompt pronto para o implementador/operador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full
characterize-fullsync-chronic-failures change, all CFC slice prompts and
COMPLETE S1-S3 reports. Execute ONLY S4 per its runbook: run the read-only
production characterization (7d window), run the lab experiments, fill the
decision ADR with verdicts and evidence, review the full diff for
PHI/identity/migrations, run every official gate plus openspec strict and
markdown lint. Never implement the fix in this change, never mutate
production, never archive without operator authorization. Create
/tmp/sirhosp-slice-CFC-S4-report.md with evidence and verifier handoff. If
a hypothesis is confirmed, open (proposal only) the corrective change
referencing the ADR. Any missing/failing item is INCOMPLETE. If complete,
mark only S4, commit, push, reply REPORT_PATH=..., then STOP.
```
