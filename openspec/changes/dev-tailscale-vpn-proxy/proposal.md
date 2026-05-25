# Change Proposal: dev-tailscale-vpn-proxy

## Why

O ambiente de desenvolvimento precisa executar automações Playwright contra o
sistema legado do hospital, acessível apenas pela rede interna hospitalar. O host
de desenvolvimento não deve entrar na VPN Tailscale por política operacional: o
acesso à VPN deve ficar restrito aos containers da aplicação.

Foi realizado um spike temporário em diretório ignorado pelo Git
(`debug/tailscale-probe/`) usando `tailscale/tailscale` em modo userspace com
proxy SOCKS5. O probe comprovou que um container consegue acessar
`SOURCE_SYSTEM_URL` pela VPN Tailscale sem `/dev/net/tun`, sem `NET_ADMIN`, sem
`NET_RAW` e sem conectar o host à tailnet. Esse desenho é compatível com Docker
rootless e atende ao escopo real: somente o Playwright precisa acessar HTTP/HTTPS
por IP do sistema legado.

## What Changes

- Adicionar sidecar Tailscale dev-only ao `compose.dev.yml`, usando userspace
  networking e proxy SOCKS5 interno.
- Manter `SOURCE_SYSTEM_URL` inalterado e adicionar configuração opcional de
  proxy para Playwright via variável de ambiente.
- Alterar os scripts Playwright para usarem proxy somente quando a variável
  estiver presente.
- Preservar `--ignore-certificate-errors` e `ignore_https_errors=True`, pois o
  sistema legado usa certificado válido apenas no contexto da rede interna.
- Documentar o novo modo de desenvolvimento, incluindo `.env`, execução,
  troubleshooting e limpeza do volume de estado Tailscale.

## Non-Goals

- Não conectar o host de desenvolvimento à VPN Tailscale.
- Não usar TUN, `network_mode: service:*`, `privileged`, `NET_ADMIN` ou `NET_RAW`.
- Não alterar `SOURCE_SYSTEM_URL`, credenciais do sistema legado ou fluxo de
  login.
- Não modificar `compose.prod.yml` nem exigir Tailscale em produção.
- Não introduzir Celery, Redis ou outro componente de coordenação.
- Não versionar authkeys, credenciais, IPs sensíveis adicionais ou respostas do
  sistema legado.

## Capabilities

### New Capabilities

- `dev-tailscale-vpn-proxy`: execução dev containerizada com acesso VPN restrito
  ao tráfego Playwright via sidecar Tailscale userspace/SOCKS5.

### Modified Capabilities

- `containerized-runtime`: passa a suportar conectividade dev ao sistema legado
  por proxy interno sem elevar privilégios do Docker rootless.
- `playwright-source-system-connectors`: passam a aceitar configuração opcional
  de proxy sem alterar URL, credenciais ou contratos funcionais.

## Impact

- Reduz risco operacional ao impedir que o host entre na VPN hospitalar.
- Mantém compatibilidade com Docker rootless.
- Isola o acesso hospitalar ao tráfego explicitamente enviado pelo Playwright.
- Simplifica alternância dev/prod: produção permanece sem proxy quando a env não
  estiver definida.
