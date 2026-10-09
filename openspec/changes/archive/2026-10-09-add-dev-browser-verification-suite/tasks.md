# Tasks: add-dev-browser-verification-suite

Estado atual: VFY-S1 ACEITO pelo operador em 2026-10-04 (commit `1ec13ac`);
VFY-S2 ACEITO pelo operador em 2026-10-05 após verification funcional
completa (auth PASS 22/22; smoke PASS 34/34 com expectations sintéticas;
duas falhas controladas FAIL/exit 1 com cleanup/revogação), review final
fresh/read-only sem P0/P1, gates reexecutados no estado final (quality-gate
4145, integration 944, ruff/mypy explícitos, OpenSpec strict, markdown-lint)
e commit atômico dos cinco arquivos. S3 não iniciado e não autorizado.
Este arquivo não concede autoridade operacional.
Executar um slice por vez, usar seu slice-prompt e parar para aceite.
Referência de entrada: master, 1ec13ac; confirmar antes de implementar.

## 1. VFY-S1 — Ciclo de sessão efêmera

Prompt: [SLICE-VFY-S1](slice-prompts/SLICE-VFY-S1.md).

Aceite limitado de F1/F2 registrado pelo parent com autorização do operador,
por inspeção e testes: 105 focados e 3867 unitários aprovados. A última
correção mínima não teve nova revisão independente. Evidências e limitações:
`/tmp/sirhosp-slice-VFY-S1-report.md`.
F3/F10 receberam aceite limitado do parent após inspeção do código e dos testes,
com 124 focados e 3886 unitários aprovados; vínculo Timer.Unit nativo, callback
bloqueante e checkpoint CLOSING durável. Sem nova revisão independente ou ações
em dev. F4 recebeu aceite limitado do parent após inspeção do fluxo real e
regressões RED/GREEN: 129 focados e 3891 unitários aprovados. PREPARE com resposta
incerta exige revogação da mesma geração e CLOSING durável antes de cleanup;
falha de revogação preserva o timer. Sem nova revisão independente.
F5 recebeu aceite limitado do parent por inspeção do schema/ownership e dos
seams reais: 70 regressões selecionadas, 199 focados e 3961 unitários aprovados.
Respostas incompletas/unowned não provam revogação; recover exige confirmação
afirmativa. Sem nova revisão independente ou ações em dev.
F6 recebeu aceite limitado do parent: snapshot v2 inclui PK e recusa
snapshot antigo após delete/recreate das duas contas reservadas. PostgreSQL
sintético: 202 focados, 3961 unitários e 941 integração aprovados, demais checks
aprovados. Sem nova revisão independente ou ações em dev.
F7 recebeu aceite limitado do parent após inspeção dos seams reais e prova RED
reconstruída: três regressões, 220 focados e 3979 unitários aprovados, gates e
checks explícitos do script aprovados. Revogação fenced não depende de sync da
namespace antes de flock; persistência continua requisito antes de publicação.
Cancelamento falho reporta cleanup unknown, sem alegar retenção/conclusão.
Executor substituído por zai/glm-5.3 high com autorização explícita após falhas
Meta; sem troca global, nova revisão independente ou ações em dev.
F8/F9/F11 foram concluídos nas etapas seguintes; o reparo da rota de banco e o
reparo do cleanup systemd foram validados com revisão independente e gates
finais novos. R8 operacional completa em 2026-10-04: fechamento da geração
congelada, idempotência do close, jornada manual (doctor, open, timer real,
logins em contextos exclusivos, close, recusa das sessões) e expiração
automática com TTL curto. Aceite do operador registrado; commit atômico dos
seis arquivos de S1 criado. Evidência: `/tmp/sirhosp-vfy-s1-r8-final-evidence.md`.

- [x] 1.1 Registrar base/working tree e RED focado de destino, colisão,
  revogação, orphan e stale callback no test-runner; evidência no relatório S1.
- [x] 1.2 Implementar serviço/command de contas owned com senhas efêmeras,
  papéis e close idempotente; provar login/sessão anterior recusados após close.
- [x] 1.3 Implementar doctor/open/status/close, lock, timer e start/stop
  restritos a db/web; testes de falhas/timer indisponível verdes.
- [x] 1.4 Documentar operação/recovery em docs/dev-verification.md e demonstrar
  abertura → login real → fechamento sem contas ativas ou timer owned pendente.
- [x] 1.5 Executar gates de S1, checks extras do script, Markdown/OpenSpec;
  entregar relatório /tmp/sirhosp-slice-VFY-S1-report.md e STOP para aceite.

## 2. VFY-S2 — Smoke Playwright repetível

Prompt: [SLICE-VFY-S2](slice-prompts/SLICE-VFY-S2.md). Depende de S1 aceito.

Aceito pelo operador em 2026-10-05. Implementation revisada por múltiplas
rodadas independentes (allowlist por porta/origem; sanitização em memória
de JSON/Markdown/stdout; prevenção CDP por hop com redirects, popups,
SW/WS; aborto fatal síncrono com verification nativa de cleanup).
Verification funcional final no dev: auth PASS 22/22, smoke PASS 34/34
(filtro positivo com expectations sintéticas do operador, polls reais de
60s, mobile, TomSelect), falhas controladas FAIL/exit 1 com cleanup/revogação
comprovados, contas owned revogadas, sessão CLOSED, sem mudança de negócio.
Review final: `/tmp/sirhosp-vfy-s2-final-review.md`; relatório completo:
`/tmp/sirhosp-slice-VFY-S2-report.md`; gates finais: `/tmp/vfy-s2-final/`.
P2 pendente (não bloqueador): comentários de fake-detach nos testes.

