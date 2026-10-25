# Gate final da change — track-inpatient-pending-items

Data (UTC): 2026-10-17. Estado: master com os quatro commits de slice; worktree limpo.

## Comandos e resultados (todos exit 0)

| Comando | Resultado |
| --- | --- |
| `SIRHOSP_TEST_DB_PORT=55434 ./scripts/test-in-container.sh quality-gate` | check sem issues; unit 4344 passed; ruff All checks passed; mypy 485 arquivos sem erros. |
| `SIRHOSP_TEST_DB_PORT=55434 ./scripts/test-in-container.sh integration` | 1065 passed (inclui jornadas browser S1/S3/S4 com Chromium real e assets pinados). |
| `./scripts/markdown-lint.sh` | 0 erros (inclui SOURCES.md dos fixtures). |
| `openspec validate track-inpatient-pending-items --strict` | Change válida. |

Nota operacional: porta 55433 ocupada por container alheio (`s1-pg-test`); gates usaram `SIRHOSP_TEST_DB_PORT=55434`, suportado pelo script oficial.

## Commits atômicos dos slices

| Slice | Commit | Conteúdo |
| --- | --- | --- |
| PEND-S1 | `7eadffe` | Domínio, catálogo Outro, grupo, página contextual auditada, merge/guarda legada, harness browser. |
| PEND-S2 | `b6937e2` | Encerramento por saída confirmada nos três writers, snapshot atômico por item, corridas PG. |
| PEND-S3 | `897d4a8` | Menu Pendências, agregado com recorte conservador compartilhado, filtros, primeira unidade, indicadores, modal. |
| PEND-S4 | `2e5382f` | Exportação XLSX autenticada, uma linha por pendência, literal anti-fórmula, cache. |

Chore pré-slice: `6b7fcf1` (lint: ignorar `tmp/`).

## Confronto requisitos × evidência de runtime

| Requisito | Evidência executada |
| --- | --- |
| PI-01..PI-02 | S1: migrations/bootstrap, duplicidade de tipo, proteção de Outro (rename/delete inclusive sem uso); suítes unit+HTTP. |
| PI-03 | S1: bloqueios de ausência/ambiguidade com mensagem exata, sem provisórios; S2: ausência no censo não finaliza; S3: recorte conservador único. |
| PI-04 | S1: matriz de acesso sem bypass de superusuário; S3: leitor no painel/modal; S4: leitor/superuser exportam e continuam sem escrita. |
| PI-05/PI-06 | S1: FSM, versões atômicas, histórico somente leitura, cache/escape; S2: atomicidade por item e Sistema. |
| PI-07 | S2: três writers, estado resultante fechado, idempotência, corridas PostgreSQL reais (snapshot/reconcile/merge × edição/cadastro). |
| PI-08 | S1/S2: registro no merge, guarda legada (incl. intercalação conservadora), rollbacks preservando versões sem reabrir. |
| PP-01/PP-03 | S1: página contextual e histórico; S3: browser desktop 1280x800 e mobile 390x844 com assets reais interceptados. |
| PP-02 | S3: ambiguidades excluídas, repetições equivalentes 1x, episódios anteriores fora (mesma seleção de indicadores). |
| PP-04 | S3: filtros antes do agrupar, tempo exato, Sistema como atualizador; S4: paridade workbook×painel. |
| PP-05 | S3: PS→UTI→Enfermaria e fallback `Primeira unidade não identificada`; S4: coluna no XLSX. |
| PP-06 | S3: modal com serviço canônico, conflito/saída/perda de grupo sem sucesso falso, grupo vazio removido. |
| PP-07 | S3: 2 pacientes/média 5/máx 8 na fixture; independência de filtros/modo/página. |
| PP-08 | S4: downloads reais como leitor (3 na jornada browser), todos os resultados além da página, literalidade por tipo de célula, sem resíduo. |
| PP-09 | S1/S3/S4: `private, no-store` em HTML/fragmentos/formulários/erros/XLSX (com dados e vazio). |

## Failing-before por slice

- S1: RED estrutural + alternâncias por integração (worker) e correções/harness validados pelo controller.
- S2: RED clássico executado pelo worker (15 failed antes; GREEN depois) — workers reais como pontos de entrada.
- S3: alternância real pelo controller (rotas off: 31 failed → on: 32 passed) — worker impedido de executar.
- S4: RED unitário real (ModuleNotFoundError) + alternância real pelo controller (18 failed → 19 passed).

## Revisões independentes (fresh, read-only)

- S1: ACCEPT, 0 findings. S2: ACCEPT, 1 P2 (data fixa) — resolvido. S3: ACCEPT, 1 P2 (resolver duplicado) — resolvido com núcleo compartilhado e gates revalidados. S4: ACCEPT, 0 findings.

## Limitações e pendências operacionais (não bloqueiam a change)

- Associação de usuários ao grupo `Desospitalização` e cadastro de tipos além de `Outro`: ação administrativa pós-deploy, fora do escopo.
- Deploy/publicação, archive da change, push: exigem autorização explícita, não executados.
- A suíte complementar do portal dev implantado (`docs/dev-verification.md`) não foi acionada; toda verification ocorreu na suíte isolada com dados sintéticos.
