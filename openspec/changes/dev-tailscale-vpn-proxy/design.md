# Design: dev-tailscale-vpn-proxy

## Context

O SIRHOSP executa automações Playwright para extrair dados do sistema legado do
hospital. No ambiente atual, `SOURCE_SYSTEM_URL` aponta diretamente para um
endereço HTTP/HTTPS interno por IP. Não há dependência de DNS interno para esse
acesso, mas o endpoint só é alcançável pela rede hospitalar.

Existe um bastion conectado à tailnet Tailscale que anuncia a subnet hospitalar.
A authkey para o node dev da aplicação já é fornecida via `.env` como
`TS_AUTHKEY`. O host de desenvolvimento não deve entrar na tailnet; apenas os
containers devem ter caminho de rede para o hospital.

Um spike temporário validou o desenho com `tailscale/tailscale:latest`,
`TS_USERSPACE=true`, `TS_SOCKS5_SERVER=0.0.0.0:1055` e `TS_EXTRA_ARGS=--accept-routes`.
O teste acessou `SOURCE_SYSTEM_URL` via `curl --proxy socks5h://tailscale-app:1055
--insecure`, comprovando conectividade em Docker rootless.

## Goals

- Permitir que Playwright acesse o sistema legado via VPN Tailscale em dev.
- Manter o host fora da VPN.
- Evitar permissões incompatíveis com Docker rootless.
- Manter `SOURCE_SYSTEM_URL` igual entre ambientes.
- Tornar o proxy opcional e controlado por env.
- Documentar operação e troubleshooting.

## Non-Goals

- Acesso transparente de todos os containers à subnet hospitalar.
- Reescrever conectores Playwright.
- Usar DNS interno da rede hospitalar.
- Persistir dados reais ou respostas do sistema legado.
- Alterar a configuração de produção.

## Decisions

### 1) Tailscale userspace com SOCKS5 em vez de TUN

**Decisão:** usar `tailscale/tailscale` em modo userspace com proxy SOCKS5.

Motivos:

- funciona com Docker rootless;
- não requer `/dev/net/tun`;
- não requer `NET_ADMIN`, `NET_RAW` ou `privileged`;
- limita o acesso hospitalar ao tráfego que explicitamente usa o proxy;
- atende ao escopo real, pois o Playwright acessa HTTP/HTTPS por IP.

### 2) Sem `network_mode: service:tailscale-app`

**Decisão:** manter `web` e `worker` na rede Compose normal e configurar apenas o
Playwright para usar proxy quando necessário.

Motivos:

- evita mover portas do `web` para o sidecar;
- reduz impacto no acesso ao PostgreSQL;
- preserva isolamento e previsibilidade da stack dev;
- evita que todo tráfego do container passe implicitamente pela VPN.

### 3) Proxy Playwright opcional por env

**Decisão:** adicionar variável opcional, por exemplo
`PLAYWRIGHT_PROXY_SERVER=socks5://tailscale-app:1055`, consumida por helper
central.

Regras:

- se a env não existir ou estiver vazia, o Playwright se comporta como hoje;
- se existir, `chromium.launch(...)` recebe `proxy={"server": value}`;
- `SOURCE_SYSTEM_URL`, usuário e senha permanecem inalterados;
- produção não define essa env por padrão.

### 4) Certificados continuam ignorados no contexto Playwright

**Decisão:** preservar `--ignore-certificate-errors` no browser e
`ignore_https_errors=True` no context.

Motivo: o sistema legado usa certificado que só é confiável no contexto da rede
interna hospitalar. O proxy resolve conectividade, não confiança de certificado.

### 5) Estado Tailscale em volume nomeado

**Decisão:** persistir estado em volume Docker nomeado, não em bind mount no
repositório.

Motivos:

- evita arquivos sensíveis no workspace;
- simplifica limpeza com `docker compose down -v`;
- reduz risco de commit acidental.

## Proposed dev runtime

```text
web/worker container
  └─ Playwright chromium.launch(proxy=socks5://tailscale-app:1055)
       └─ tailscale-app userspace SOCKS5
            └─ Tailscale tailnet
                 └─ bastion subnet router
                      └─ sistema legado hospitalar
```

## Validation Strategy

- Testes unitários para o helper de proxy:
  - env ausente retorna `None`;
  - env vazia retorna `None`;
  - env presente retorna `{"server": ...}`.
- Testes de caracterização/mocking para pelo menos um script Playwright garantir
  que `chromium.launch` recebe proxy quando configurado.
- Smoke operacional dev:
  - subir stack dev com `TS_AUTHKEY` e proxy habilitado;
  - confirmar que sidecar chega a `Running`;
  - executar probe HTTP/HTTPS sem login contra `SOURCE_SYSTEM_URL` ou comando
    equivalente documentado;
  - manter gates oficiais do projeto para check, unit, lint e typecheck.

## Risks / Trade-offs

- O proxy SOCKS5 só cobre tráfego explicitamente configurado; chamadas HTTP fora
  do Playwright não passarão pela VPN automaticamente.
- Redirects do sistema legado para hostnames internos podem exigir DNS via proxy
  ou ajuste futuro; o cenário atual usa IP e o spike comprovou resposta.
- Authkeys podem expirar ou acumular nodes na tailnet; runbook deve documentar
  limpeza de volume e rotação.
- Alguns scripts Playwright podem ficar fora da configuração se não forem
  atualizados; a busca por `chromium.launch` deve fazer parte do gate do slice.

## Anti-drift guardrails

- Implementar um slice por vez.
- Não ler nem registrar credenciais do `.env`.
- Não versionar outputs do sistema legado.
- Se a alteração exigir TUN/capabilities, parar e reportar bloqueio.
- Gerar relatório obrigatório por slice em `/tmp/sirhosp-slice-<ID>-report.md`.
