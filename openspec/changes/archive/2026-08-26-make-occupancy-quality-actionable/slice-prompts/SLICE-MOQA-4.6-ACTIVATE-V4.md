# MOQA-4.6 — Publicação explícita do catálogo v4

## Handoff com contexto zero

Execute somente a task 4.6 após ler `AGENTS.md`, `PROJECT_CONTEXT.md`, todos os
artefatos MOQA, prompts/relatórios 4.4–4.5, comando e serviço de ativação. A
RC10 está em produção. O operador aprovou explicitamente a vigência
`2026-08-24`, cujo dry-run do hash
`141166289c296cb5982da3f145edddf576d15392303ba2d7aaf198ff4bfaf0f9` passou.
Use o pane tmux 9 autenticado como root em `/srv/apps/prisma`.

## Objetivo

Publicar atomicamente o documento v4 completo para `2026-08-24`, provar
idempotência e preservação byte-equivalente dos três catálogos anteriores. Antes
da meia-noite local, v3 deve continuar aplicável; para `2026-08-24`, a seleção
deve apontar v4. Não executar primeiro censo v4 nem task 4.7.

## Requisitos

- R1: confirmar root, RC10, health, DB, migrations, 10 workers e data local
  exatamente `2026-08-23`; se já for 24, parar INCOMPLETO.
- R2: verificar backup RC10 protegido/checksum, hash do JSON v4, v3 aplicável,
  data 24 vazia e zero medições v4.
- R3: capturar snapshot JSON ordenado dos três catálogos anteriores com datas,
  schemas, algoritmos, hashes e contagens agregadas.
- R4: executar uma única publicação sem `--dry-run` para `2026-08-24` e exigir
  `created=True`/saída `publicado`.
- R5: repetir exatamente a ativação e exigir no-op idempotente `created=False`/
  `já publicado (idempotente)`.
- R6: confirmar v4 único, schema 3.0, hash, 43 grupos, 48 memberships, 47
  códigos, 39 standard, 4 unrated, 666/666 e aliases 48/48.
- R7: snapshot dos três catálogos anteriores deve ser literalmente igual;
  medições v4 continuam zero e não há backfill.
- R8: seleção aplicável usa v3 em 2026-08-23 e v4 em 2026-08-24; nenhuma
  mistura por dia.

## Escopo e proibições

Não editar `.env`, Compose, migrations, versões antigas ou medições. Não
reiniciar serviços, executar extração/processamento, aguardar censo v4, expor
PHI ou realizar rollback destrutivo. Nenhum arquivo rastreado muda. Após sucesso,
marcar somente 4.6 e criar `/tmp/sirhosp-slice-MOQA-4.6-report.md`.

## Critérios binários

- [ ] Autorização/data/hash exatos.
- [ ] Preflight R1–R3 verde.
- [ ] Publicação criada uma vez.
- [ ] Segunda execução idempotente.
- [ ] Totais e aliases v4 íntegros.
- [ ] Três versões anteriores byte-preservadas.
- [ ] Zero medição/backfill v4.
- [ ] V3 aplicável hoje e v4 amanhã.
- [ ] Runtime saudável e zero erro estrutural.
- [ ] Somente 4.6 marcada; parar antes de 4.7.

### INCOMPLETO automático

Data local diferente de 2026-08-23, catálogo existente na data, hash diferente,
backup inválido, falha parcial, totais divergentes, versão anterior alterada,
medição v4 existente, seleção diária incorreta, PHI ou execução de 4.7 tornam o
slice INCOMPLETO.

## Gates finais

```bash
openspec validate make-occupancy-quality-actionable --strict
./scripts/markdown-lint.sh
git status --short --branch
```

## Relatório

Criar `/tmp/sirhosp-slice-MOQA-4.6-report.md` com status, autorização, matriz
R1–R8, snapshots seguros, output de criação/idempotência, catálogo v4, seleção
por data, privacidade, riscos e próximo passo. Não incluir dados clínicos.

## Prompt pronto

```text
Execute ONLY MOQA task 4.6. The operator explicitly approved v4 effective on
2026-08-24 with SHA-256 141166...bfaf0f9. In root tmux pane 9, preflight RC10,
backup, local date 2026-08-23, v3 and zero v4. Snapshot the three historical
catalogs using aggregate metadata, publish the exact v4 once, prove the exact
retry is idempotent, verify 43/48/47/39/4/666/666 and aliases 48/48, historical
snapshot equality, zero v4 measurements, and v3-today/v4-tomorrow selection.
Never run a census, backfill, restart, edit env/Compose or expose PHI. Mark only
4.6, report to /tmp/sirhosp-slice-MOQA-4.6-report.md and STOP.
```
