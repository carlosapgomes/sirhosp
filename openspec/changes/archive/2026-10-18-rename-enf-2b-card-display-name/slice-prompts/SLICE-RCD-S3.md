# RCD-S3 — Runbook de publicação + prova local de dry-run

## Handoff para implementador LLM com contexto zero

Leia integralmente, na ordem:

1. `AGENTS.md`, `PROJECT_CONTEXT.md` e `deploy/README.md`;
2. `openspec/changes/rename-enf-2b-card-display-name/proposal.md`,
   `design.md` (D6 é a decisão central deste slice) e `tasks.md` (§3 e §5);
3. `openspec/changes/rename-enf-2b-card-display-name/activation-runbook.md`
   (esqueleto a completar/validar) e o delta
   `specs/versioned-sector-capacity-catalog/spec.md` (cenário de dry-run);
4. `apps/census/management/commands/activate_sector_capacity_catalog.py` e
   `apps/census/capacity_catalog.py` — SOMENTE LEITURA (semântica de
   `--dry-run` nada persiste; publicação exige data estritamente futura em
   `America/Bahia`; retry exato é idempotente);
5. Precedente operacional:
   `openspec/changes/archive/2026-08-26-make-occupancy-quality-actionable/slice-prompts/SLICE-MOQA-4.6-ACTIVATE-V4.md`
   (estrutura de R1..Rn operacionais) e
   `docs/releases/v0.1.0-rc.11-upgrade.md` (formato de runbook de upgrade).

## Protocolo obrigatório

Este slice NÃO executa publicação real (nem local sem `--dry-run`, nem em
produção): a publicação é a ação operacional do operador pós-deploy
(tasks.md §5). Toda execução aqui é `--dry-run` em container de teste, que
por contrato não persiste nada. Evidências no relatório; falha de dry-run ou
de markdown lint ⇒ INCOMPLETO.

## Objetivo do slice

Provar localmente que o v6 passa pelo comando oficial de ativação em modo
`--dry-run` (exit 0, totais corretos, nada persistido) e entregar o runbook
definitivo de publicação para o operador, com comandos exatos, pré/pós-
condições, idempotência e proibições.

## Requisitos verificáveis

- **R1 — Dry-run local**: em container de teste,
  `activate_sector_capacity_catalog --input
  apps/census/data/sector_capacity_catalog_v6.json --effective-from
  2099-01-01 --dry-run` termina com exit 0 e saída "validado (dry-run)"
  reportando `occupancy-v5`, 43 grupos, 48 memberships, 47 códigos, 39
  standard, 4 unrated e 666/666. A cobertura de aliases 48/48 NÃO aparece no
  stdout (o comando não imprime essa métrica —
  `activate_sector_capacity_catalog.py:63-77`); ela fica comprovada pelos
  testes de contrato do S1 (R2/R6). Data distante (2099-01-01) é proposital
  para o check local nunca virar passado.
- **R2 — Nada persistido**: a execução de R1 não cria linhas (comportamento
  garantido pelo modo `--dry-run` do comando; quando houver db de teste
  disponível, evidencie com contagem de
  `CapacityCatalogVersion`/`CapacityGroupDefinition` antes/depois = igual).
- **R3 — Runbook completo**: `activation-runbook.md` contém pré-condições
  (release deployado/saudável, backup, hash do JSON conferido, data futura
  aprovada), os três comandos (dry-run → publicar → retry idempotente) com
  resultados esperados ("validado (dry-run)" / "publicado" / "já publicado
  (idempotente)"), pós-condições (primeiro dia local integral em v6; `/beds`
  exibe `Enfermaria 2B Cardio` após a primeira medição do dia; medições
  anteriores preservam o rótulo antigo; nenhuma mistura v5/v6 por dia) e
  proibições/rollback (não editar v6 após publicar; não há unpublish —
  ADR-0003; correção futura = v7).
- **R4 — Markdown lint**: `./scripts/markdown-lint.sh` sem erros nos `.md`
  do change.

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1 | saída de comando (relatório) | dry-run em container, exit 0 + totais (sem métrica de aliases no stdout) |
| R2 | saída de comando (relatório) | contagem de rows antes/depois igual (ou natureza do dry-run citada) |
| R3 | `openspec/changes/rename-enf-2b-card-display-name/activation-runbook.md` | revisão por checklist do R3 |
| R4 | todos os `.md` do change | `./scripts/markdown-lint.sh` exit 0 |

## Arquivos esperados e limite

Máximo de **1 arquivo**:

1. `openspec/changes/rename-enf-2b-card-display-name/activation-runbook.md`
   (completar/ajustar o esqueleto já criado no change).

`allowed_incidental_files`: nenhum. Fora de escopo (proibido): publicação
real (sem `--dry-run`) em QUALQUER ambiente; edição de código, JSONs ou
outros `.md` do change; `docs/releases/` (o release doc é escrito no
preparo do release, fora deste change).

## Execução e verificação local

1. R1/R2 — comando (data 2099-01-01 é futura estável para check local);
   registrar a saída integral no relatório:

   ```bash
   docker compose -p sirhosp-test -f compose.yml -f compose.test.yml up -d db
   docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm \
     test-runner bash -lc "uv run --no-sync python manage.py \
     activate_sector_capacity_catalog \
     --input apps/census/data/sector_capacity_catalog_v6.json \
     --effective-from 2099-01-01 --dry-run"
   ```

   Resultado esperado: exit 0; mensagem "validado (dry-run)"; totais
   43/48/47, 39 standard, 4 unrated, 666/666; `occupancy-v5` (a métrica de
   aliases não é impressa pelo comando).

2. R3 — completar o runbook seguindo o checklist de R3 (o esqueleto já traz
   a estrutura; conferir comandos e mensagens esperadas contra o comando
   real executado em 1).

3. R4 — `./scripts/markdown-lint.sh` — exit 0.

## Critérios de aceitação

- [ ] Dry-run local exit 0 com totais corretos (grupos/associações/códigos/
      capacidades — a métrica de aliases não é impressa), saída integral no
      relatório;
- [ ] Evidência de nada persistido (contagem antes/depois ou citação do
      contrato do modo dry-run);
- [ ] Runbook completo conforme R3 (checklist item a item no relatório);
- [ ] Markdown lint exit 0;
- [ ] Diff = 1 arquivo; nenhuma publicação real executada;
- [ ] Relatório `/tmp/sirhosp-slice-RCD-S3-report.md` com comandos, exit
      codes e a saída do dry-run.

## Bloqueios conhecidos

- Se o dry-run falhar (validação, hash, data), NÃO ajuste o JSON neste
  slice: reporte INCOMPLETO com a mensagem exata (correção de JSON é
  reabertura do RCD-S1).
- Se o ambiente de teste estiver indisponível, registre o obstáculo e
  reporte INCOMPLETO — dry-run é a evidência central deste slice.
