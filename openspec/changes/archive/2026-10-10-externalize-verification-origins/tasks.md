# Tasks: externalize-verification-origins

Execução autorizada pelo operador via `/change-loop`, incluindo bootstrap
privado e verification dev CLI/MCP com dados fictícios. ORIG-001 aceito pelo
controller após review independente sem P0/P1; gates finais aprovados.
Estado: `READY_FOR_HUMAN_FINAL_REVIEW`; revisão humana 2.4 pendente.
Contrato único:
[ORIG-001](slices/slice-001-private-origins.md).

## 1. ORIG-001 — Configuração privada integrada a CLI e MCP

Todos os itens deste grupo pertencem ao mesmo slice. Testes e documentação
entram com a implementação, não depois da revisão. Verificação funcional real
exige aprovação da change e autorização operacional do operador.

- [x] 1.1 Registrar baseline atribuível e criar regressões RED para R1–R4,
      sem alterar implementação; verificar falhas no test-runner oficial,
      inventário dos FQDNs por paths/contagens e caracterização inicial de R5
      em `/tmp/sirhosp-slice-ORIG-001-report.md`; contrato ORIG-001.
- [x] 1.2 Implementar resolvedor privado e validação HTTPS normalizada de
      duas origens, conforme D1–D2; verificar matrix unit GREEN, ausência de
      fallback/override/consultas a produção e diagnósticos sem valores
      inválidos; contrato ORIG-001, R1–R3.
- [x] 1.3 Integrar validação antes dos efeitos, metadata `origin` em doctor/open
      e transmissão explícita da fotografia de abertura à factory/browser/
      contexts/jornadas/policy; verificar JSON, sentinelas de não-mutação,
      regressões de transporte/fatal/sanitização e ausência de defaults
      operacionais; contrato ORIG-001, R2–R4/R8.
- [x] 1.4 Preservar imports, close/recovery/callback/status sem dependência de
      origens; verificar command paths canônicos com perfil temporário
      ausente/inválido, fingerprint/ownership e regressões de revogação/timer;
      contrato ORIG-001, R5/R8, sem apagar o perfil real durante uma sessão.
- [x] 1.5 Migrar fixtures para origens sintéticas e atualizar runbook,
      skill/mapas e template com chaves vazias; verificar scan dos arquivos
      atuais/candidatos sem os FQDNs da baseline, template vazio BLOCKED,
      consumo da origem canônica, dry-run de divergência doctor/open e
      Markdown explícito inclusive em `.pi`; contrato ORIG-001, R6–R8.
- [x] 1.6 Executar `uv run python scripts/verify_portal.py` para doctor,
      auth/smoke e roteiro MCP somente com perfil privado/expectativas
      preparados e operações autorizadas; verificar UI real, origem correta,
      revogação fenced, timers/browser owned ausentes, sem serviço de negócio
      iniciado; registrar evidência/limites no relatório obrigatório;
      contrato ORIG-001, R4/R7/R8.
- [x] 1.7 Obter review independente read-only do contrato/diff/evidências,
      sem P0/P1 aberto, e validações focadas obrigatórias aprovadas;
      o controller registra aceite do ORIG-001 e só então atualiza este
      grupo/cria commit atômico quando autorizado.

## 2. Gate final da change e revisão humana

Este grupo não é um segundo slice nem posterga testes/documentação do grupo
1. Verifica o estado final aceito, preservando as mudanças concorrentes.

- [x] 2.1 Executar `./scripts/test-in-container.sh quality-gate` e
      `./scripts/test-in-container.sh integration` no estado final; verificar
      exit 0, sem usar execução host-only como gate nem reusar resultado
      anterior a alteração de código.
- [x] 2.2 Repetir Ruff/mypy explícitos para scripts/automation conforme D9
      herdado, Markdown global mais skill/change explicitamente e
      `openspec validate externalize-verification-origins --strict`;
      verificar exit 0 e scan final sem FQDN operacional na árvore atual.
- [x] 2.3 Consolidar requirements → evidence, provas CLI/MCP e cleanup,
      limitações e baseline final em relatório de fechamento; se o estado de
      produto mudou depois das provas, repetir a verification afetada;
      declarar histórico não purgado e READY_FOR_HUMAN_FINAL_REVIEW apenas
      com todos os gates/evidências válidos e nenhuma decisão pendente.
- [x] 2.4 Revisão final humana explícita obtida do operador (2026-10-10);
      sync/archive/publicação autorizados para a rc.35.
