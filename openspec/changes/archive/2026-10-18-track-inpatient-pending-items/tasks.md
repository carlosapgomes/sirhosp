# Tasks

## 1. PEND-S1 — Gestão contextual auditada

- [x] 1.1 Implementar cadastro, edição, finalização e consulta de versões pela internação selecionada, com catálogo Outro, grupo sem bypass de superusuário, integridade/concorrência e proteção das relações em merge/consolidação. Contrato: [PEND-S1](slices/slice-001-gestao-contextual-auditada.md). Verificar R1–R6 por migrations, testes unitários/integrados, jornada contextual Playwright e relatório `/tmp/sirhosp-slice-PEND-S1-report.md` aceito sem P0/P1.

## 2. PEND-S2 — Encerramento por saída confirmada

- [x] 2.1 Integrar encerramento com autoria Sistema pelo estado fechado resultante dos três writers válidos, incluindo ativas residuais, com snapshot atômico por internação/item e sem reabertura ou efeitos por ausência no censo. Contrato: [PEND-S2](slices/slice-002-encerramento-por-saida-confirmada.md). Verificar R1–R5 por entradas reais, merge sem fim na confirmação, already_reconciled residual, falha no segundo de três itens e concorrência PostgreSQL incluindo snapshot × edição/cadastro; relatório `/tmp/sirhosp-slice-PEND-S2-report.md` aceito sem P0/P1.

## 3. PEND-S3 — Painel agregado e edição rápida

- [x] 3.1 Entregar menu e agregado com visão por paciente padrão, alternativa por pendência, filtros, primeira unidade registrada, indicadores globais, histórico recolhível e edição rápida responsiva. Contrato: [PEND-S3](slices/slice-003-painel-agregado-e-edicao-rapida.md). Verificar R1–R6 por testes de queries/HTTP, Playwright desktop/mobile e relatório `/tmp/sirhosp-slice-PEND-S3-report.md` aceito sem P0/P1.

## 4. PEND-S4 — Exportação XLSX autenticada

- [x] 4.1 Exportar estados atuais de todos os resultados filtrados, uma linha por pendência, para qualquer autenticado, sem histórico, fórmulas executáveis ou arquivo clínico residual. Contrato: [PEND-S4](slices/slice-004-exportacao-xlsx.md). Verificar R1–R4 por abertura/inspeção do workbook, download real como leitor, regressão de filtros e relatório `/tmp/sirhosp-slice-PEND-S4-report.md` aceito sem P0/P1.

## 5. Gate integrado da change

- [x] 5.1 Depois dos quatro slices aceitos, executar `./scripts/test-in-container.sh quality-gate`, `./scripts/test-in-container.sh integration`, `./scripts/markdown-lint.sh` e `openspec validate track-inpatient-pending-items --strict`; confrontar runtime com PI-01–PI-08 e PP-01–PP-09. Aceitar o gate somente com todos os comandos aprovados, não por ausência de erros novos. Se o lint global continuar bloqueado pelos arquivos de entrada preservados, manter este item pendente e registrar `NEEDS_HUMAN_DECISION` para autorizar sua correção ou decidir exceção explícita conforme `AGENTS.md`; lint focado não substitui o global. Esta é verificação transversal do controller, não outro slice; seguir o protocolo de reparo/review e não declarar a change pronta com gate obrigatório falhando.

## 6. Encerramento

- [x] 6.1 Revisão humana final confirmada pelo operador (2026-10-18):
      feature revisada em produção na release `v0.1.0-rc.40` (upgrade
      executado no mesmo dia; conferência do operador registrada em
      `docs/releases/2026-10-18_v0.1.0-rc.40.md`); archive autorizado
      junto com a sincronização das specs PI-01..PI-08 e PP-01..PP-09.

## Sequência e autoridade

PEND-S1 → PEND-S2 → PEND-S3 → PEND-S4 → gate integrado. Não executar slices em paralelo nem publicar estados intermediários incompletos. Todos começam pendentes; criar os artefatos não significa aprovação técnica dos slices nem autorização para iniciar implementação.

