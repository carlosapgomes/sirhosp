# SLICE-VFY-S2 — Smoke real por Playwright com evidências

## Handoff de entrada e objetivo

Leia AGENTS.md e PROJECT_CONTEXT.md. S1 deve estar aceito, com open/close/doctor
operacionais e prova de revogação. Implemente somente S2: um comando run executa
jornadas reais do portal, produz evidências e revoga contas após sucesso/falha.
Não gerar a skill MCP ainda. Não iniciar extração ou criar dados de negócio.

## Contexto mínimo

- ../design.md D2–D7 e D9; ../specs/dev-browser-verification/spec.md.
- scripts/verify_portal.py e apps/accounts/verification.py entregues em S1.
- docs/dev-verification.md e testes de S1.
- templates/registration/login.html, base_sidebar.html, includes/sidebar.html
  e includes/topbar_sync.html.
- apps/services_portal/templates/services_portal/censo.html, urls.py;
  config/settings.py e tests/integration/test_portal_entry_auth.py.
- tests/integration/test_topbar_census_freshness.py.
- apps/ingestion/views.py, statistics_reports/views.py e templates/base.html
  somente para identificar mutações e assets externos permitidos.

../ é relativo ao prompt; outros caminhos são relativos ao repo.
O produto atual redireciona ao /painel/; drift da spec antiga está em design.
Não corrigir produto/specs de terceiros oportunisticamente.

## Requisitos verificáveis

- R1: run usa S1, mantém senhas em memória e contexts novos por papel; login
  real por Usuário/Senha/Entrar, navegação e logout pelo botão Sair.
- R2: provar /painel/, links Censo/Perfil, identidade e menu ativo; item
  Estatísticas ausente no comum e presente no admin sem visitar exports.
- R3: censo exercita TomSelect e filtros por UI; o filtro positivo compara
  descritor fictício conhecido antes da ação. Sem dados esperados: BLOCKED.
  Não inserir fixture no db nem deduzir esperado da resposta filtrada.
- R4: observar dois polls HTMX reais, swaps sem badge duplicado e sem login
  no fragmento; mobile opera sidebarToggle/sidebarOverlay/Escape.
- R5: allowlist de origem/método/caminho inclusive redirects e popups; permitir
  POST somente login/logout; rotas de negócio mutantes e GET de demografia
  bloqueados. CDNs apenas nos caminhos versionados conhecidos.
- R6: detectar erro JS, HTTP inesperado, asset obrigatório faltante e
  criação de jobs; não descartar erros globalmente ou apagar efeitos.
- R7: JSON/Markdown/screenshots por run, sem senhas/headers/cookies/body de
  auth; artefatos sobrevivem ao cleanup. Códigos/agrupamento conforme D7.
- R8: finally em sucesso, assert falha e timeout: close de S1 e browser owned.
  Cleanup falho impede exit 0. Não fechar o Chrome pessoal ou parar edge.

## Escopo e limite de arquivos

Máximo seis arquivos abaixo, mais tasks/relatório do controller (até dois).
Se precisar modificar templates, dependências, políticas de auth ou persistir
dados clínicos, STOP e escale ao operador.

```yaml
expected_files:
  - automation/verification/__init__.py
  - automation/verification/browser.py
  - scripts/verify_portal.py
  - tests/unit/test_verification_browser.py
  - tests/unit/test_verification_session.py
  - docs/dev-verification.md
allowed_incidental_files: []
out_of_scope:
  - conectores automation/source_system e laboratório de scraping
  - modelos/migrations/templates/deployment
  - exports, troca de senha, ingestão, sumários e CRUD
  - skill MCP e qualquer reutilização da sessão pessoal do operador
```

## TDD e testes focados

RED: testes para R5–R8 e contratos do driver antes de implementá-los; cobrir
rota GET mutante, redirects externos, credenciais em report, cleanup falho,
timeout e caso solicitado sem fixture. Falha esperada: contratos ausentes.

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test \
  -f compose.yml -f compose.test.yml run --rm test-runner \
  uv run --no-sync pytest -q tests/unit/test_verification_browser.py \
  tests/unit/test_verification_session.py
```

GREEN: repetir o mesmo comando após a implementação mínima.
Fakes de Page/subprocess são testes do runner, não evidência de que a UI funciona.

## Prova real e validação

Interface prevista, a documentar e executar literalmente:

```bash
uv run python scripts/verify_portal.py run --feature auth --role both \
  --confirm-synthetic-data
uv run python scripts/verify_portal.py run --feature smoke --role both \
  --confirm-synthetic-data --expectations /CAMINHO/PRIVADO/expectations.json
```

A segunda linha é molde: o operador fornece arquivo com descritor fictício
e resultados esperados, sem credenciais. Ausência gera BLOCKED; não criar
um arquivo com dados extraídos de pacientes reais. Provar R1–R4 em desktop
1440x900 e mobile 390x844; o poll usa o intervalo real de 60s, sem setter DOM.
Repetir uma falha controlada para R8, preservando evidence e revogando contas.

Executar check/unit/lint/typecheck oficiais; a regressão integration de S1
deve permanecer verde. Usar design D9 para checks explícitos de scripts e
automation/verification. Markdown e OpenSpec devem passar. Browser ausente
é bloqueio operacional, não permissão para instalar/reconfigurar tudo ou
usar pytest host-only como gate. Encerre só a stack de testes owned.

## Aceite e handoff de saída

- [ ] R1–R8 provados por testes do executor e evidência de navegador real.
- [ ] Casos sem pré-requisito não viraram PASS; credenciais revogadas no final.
- [ ] Gates/regressões aprovados e dataset/volumes preservados.
- [ ] Relatório /tmp/sirhosp-slice-VFY-S2-report.md com antes/depois por arquivo,
  comandos, assertions/evidências e riscos, sem credenciais.

Sem delegação implícita, commit/push automático ou execução de S3. STOP.