- [x] 2.1 RED focado de política de requests, reports, pré-requisitos,
  timeout e cleanup do driver; confirmar falha por comportamento ausente.
- [x] 2.2 Implementar run com contextos por papel e jornada real de
  autenticação/navegação; prova real sem force_login ou mock de auth.
- [x] 2.3 Provar censo/TomSelect, dois polls HTMX, menu mobile e visibilidade
  por papel; casos sem descritor fictício ficam BLOCKED e impedem falso PASS.
- [x] 2.4 Produzir JSON/Markdown/screenshots sanitizados e provar cleanup após
  sucesso/falha controlada, com artefatos ainda presentes e contas revogadas.
- [x] 2.5 Atualizar runbook, executar gates/checks extras/Markdown/OpenSpec,
  entregar /tmp/sirhosp-slice-VFY-S2-report.md e STOP para aceite.

## 3. VFY-S3 — Skill MCP e mapa de funcionalidades

Prompt: [SLICE-VFY-S3](slice-prompts/SLICE-VFY-S3.md). Depende de S2 aceito.

Aceito pelo operador em 2026-10-05. Skill `verify-sirhosp` + mapas entregues
(R1–R4/R7); prova MCP real de autenticação end-to-end (run `16b7593f…`:
login por formulário em contexto exclusivo, navegação leitura, evidências
sanitizadas, logout, close com revogação; sessão pessoal intacta);
isolamento de armazenamento DEMONSTRADO por probe dedicada (contextos A/B,
marcador ausente em B, presente em A; evidência redigida em
`/tmp/sirhosp-verification-mcp/isolation-probe/`); end state pós-logout
descrito corretamente (landing pública). Reviews:
`/tmp/sirhosp-vfy-s3-review.md` (P1/P2 → corrigidos) e
`/tmp/sirhosp-vfy-s3-review2.md` (APPROVE; P2 de redação de cookies na
probe resolvido pelo controller). Relatório:
`/tmp/sirhosp-slice-VFY-S3-report.md`. Limitação honesta: cobertura MCP =
autenticação e2e + leitura shell/censo/perfil; TomSelect/polls/mobile
seguem proven-playwright (marcados como futuros candidatos MCP).

- [x] 3.1 Registrar ausência documental e criar SKILL.md com frontmatter,
  contratos do ciclo e comandos comprovados de S1/S2; links/Markdown válidos.
- [x] 3.2 Criar README e quatro mapas de features com ações/end states e
  estados de cobertura; conferir seletores no repo e casos não comprovados.
- [x] 3.3 Provar uma feature por MCP em contexto exclusivo e fechar sessão;
  evidências sobrevivem, contas revogadas e sessão pessoal intacta.
- [x] 3.4 Atualizar manutenção/runbook, validar Markdown/OpenSpec e entregar
  /tmp/sirhosp-slice-VFY-S3-report.md; STOP para aceite.

## 4. Gate final e aceite operacional

Somente depois de todos os slices aceitos; responsabilidade do controller.

- [x] 4.1 Conferir diffs/ownership/limites com revisão humana e, se autorizada,
  revisão independente; nenhuma pendência concreta de segurança ou cleanup.
  (Review independente fresh/read-only realizada no gate final:
  `/tmp/sirhosp-change-final-review.md` — APPROVE, sem P0/P1. Revisão HUMANA
  concluída em 2026-10-05: operador revisou o status consolidado da change
  (slices aceitos, gates, verification final, pendências) e autorizou
  explicitamente o fechamento e o archive.)
- [x] 4.2 Executar ./scripts/test-in-container.sh quality-gate e integration,
  checks explícitos de scripts/automation, Markdownlint e OpenSpec strict.
  (Gate final 2026-10-05, logs `/tmp/vfy-final-gate/`: quality-gate 4145
  exit 0; integration 944 exit 0; ruff/mypy explícitos D9 exit 0;
  markdown-lint 0 erros; markdownlint explícito da skill 0 erros; OpenSpec
  strict válido.)
- [x] 4.3 Reexecutar smoke real e verificar estado final das contas, timer,
  browser e evidências; ausência de pré-requisito bloqueia o aceite.
  (Smoke final `b1e155c9…` PASS exit 0 34/34 com expectations do operador;
  revogação comprovada por owned-status fenced; timer/browser/stack
  verificados em artefato durável `/tmp/vfy-final-gate/timer-browser-check.txt`;
  evidências presentes e sanitizadas.)
- [x] 4.4 Registrar decisão do operador sobre parar web/db, relatório final
  sem credenciais e commits rastreáveis; não arquivar ou fazer push
  automaticamente.
  (Decisão 2026-10-05: manter web/db no estado atual, workers parados.
  Relatório final `/tmp/sirhosp-change-final-report.md`. Commits rastreáveis:
  S1 `1ec13ac`, S2 `87e85ee`, S3 `36ed7ee`. Sem push/merge/archive.)
