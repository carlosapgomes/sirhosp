# Modo Dev com VPN Tailscale (sidecar userspace/SOCKS5)

## Visão geral

O SIRHOSP utiliza automações Playwright para extrair dados do sistema legado
hospitalar, que só é acessível pela rede interna do hospital (tailnet Tailscale).

Para desenvolvimento local, um container sidecar `tailscale-app` (modo userspace)
roda um proxy SOCKS5 na porta `1055`. O Playwright é configurado opcionalmente
para usar esse proxy. **O host de desenvolvimento não entra na VPN** — apenas os
containers que executam Playwright têm caminho de rede para o hospital.

## Arquitetura

```text
Host de desenvolvimento
  └─ Docker Compose (compose.yml + compose.dev.yml)
       ├─ web / worker / summary_worker
       │    └─ Playwright chromium.launch(proxy=socks5://tailscale-app:1055)
       │         └─ tailscale-app (userspace, SOCKS5)
       │              └─ Tailscale tailnet
       │                   └─ bastion (subnet router)
       │                        └─ sistema legado hospitalar
       └─ db (PostgreSQL)
```

### Características

- **Proxy opcional:** somente quando `PLAYWRIGHT_PROXY_SERVER` está definida.
- **Sidecar opcional:** ativado via Docker Compose profile `tailscale`.
- **Sem privilégios extras:** o sidecar roda com `TS_USERSPACE=true`, sem
  `/dev/net/tun`, sem `NET_ADMIN`, sem `NET_RAW`, sem `privileged`.
- **Compatível com Docker rootless:** nenhuma capability especial é necessária.
- **Somente tráfego Playwright:** o proxy SOCKS5 só atende conexões que
  explicitamente o usam; o resto da stack dev não entra na VPN.
- **Produção isolada:** `compose.prod.yml` não contém sidecar Tailscale nem a env
  de proxy.

## Pré-requisitos

- Docker 20.10+ com `docker compose`
- Uma authkey Tailscale válida para a tailnet hospitalar
- O bastion da tailnet deve anunciar a subnet do sistema legado
  (`--accept-routes` e subnet route aprovada no admin console)

## Variáveis de ambiente

### `TS_AUTHKEY` (obrigatória para o sidecar)

Authkey para autenticar o container na tailnet Tailscale.

```text
TS_AUTHKEY=tsauthkey-xxxxxxxxxxxx
```

**Regras:**

- Deve estar no `.env` local.
- **NÃO deve ser versionada** — o `.env.example` tem apenas o placeholder.
- Rotacione a authkey se ela for exposta acidentalmente (ex: em logs de
  terminal ou output de `docker compose config`).
- Ao executar `docker compose config` para validação, use `--env-file` com um
  arquivo vazio ou sintético para evitar vazar a authkey real.

### `PLAYWRIGHT_PROXY_SERVER` (opcional)

Configura o Playwright para usar o proxy SOCKS5 do sidecar Tailscale.

```text
PLAYWRIGHT_PROXY_SERVER=socks5://tailscale-app:1055
```

**Regras:**

- Se não estiver definida ou estiver vazia, o Playwright se comporta como antes
  (sem proxy).
- Se definida, todo `chromium.launch(...)` nos scripts de automação recebe
  `proxy={"server": "socks5://tailscale-app:1055"}`.
- **Produção não define essa variável por padrão.**

### `SOURCE_SYSTEM_URL` (inalterada)

Permanece apontando para o IP ou URL do sistema legado hospitalar, sem
alteração. O proxy resolve a conectividade; o destino final é o mesmo.

## Como usar

### 1. Configurar o `.env` local

Adicione ao `.env` (nunca versionado):

```env
TS_AUTHKEY=tsauthkey-xxxxxxxxxxxx
PLAYWRIGHT_PROXY_SERVER=socks5://tailscale-app:1055
```

### 2. Subir a stack dev com Tailscale

```bash
docker compose -f compose.yml -f compose.dev.yml \
  --profile tailscale up -d db web worker summary_worker tailscale-app
```

