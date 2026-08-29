# FX-S4 — Regressão laboratório, nota operacional e verificação final

## Handoff para implementador LLM com contexto zero

Leia integralmente:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. o change completo `fix-fullsync-failure-exhaustion`
   (proposal/design/specs/tasks) e os slice prompts FX-S1..S3;
3. relatórios COMPLETE de FX-S1..S3 em
   `/tmp/sirhosp-slice-FX-S{1,2,3}-report.md`;
4. `automation/lab/playwright_experiments/fullsync_failure_lab.py` e
   `deploy/README.md` (§6.1–§6.2 como estilo de runbook operacional);
5. `docs/adr/ADR-0008-fullsync-failure-characterization-decision.md`.

Estado atual: as três frentes da correção estão implementadas e
verificadas (fail-fast determinístico, orçamento por volume com teto,
caracterização das validações). Este slice é o fechamento do change:
regressão do laboratório CFC contra o código corrigido, nota operacional
no runbook e verificação final — **sem novo código de produção**.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Idêntico ao FX-S1 (BASE_REF, baseline unit oficial, inspeções, gates
completos com unit final `passed >= baseline`, relatório com evidência).
Slice operacional: sem TDD novo; a prova é a evidência registrada.
**Qualquer item falho = INCOMPLETO.**

## Objetivo do slice

1. Laboratório CFC re-executado com o código corrigido, vereditos H1/H2
   inalterados nos parâmetros experimentais;
2. `deploy/README.md` com a nota operacional da correção;
3. diff total do change revisado (PHI/identificadores/migrations/
   dependências) e todos os gates finais;
4. relatório final do change para verificação de terceiro LLM.

## Escopo funcional

- **R1 — Regressão laboratório:** executar
  `fullsync_failure_lab.py --output /tmp/fx-verdicts.json` no ambiente
  containerizado de teste. Esperado: H1 (deadline curto experimental)
  `confirmed` com reason `timeout` — o bounded continua; controles
  (deadline folgado) `confirmed` sem falha; H2 inválidas `confirmed`
  `invalid_payload`. **Vereditos idênticos aos pré-correção** (a correção
  não altera o comportamento nos parâmetros experimentais do lab). Se
  algum veredito mudar, parar e reportar (regressão de contrato).
- **R2 — Nota operacional (`deploy/README.md`, nova §6.3 "Correção do
  esgotamento de tentativas (FX)"):** o que mudou operacionalmente
  (fail-fast de `invalid_payload` sem requeue; orçamento por janela
  base 120s + 2s/dia, teto 600s, no worker persistente) e como observar
  pelos agregados existentes: health check (`full_sync_failure_reasons`,
  `failure_percent` deve cair com menos queima), caracterização
  (`attempts_median/max` da coorte deve cair pós-rollout;
  `FinalRunFailure.attempts_exhausted=1` nos fail-fast), stage metrics
  (median/p90 de `evolution_extraction` com janelas longas). Sem comando
  novo, sem contrato novo, sem flag `--apply`.
- **R3 — Revisão de diff total do change:** ausência de PHI/identidades/
  dados reais/migrations/dependências; sentinelas só em testes que
  asseveram ausência; nenhum dado sensível.
- **R4 — Gates finais:** check, unit, integration, lint, typecheck,
  quality-gate, `openspec validate fix-fullsync-failure-exhaustion
  --strict`, `./scripts/markdown-lint.sh` — todos exit 0.

## Arquivos esperados (limite 2, além de `tasks.md`)

1. `deploy/README.md` (seção §6.3);
2. artefato de vereditos do laboratório versionado **não** — o JSON fica
   em `/tmp` (efêmero); nenhum arquivo de dados novo no repo.

Nenhum código de produção alterado neste slice.

## Execução R1 (rerun do laboratório)

```bash
docker compose -f compose.yml -f compose.test.yml -p sirhosp-test up -d db
docker compose -f compose.yml -f compose.test.yml -p sirhosp-test \
  run --rm -T -v /tmp:/host-tmp test-runner bash -lc \
  "cd /app && PYTHONPATH=/app uv run --no-sync python \
   automation/lab/playwright_experiments/fullsync_failure_lab.py \
   --output /host-tmp/fx-verdicts.json"
python3 -c "import json; [print(v['hypothesis'], v['verdict'], v['reason']) \
  for v in json.load(open('/tmp/fx-verdicts.json'))['verdicts']]"
```

Comparar com os vereditos registrados no relatório CFC-S4 (H1/H2
confirmed; controles confirmed com reason None).

## Checks de inspeção obrigatórios

```bash
rg -n "## 6.3|fail-fast|evolution_window_budget|attempt" deploy/README.md | head
rg -n "markdownlint-disable" deploy/ ; echo "deve sair vazio"
git diff --name-only <BASE_REF_DO_CHANGE>..HEAD | rg "migration|pyproject|uv.lock"; echo "deve sair vazio"
git diff <BASE_REF_DO_CHANGE>..HEAD | rg -c "SYNTH|PRIV-"; echo "apenas testes/scanners"
```

## Gates de autoavaliação

1. Os vereditos do laboratório mudaram com a correção? (Esperado: não;
   por quê?)
2. O que a §6.3 orienta o operador a observar pós-rollout e por quais
   comandos existentes?
3. O que o diff total prova (e o que não prova)?
4. Quais gates falharam, se algum? Como foram tratados?
5. O que fica como pendência para o próximo change/release?

## Critérios de sucesso binários

- [ ] Laboratório re-executado com vereditos idênticos registrados.
- [ ] §6.3 escrita (o que mudou + como observar, só comandos existentes).
- [ ] Diff revisado sem PHI/migrations/dependências.
- [ ] Todos os gates + strict + markdown lint exit 0.
- [ ] Relatório final criado; nenhuma task marcada sem evidência.
- [ ] Sem arquivamento (exige verificação de terceiro LLM + autorização
      explícita do operador).

### Condições automáticas de INCOMPLETO

- FX-S1/S2/S3 não COMPLETE;
- veredito do laboratório mudou e não foi reportado como bloqueio;
- §6.3 ausente ou introduz comando/contrato novo;
- PHI/identidade/migration/dependência no diff;
- gate falho; relatório ausente; task prematura; arquivamento executado.

## Relatório obrigatório

`/tmp/sirhosp-slice-FX-S4-report.md`: Status; vereditos do laboratório
(antes/depois); resumo do diff total; gates; §6.3 (snippet); riscos;
pendências (rollout rc.15, worker clássico backlog, canário §6.1.2);
`Handoff para verificador` R1–R4.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full fix-fullsync-failure-exhaustion change, all FX slice prompts and the COMPLETE FX-S1..S3 reports. Execute ONLY FX-S4: rerun the CFC lab harness in the containerized test environment and register that H1/H2 verdicts and controls are unchanged; add the operational note §6.3 to deploy/README.md (what changed: invalid_payload fail-fast without requeue, window-scaled evolution budget 120s+2s/day capped 600s on the persistent worker; how to observe via existing health check, characterization command and stage metrics — no new commands/contracts); review the full change diff for PHI/identity/migrations/dependencies; run every official gate plus openspec validate fix-fullsync-failure-exhaustion --strict and markdown-lint, all exit 0 with final unit passed >= baseline. No production code changes. Never archive without third-party LLM verification and explicit operator authorization. Create /tmp/sirhosp-slice-FX-S4-report.md with evidence and verifier handoff. Any missing/failing item is INCOMPLETE. If complete, mark only 4.x, commit, push, reply REPORT_PATH=..., then STOP.
```