Usar `AGENTS.md` como política de execução, testes, revisão, aceite, atualização de estado e commits. Worker e reviewer não marcam tarefas; o controller atualiza somente após aceite. Sem push, deploy, archive ou alteração de contas operacionais neste planejamento.

Os testes e a documentação específica de cada entrega pertencem ao próprio slice; o grupo 5 não deve ser usado para adiar testes dos grupos anteriores.

## Rastreabilidade

| Requisito da spec | Slice principal | Evidência complementar |
| --- | --- | --- |
| PI-01 — Cadastro manual | PEND-S1 | Browser contextual e HTTP. |
| PI-02 — Catálogo com Outro | PEND-S1 | Migrations/admin, snapshots e proteção rename/delete de Outro inclusive sem uso. |
| PI-03 — Internação atual | PEND-S1 | PEND-S2 testa saída concorrente; PEND-S3 testa recorte agregado. |
| PI-04 — Grupo e acesso | PEND-S1 | PEND-S3 prova modal/leitor; PEND-S4 prova exportação por leitor. |
| PI-05 — Terminalidade | PEND-S1 | PEND-S2 preserva estados finais humanos. |
| PI-06 — Histórico | PEND-S1 | PEND-S2 prova Sistema/atomicidade; PEND-S3 prova consulta recolhível. |
| PI-07 — Saída confirmada | PEND-S2 | Três writers, estado fechado resultante/residual, atomicidade por item e snapshot concorrente no PostgreSQL. |
| PI-08 — Reconciliação | PEND-S1 | Guarda/corrida conservadora; PEND-S2 integra fechamento e rollback sem reabrir pendência. |
| PP-01 — Navegação contextual | PEND-S1 | Consulta histórica após saída em PEND-S2. |
| PP-02 — Agregado atual | PEND-S3 | Dataset com episódios anteriores e múltiplos status. |
| PP-03 — Duas visualizações | PEND-S3 | Browser desktop/mobile e paginação. |
| PP-04 — Filtros | PEND-S3 | PEND-S4 confronta seleção com workbook. |
| PP-05 — Primeira unidade | PEND-S3 | PEND-S4 verifica coluna e fallback. |
| PP-06 — Edição rápida | PEND-S3 | Modal real, histórico e atualização da listagem. |
| PP-07 — Indicadores globais | PEND-S3 | Relógio controlado, pacientes distintos e independência de filtros. |
| PP-08 — XLSX | PEND-S4 | Arquivo literal, completo, efêmero e acessível a todo autenticado; mesmo recorte conservador da lista/indicadores. |
| PP-09 — Cache clínico | PEND-S1 | Contexto/formulário/histórico; PEND-S3 cobre agregado/fragmentos e PEND-S4, XLSX. |

## Comandos e evidências

Os comandos oficiais e a distinção entre teste/verification estão em `AGENTS.md`. Quando for necessário executar Python diretamente dentro do ambiente isolado, usar `uv`, por exemplo `uv run python manage.py makemigrations --check --dry-run`; diagnóstico host-only não substitui os gates.

Os cenários de browser pertencem à suíte de integração com banco sintético efêmero. Não acionar automaticamente `scripts/verify_portal.py`, MCP ou o portal implantado: a camada complementar tem autorização e guardrails próprios em `docs/dev-verification.md`.

No planejamento, o lint global apresentou 64 erros preexistentes somente nas entradas ignoradas `tmp/respostas.md` e `tmp/respostas2.md`. A autorização para corrigir esta change não abrange esses arquivos nem as regras de lint. Zero erros nos artefatos da change pode ser reportado como validação focada, mas não aprova o gate global nem a task 5.1. Se o baseline persistir ao tentar o aceite final, é necessário pedir autorização para corrigir as entradas ou obter decisão explícita sobre exceção à política; até lá, registrar o bloqueio e não declarar a change pronta. Não alterar entradas, regras, varredura do script ou filtros para mascarar erros. O baseline em `/tmp/sirhosp-pending-items-markdown-baseline.log` é evidência auxiliar, não dependência do contrato.