O container `tailscale-app` (nome: `sirhosp-tailscale`) irá:

1. Autenticar na tailnet usando `TS_AUTHKEY`.
2. Iniciar o proxy SOCKS5 em `0.0.0.0:1055`.
3. Aceitar rotas anunciadas pela tailnet.

### 3. Verificar se o sidecar está pronto

```bash
docker compose -f compose.yml -f compose.dev.yml logs tailscale-app
```

Espere pela mensagem de "Connected" ou "Running". Exemplo de sucesso:

```text
tailscale-app  | 2025/01/15 10:00:00 logtail: dialed "log.tailscale.io/ts2021"
tailscale-app  | 2025/01/15 10:00:01 Program starting: v1.76.6
tailscale-app  | 2025/01/15 10:00:02 Started SOCKS5 proxy on 0.0.0.0:1055
tailscale-app  | 2025/01/15 10:00:02 Connected.
```

### 4. Executar smoke de conectividade (sem login)

Para testar se o proxy está funcional, execute um probe HTTP/HTTPS dentro de
um container da stack:

```bash
docker compose -f compose.yml -f compose.dev.yml exec -T web \
  bash -c 'curl --proxy socks5h://tailscale-app:1055 \
  --connect-timeout 10 --max-time 15 -k -o /dev/null -w "%{http_code}" \
  ${SOURCE_SYSTEM_URL}'
```

Saída esperada em caso de sucesso: código HTTP (`200`, `302`, etc.). Em caso de
falha (timeout, `000`), verifique a seção de Troubleshooting abaixo.

### 5. Rotina normal de desenvolvimento

Com o sidecar rodando, use os comandos normais de extração. O proxy é ativado
automaticamente nos scripts Playwright quando `PLAYWRIGHT_PROXY_SERVER` está
definida:

```bash
docker compose -f compose.yml -f compose.dev.yml exec -T web \
  uv run --no-sync python manage.py extract_census --headless
```

**Não é necessário passar flags extras ou modificar o script** — o helper
central (`get_playwright_proxy()`) resolve a configuração automaticamente.

## Limpeza do estado Tailscale

O estado de autenticação do Tailscale (chaves, certs, configuração de node) é
armazenado em um volume Docker nomeado `sirhosp_tailscale_state`.

Para remover o sidecar e seu estado (útil para trocar de authkey ou limpar um
node órfão):

```bash
# Remove o container e o volume de estado
docker compose -f compose.yml -f compose.dev.yml \
  --profile tailscale down -v

# Subir novamente com uma authkey fresca
docker compose -f compose.yml -f compose.dev.yml \
  --profile tailscale up -d tailscale-app
```

**Atenção:** O `-v` (--volumes) remove **todos** os volumes declarados no
compose, incluindo `sirhosp_db_data`. Se quiser remover apenas o volume
Tailscale, derrube a stack sem `-v`, descubra o nome real do volume com o prefixo
do projeto Compose e remova esse volume explicitamente:

```bash
docker compose -f compose.yml -f compose.dev.yml \
  --profile tailscale down
docker volume ls | grep sirhosp_tailscale_state
docker volume rm <nome_real_do_volume>
```

## Certificados internos

O sistema legado hospitalar usa certificado TLS válido apenas no contexto da
rede interna. O proxy SOCKS5 resolve a **conectividade**, mas não a
**confiança do certificado**.

Os scripts Playwright continuam usando:

- `chromium.launch(args=["--ignore-certificate-errors"])`
- `browser.new_context(ignore_https_errors=True)`

Isso é preservado com ou sem proxy.

## Produção

O ambiente de produção **não** usa sidecar Tailscale por padrão:

- `compose.prod.yml` não define o serviço `tailscale-app`.
- `compose.prod.yml` não define a env `PLAYWRIGHT_PROXY_SERVER`.
- O script helper `get_playwright_proxy()` retorna `None` se a env não existir,
  mantendo o comportamento original.

Em ambientes de produção que precisem de proxy, a configuração pode ser
adicionada caso a caso, mas **não faz parte do setup padrão**.

