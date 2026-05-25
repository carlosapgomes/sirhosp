# Slice S4 - Documentação operacional dev VPN

## Handoff para executor com contexto zero

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/dev-tailscale-vpn-proxy/proposal.md`
4. `openspec/changes/dev-tailscale-vpn-proxy/design.md`
5. `openspec/changes/dev-tailscale-vpn-proxy/tasks.md`
6. Relatórios anteriores em `/tmp/sirhosp-slice-S1-report.md`,
   `/tmp/sirhosp-slice-S2-report.md` e `/tmp/sirhosp-slice-S3-report.md`

Implemente **somente este slice**.

## Objetivo

Documentar o modo de desenvolvimento com Tailscale sidecar userspace/SOCKS5.

## Escopo permitido

- README ou documentação operacional existente sobre Compose/dev.
- `.env.example` ou arquivo de exemplo equivalente, se existir.
- OpenSpec tasks somente para marcar progresso deste slice, se aplicável.

## Limite de arquivos

Até 6 arquivos alterados.

## Conteúdo obrigatório

A documentação deve explicar:

- o host não entra na VPN;
- somente tráfego Playwright configurado com proxy acessa a rede hospitalar;
- `TS_AUTHKEY` deve estar no `.env` local e não deve ser versionada;
- `PLAYWRIGHT_PROXY_SERVER=socks5://tailscale-app:1055` habilita proxy em dev;
- `SOURCE_SYSTEM_URL` permanece apontando para o IP/URL do sistema legado;
- produção não usa essa configuração por padrão;
- certificados internos continuam tratados pelo Playwright com ignore HTTPS;
- como limpar o volume Tailscale com `docker compose down -v`;
- troubleshooting para authkey expirada, subnet route não aprovada, timeout
  inicial e redirect para hostname interno.

## Regras

- Não documentar credenciais reais.
- Não incluir IPs internos adicionais além de placeholders.
- Não usar `<!-- markdownlint-disable ... -->`.

## Validação

Execute:

```bash
./scripts/markdown-format.sh
./scripts/markdown-lint.sh
./scripts/test-in-container.sh check
```

## Relatório obrigatório

Gerar `/tmp/sirhosp-slice-S4-report.md`.

Pare ao final do slice.
