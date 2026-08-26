# MOQA-4.5 — Confirmação v3 e dry-run v4 sem escrita

## Handoff com contexto zero

Execute somente a task 4.5 após a RC10 implantada. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, todos os artefatos MOQA, prompt/relatório 4.4, runbook
RC10, comando `activate_sector_capacity_catalog.py`, serviço
`capacity_catalog.py` e catálogo v4. Acesso de produção: pane tmux janela 9,
reautenticado como root; antes de operar faça `cd /srv/apps/prisma`.

## Objetivo

Confirmar por metadados agregados que produção usa RC10 com catálogo v3 e zero
v4; calcular a primeira data estritamente futura em `America/Bahia`; executar
somente dry-run do documento v4 e provar estado do banco idêntico antes/depois.

## Requisitos

- R1: health, imagem/revisão, dez workers e migrations 0022/0023 verdes.
- R2: catálogo vigente v3 de hash conhecido; zero catálogos/medições v4.
- R3: data candidata calculada por `timezone.localdate() + 1 dia`, não
  hardcoded; é somente candidata para a task 4.6.
- R4: SHA do JSON v4, schema 3.0, `occupancy-v4`, 43 grupos, 48 memberships,
  47 códigos, 39 standard, 4 unrated, 666/666 e aliases 48/48.
- R5: dry-run via management command e via serviço retorna `created=False`.
- R6: snapshot agregado e determinístico do banco é byte-idêntico antes/depois,
  incluindo contagens de versões, grupos, memberships, v4 e data candidata.
- R7: nenhum comando sem `--dry-run`, nenhuma publicação, migration, backfill,
  restart ou alteração de `.env`/Compose.

## Escopo

Nenhum arquivo rastreado deve mudar. Somente `tasks.md` pode marcar 4.5 após
sucesso e relatório `/tmp/sirhosp-slice-MOQA-4.5-report.md` deve ser criado.
Task 4.6 permanece desmarcada.

## Inspeções e gates

Local:

```bash
openspec validate make-occupancy-quality-actionable --strict
./scripts/markdown-lint.sh
git status --short --branch
```

Produção, somente agregados:

- `docker compose config --quiet`, `ps`, DB ready e health;
- imagem RC10 e revisão `19bdcf5...`;
- migrations 0022/0023 aplicadas;
- snapshot JSON `sort_keys=True` antes/depois;
- dry-run e totais/aliases;
- zero `Traceback|CRITICAL` recente.

## Critérios binários

- [ ] Root e diretório corretos.
- [ ] RC10 saudável com dez workers.
- [ ] V3 vigente e v4 zero antes.
- [ ] Data candidata é amanhã local e não existe no banco.
- [ ] Hash/schema/algoritmo/totais/aliases v4 corretos.
- [ ] Dry-run informa `created=False`.
- [ ] Snapshot antes/depois exatamente igual.
- [ ] V4 continua zero depois.
- [ ] Nenhuma ativação ou mutação operacional.
- [ ] Relatório sanitizado e somente 4.5 marcada.

### INCOMPLETO automático

Qualquer divergência, escrita, catálogo na data candidata, v4 já existente,
health/worker/migration falho, snapshot diferente, comando sem `--dry-run`, PHI
em saída, task posterior marcada ou gate local falho torna o slice INCOMPLETO.

## Relatório

Criar `/tmp/sirhosp-slice-MOQA-4.5-report.md` com status, referências, matriz
R1–R7, comandos/resultados, snapshot antes/depois, data candidata, hash/totais,
prova de zero escrita, privacidade, riscos e handoff. Marcar somente 4.5 e parar.

## Prompt pronto

```text
Execute ONLY MOQA task 4.5 from the authenticated root tmux window 9. Confirm
RC10/v3, calculate tomorrow in America/Bahia as a candidate only, run the v4
catalog strictly with --dry-run, verify 43/48/47/39/4/666/666 and aliases 48/48,
and prove an aggregate sorted database snapshot is exactly unchanged. Never
publish/activate, migrate, restart, edit env/Compose or expose PHI. Any mismatch
is INCOMPLETE. Create /tmp/sirhosp-slice-MOQA-4.5-report.md, mark only 4.5 and
STOP.
```