## Troubleshooting

### Authkey expirada

**Sintoma:** O container `tailscale-app` reinicia em loop e o log mostra:

```text
tailscale-app  | authkey expired or invalid
```

**Causa:** A authkey gerada no admin console Tailscale tem validade configurável
(1 dia, 30 dias, etc.). Se expirou, o sidecar não consegue autenticar.

**Ação:**

1. Gere uma nova authkey no [Tailscale Admin Console](https://login.tailscale.com)
   para a tailnet hospitalar.
2. Atualize `TS_AUTHKEY` no `.env` local.
3. Limpe o volume de estado (veja seção [Limpeza do estado Tailscale]).
4. Suba o sidecar novamente.

### Subnet route não aprovada

**Sintoma:** O sidecar conecta à tailnet (`Connected.`) mas o curl via proxy
retorna timeout ou `Connection refused`.

**Causa:** O bastion que anuncia a subnet do hospital precisa ter a rota
aprovada no admin console Tailscale.

**Ação:**

1. Verifique no [Tailscale Admin Console](https://login.tailscale.com) →
   **Machines** → bastion → **Edit route settings** se a subnet do hospital
   está marcada como **Approved**.
2. Confirme que `TS_EXTRA_ARGS=--accept-routes` está presente nas envs do
   sidecar (já configurado no `compose.dev.yml`).
3. Teste novamente a conectividade.

### Timeout inicial (cold start)

**Sintoma:** O sidecar demora mais de 30 segundos para ficar pronto e os
primeiros comandos Playwright falham com timeout.

**Causa:** O Tailscale precisa estabelecer conexão DERP, autenticar e receber
as rotas anunciadas. Na primeira execução (volume vazio), isso pode levar de 10
a 40 segundos.

**Ação:**

- Aguarde o log mostrar `Connected.` antes de executar comandos Playwright.
- Em scripts que dependem de conectividade imediata, considere adicionar um
  loop de healthcheck contra o proxy:

```bash
for i in $(seq 1 12); do
  if curl --proxy socks5h://127.0.0.1:1055 --connect-timeout 2 \
    -k -s -o /dev/null http://internal-ip; then
    echo "Proxy pronto"
    break
  fi
  echo "Aguardando proxy... ($i)"
  sleep 5
done
```

(Nota: esse loop é executado **dentro** do container que usa o proxy, não no
host.)

### Redirect do sistema legado para hostname interno

**Sintoma:** O Playwright abre a página, mas após o login é redirecionado para
um hostname interno não resolvível (ex: `http://srv-saude/...`), resultando em
erro de DNS.

**Causa:** O sistema legado redireciona para um nome interno que não está no DNS
da tailnet ou não é resolvível pelo proxy SOCKS5.

**Ação:**

- Se o IP do sistema legado é fixo e conhecido, verifique se
  `SOURCE_SYSTEM_URL` está configurada com o IP em vez do hostname, pois o
  acesso por IP elimina dependência de DNS interno.
- Se o redirecionamento ocorre após login, pode ser necessário usar
  `page.route()` no Playwright para interceptar e reescrever a URL.
- Verifique com a equipe de TI do hospital se o hostname interno é anunciado
  via DNS na tailnet.
- Como fallback, registre manualmente o hostname no `/etc/hosts` do container
  (bind mount de um arquivo hosts customizado no `compose.dev.yml`).

### Erro de permissão ao ler `.env`

**Sintoma:** `docker compose config` com `TS_AUTHKEY` não definida quebra o
compose.

**Causa:** O sidecar usa `TS_AUTHKEY=${TS_AUTHKEY:-}` (expansão com fallback
para vazio), portanto não quebra se a env não existir. Se você alterou a sintaxe
para `TS_AUTHKEY=${TS_AUTHKEY:?...}` (required), a ausência da env quebra o
parse do compose.

**Ação:** Use a sintaxe `TS_AUTHKEY=${TS_AUTHKEY:-}`. Se quiser proteção extra,
adicione uma validação explícita em script de entrada do sidecar, não no compose
em si.
