# Slice S5 - Smoke operacional ponta a ponta sem dados sensíveis

## Handoff para executor com contexto zero

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/dev-tailscale-vpn-proxy/proposal.md`
4. `openspec/changes/dev-tailscale-vpn-proxy/design.md`
5. `openspec/changes/dev-tailscale-vpn-proxy/tasks.md`
6. Relatórios anteriores `/tmp/sirhosp-slice-S1-report.md` até
   `/tmp/sirhosp-slice-S4-report.md`

Implemente **somente este slice**.

## Objetivo

Consolidar uma validação operacional segura para o modo dev VPN, testando apenas
conectividade HTTP/HTTPS via proxy, sem login e sem persistir resposta real do
sistema legado.

## Escopo permitido

- Script de smoke em `scripts/` ou documentação de comando reproduzível.
- Pequenos ajustes em documentação já criada no S4.
- OpenSpec tasks somente para marcar progresso deste slice, se aplicável.

## Limite de arquivos

Até 6 arquivos alterados.

## Requisitos do smoke

- Usar `SOURCE_SYSTEM_URL` do ambiente.
- Usar proxy `socks5h://tailscale-app:1055` ou valor derivado de
  `PLAYWRIGHT_PROXY_SERVER`.
- Usar modo equivalente a `--insecure` para validar certificado interno sem
  falhar por CA.
- Não usar `SOURCE_SYSTEM_USERNAME` nem `SOURCE_SYSTEM_PASSWORD`.
- Não gravar corpo de resposta no repositório.
- Retornar exit code diferente de zero quando o proxy não estiver disponível.
- Retornar exit code zero quando Tailscale estiver autenticado, rota aprovada e o
  sistema legado responder.

## Regras

- Não versionar dados reais ou resposta HTML do sistema legado.
- Não exibir credenciais.
- Não exigir host Tailscale.
- Não exigir TUN/capabilities.

## Validação

Execute, quando houver ambiente disponível:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
```

Execute também o smoke em cenário negativo e, se `TS_AUTHKEY`/VPN estiverem
disponíveis, cenário positivo. Registre comandos e exit codes.

## Relatório obrigatório

Gerar `/tmp/sirhosp-slice-S5-report.md`.

Pare ao final do slice.
