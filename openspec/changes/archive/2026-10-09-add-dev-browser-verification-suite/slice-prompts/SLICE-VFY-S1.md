# SLICE-VFY-S1 — Abrir e encerrar contas efêmeras no dev

## Handoff de entrada e objetivo

Você inicia com contexto zero. Leia AGENTS.md e PROJECT_CONTEXT.md.
Este change cria uma suíte complementar, não modifica o produto. Implemente
somente S1: o operador abre uma sessão de teste no dev, recebe credenciais
efêmeras para contas exclusivas e consegue revogá-las, incluindo recovery.
NÃO execute S2/S3. Após relatório e validação, STOP.

A primeira entrega é vertical: comando → conta persistida → login real
comprovado → close → login/sessão anterior recusados. O driver Playwright
repetível fica em S2; a prova operacional de S1 pode usar browser dedicado.

## Contexto mínimo

- ../design.md, decisões D1–D4 e D9; ../specs/dev-verification-sessions/spec.md.
- apps/accounts/models.py, middleware.py e management/commands/create_portal_user.py.
- tests/integration/test_accounts_provisional.py e test_portal_entry_auth.py.
- compose.yml, compose.dev.yml e compose.test.yml; docker/entrypoint.sh.
- scripts/test-in-container.sh e scripts/container-smoke.sh somente para leitura.
- config/settings.py: redirect /painel/, DEBUG e conexão ao db.
- Referência da abertura do change: master, HEAD curto 118c91d; registrar o HEAD
  atual antes de editar, sem assumir que a referência permaneceu igual.

Os caminhos começando com ../ são relativos a este arquivo. Os demais são
relativos à raiz /projects/dev/sirhosp. Não ler ou editar credenciais do .env.

## Requisitos verificáveis

- R1: doctor read-only valida alvo dev, conexão/schema, dataset declarado e
  workers parados; alvo errado, DEBUG verdadeiro ou migrations pendentes
  bloqueiam antes de qualquer mutação. Comando Django direto também exige
  contexto de dev explícito; não deixar uma API de reset arbitrário.
- R2: abrir cria/reutiliza somente verify_user/verify_admin owned; uma colisão
  sem marcador bloqueia atomicamente. Normalizar somente os papéis dessas
  contas; garantir comum sem permissão Estatísticas e admin autorizado.
- R3: novas senhas imprevisíveis por execução, sem senha em arquivo/argv;
  open assistido pode emitir uma vez. Perfil normal sem troca obrigatória.
- R4: close idempotente torna senhas inutilizáveis, contas inativas e a sessão
  anterior anônima no próximo request; nenhuma conta humana é alterada.
  Readiness de abertura (DEBUG, workers, outras migrations) não impede close
  se destino/ownership e banco de autenticação estiverem acessíveis.
- R5: lock/registro não secreto impedem sobreposição; callback com run-id
  antigo não revoga o run atual; órfã exige recovery antes da abertura.
- R6: timer do usuário armado antes da emissão; falha de agendamento revoga
  e bloqueia. Failure de close permanece visível, sem falso CLOSED.
- R7: --start/--stop operam apenas db/web de dev, sem -v, workers ou edge.
  Parar db somente após tentar/comprovar a revogação; relatar falha e orientar
  contenção do web se o db não estiver acessível.
- R8: runbook demonstra abertura/login/fechamento e limites de reboot; cleanup
  da prova não deixa contas ativas ou timer owned pendente.

## Escopo e limite de arquivos

Máximo: seis arquivos de implementação/documentação abaixo. Até dois artefatos
adicionais, tasks.md e relatório /tmp, são responsabilidade do controller.
Qualquer novo arquivo, alteração de modelo/migration ou expansão exige STOP
e aprovação do operador antes de continuar.

```yaml
expected_files:
  - apps/accounts/verification.py
  - apps/accounts/management/commands/verification_session.py
  - scripts/verify_portal.py
  - tests/unit/test_verification_session.py
  - tests/integration/test_verification_session.py
  - docs/dev-verification.md
allowed_incidental_files: []
out_of_scope:
  - models/migrations/auth backends/settings/templates
  - create_portal_user e usuários humanos
  - driver Playwright, skill MCP e novos servidores/providers
  - Compose/env/infra edge/systemd permanente
```

## TDD e testes focados

Antes do RED, registrar BASE_REF/baseline uma vez e confirmar imagem test-runner
atualizada conforme design D9. Se a imagem estiver obsoleta, reconstruir somente
ela com o Compose de testes; não corrigir falta de dependência removendo middleware
ou alterando o lockfile. Baseline global somente se não houver CI confiável.

RED: escrever os testes R1–R7 primeiro. O comando abaixo deve falhar por ausência
dos novos contratos, não por DNS/configuração ou fixtures inválidas.

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test \
  -f compose.yml -f compose.test.yml run --rm test-runner \
  uv run --no-sync pytest -q tests/unit/test_verification_session.py \
  tests/integration/test_verification_session.py
```

GREEN: implementar o mínimo e repetir exatamente o comando, exit 0.
Fakes são permitidos para Docker/systemd/clock nos testes de controlador;
auth e persistência em integration são Django/PostgreSQL reais. Testar
check_password/has_usable_password, cliente autenticado antes/depois de close,
colisão, falha parcial, orphan e stale callback. Não passar senha real do dev
como fixture nem usar banco dev para os testes de implementação.

## Verificação operacional e gates

- Provar R8 em destino confirmado: doctor, open, login real pelo formulário,
  close e requisição com a sessão anterior. Repetir close sem erro.
- Antes da prova, obter autorização de ativação e confirmar dataset fictício.
  Se browser/timer/destino não estiver pronto, reportar BLOCKED; não improvisar.
- A prova não usa force_login nem mock; preservar contas humanas e evidências.
- Executar check, unit, integration, lint e typecheck via
  ./scripts/test-in-container.sh, como especificado em AGENTS.md.
- Executar os checks extras de scripts/verify_portal.py em design D9.
- Validar Markdown e openspec validate add-dev-browser-verification-suite --strict.
- Encerrar somente o projeto sirhosp-test criado pelos testes; nunca -v.

## Aceite e handoff de saída

- [ ] R1–R7 cobertos por RED/GREEN e regressão de auth existente.
- [ ] R8 demonstrado; contas owned inativas e senhas inutilizáveis no final.
- [ ] Runbook utilizável, gates aprovados e nenhuma mudança fora do limite.
- [ ] Relatório /tmp/sirhosp-slice-VFY-S1-report.md com arquivos, fragmentos
  antes/depois, comandos, resultados, evidências e riscos sem credenciais.

O controller atualiza tasks somente depois de conferir as evidências.
Revisão independente apenas quando autorizada pelo operador; este prompt não
autoriza delegação. Não fazer push nem iniciar o próximo slice automaticamente.
