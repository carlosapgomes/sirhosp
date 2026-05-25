# Slice S1 - Configuração Playwright proxy centralizada

## Handoff para executor com contexto zero

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/dev-tailscale-vpn-proxy/proposal.md`
4. `openspec/changes/dev-tailscale-vpn-proxy/design.md`
5. `openspec/changes/dev-tailscale-vpn-proxy/tasks.md`
6. `openspec/changes/dev-tailscale-vpn-proxy/specs/dev-tailscale-vpn-proxy/spec.md`

Implemente **somente este slice**.

## Objetivo

Criar uma configuração central opcional para proxy Playwright baseada em
`PLAYWRIGHT_PROXY_SERVER`, com testes. Não aplique ainda em todos os scripts.

## Escopo permitido

- Criar helper em módulo compartilhado sob `automation/source_system/`.
- Criar/alterar testes unitários para o helper.
- Alterar no máximo um script Playwright representativo para teste de mocking,
  se necessário para demonstrar integração.

## Limite de arquivos

Até 5 arquivos alterados.

## TDD obrigatório

1. RED: teste falhando para env ausente, env vazia e env presente.
2. GREEN: helper retorna:
   - `None` quando `PLAYWRIGHT_PROXY_SERVER` não existe ou está vazia;
   - `{"server": "socks5://tailscale-app:1055"}` quando configurada.
3. Refactor controlado sem ampliar escopo.

## Regras técnicas

- Não ler `.env` diretamente.
- Não alterar `SOURCE_SYSTEM_URL`.
- Não alterar usuário/senha do sistema legado.
- Preservar `--ignore-certificate-errors` e `ignore_https_errors=True` no script
  representativo, se ele for tocado.
- Não adicionar dependência nova.

## Validação

Execute comandos relevantes do projeto, preferencialmente:

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

Se algum comando não puder ser executado, registre motivo e evidência no
relatório.

## Relatório obrigatório

Gerar `/tmp/sirhosp-slice-S1-report.md` com:

- resumo;
- checklist de aceite;
- arquivos alterados;
- antes/depois por arquivo;
- comandos executados e resultados;
- riscos e próximo passo sugerido.

Pare ao final do slice.
