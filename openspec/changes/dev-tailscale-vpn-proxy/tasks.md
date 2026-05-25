# Tasks: dev-tailscale-vpn-proxy

## 1. Slice S1 - Configuração Playwright proxy centralizada

Escopo: criar base de configuração opcional de proxy Playwright com testes, sem
alterar ainda todos os scripts de scraping.

Limite: até 5 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S1.md`.

- [ ] 1.1 (RED) Criar teste unitário falhando para env ausente/vazia/presente de
      `PLAYWRIGHT_PROXY_SERVER`.
- [ ] 1.2 Criar helper central para retornar configuração Playwright
      `proxy={"server": ...}` somente quando a env estiver definida.
- [ ] 1.3 Adicionar teste de integração/mocking mínimo em um script Playwright
      representativo para provar que o proxy é repassado ao `chromium.launch`.
- [ ] 1.4 Preservar `--ignore-certificate-errors` e `ignore_https_errors=True`.
- [ ] 1.5 Executar testes unitários relevantes e gerar
      `/tmp/sirhosp-slice-S1-report.md`.

## 2. Slice S2 - Aplicação do proxy em todos os scripts Playwright operacionais

Escopo: atualizar todos os pontos operacionais que chamam `chromium.launch` para
usar o helper opcional, mantendo comportamento antigo quando a env não existir.

Limite: até 10 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S2.md`.

- [ ] 2.1 (RED) Usar busca por `chromium.launch` para listar pontos ainda sem o
      helper.
- [ ] 2.2 Aplicar o helper nos scripts Playwright de `automation/source_system/`.
- [ ] 2.3 Garantir que nenhum script altere `SOURCE_SYSTEM_URL`, usuário ou senha.
- [ ] 2.4 Garantir que argumentos existentes de Chromium e contexts HTTPS sejam
      preservados.
- [ ] 2.5 Executar testes unitários relevantes, lint/typecheck aplicáveis e gerar
      `/tmp/sirhosp-slice-S2-report.md`.

## 3. Slice S3 - Sidecar Tailscale no Compose dev

Escopo: adicionar sidecar Tailscale userspace/SOCKS5 ao `compose.dev.yml` e
propagar a env opcional de proxy para serviços que podem executar Playwright.

Limite: até 5 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S3.md`.

- [ ] 3.1 (RED operacional) Demonstrar que `compose.dev.yml` ainda não possui
      sidecar Tailscale nem `PLAYWRIGHT_PROXY_SERVER`.
- [ ] 3.2 Adicionar serviço `tailscale-app` dev-only com `TS_USERSPACE=true`,
      `TS_SOCKS5_SERVER=0.0.0.0:1055`, `TS_EXTRA_ARGS=--accept-routes` e volume
      nomeado de estado.
- [ ] 3.3 Passar `PLAYWRIGHT_PROXY_SERVER=${PLAYWRIGHT_PROXY_SERVER:-}` para
      serviços que executam ou podem disparar Playwright.
- [ ] 3.4 Não adicionar TUN, capabilities, privileged ou `network_mode`.
- [ ] 3.5 Validar `docker compose config`, smoke de conectividade quando
      `TS_AUTHKEY` estiver disponível e gerar `/tmp/sirhosp-slice-S3-report.md`.

## 4. Slice S4 - Documentação operacional dev VPN

Escopo: documentar o novo modo de desenvolvimento com Tailscale sidecar,
variáveis necessárias, troubleshooting e limpeza segura.

Limite: até 6 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S4.md`.

- [x] 4.1 Criar `docs/dev-tailscale.md` com documentação completa do fluxo
      Tailscale userspace/SOCKS5.
- [x] 4.2 Atualizar `.env.example` com placeholders de `TS_AUTHKEY` e
      `PLAYWRIGHT_PROXY_SERVER`.
- [x] 4.3 Documentar que o host não entra na VPN e que produção não usa essa
      configuração por padrão.
- [x] 4.4 Documentar troubleshooting: authkey expirada, subnet routes não
      aprovadas, timeout inicial, certificado interno e limpeza do volume.
- [x] 4.5 Atualizar `README.md` com referência cruzada para
      `docs/dev-tailscale.md`.
- [x] 4.6 Executar markdown format/lint e gerar
      `/tmp/sirhosp-slice-S4-report.md`.
- [x] 4.7 Relatório gerado em `/tmp/sirhosp-slice-S4-report.md`.

## 5. Slice S5 - Smoke operacional ponta a ponta sem dados sensíveis

Escopo: consolidar validação operacional segura do modo dev VPN sem realizar
login nem persistir resposta do sistema legado.

Limite: até 6 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S5.md`.

- [x] 5.1 Criar `scripts/smoke-vpn-connectivity.sh` que testa conectividade
      HTTP/HTTPS de `SOURCE_SYSTEM_URL` via proxy SOCKS5, sem credenciais.
- [x] 5.2 Smoke usa `-o /dev/null` no curl e não persiste resposta do sistema
      legado no repositório.
- [x] 5.3 Smoke retorna exit code 2 quando proxy não está disponível (exit 6/7
      do curl), validado em cenário negativo.
- [x] 5.4 Validar em ambiente real que o smoke retorna exit code 0 quando
      Tailscale está autenticado, subnet route está aprovada e o target responde
      HTTP 2xx/3xx.
- [x] 5.5 Quality gates executados e relatório gerado em
      `/tmp/sirhosp-slice-S5-report.md`.
