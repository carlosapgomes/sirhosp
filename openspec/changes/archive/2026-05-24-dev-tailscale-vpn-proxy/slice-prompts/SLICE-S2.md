# Slice S2 - Aplicação do proxy em todos os scripts Playwright operacionais

## Handoff para executor com contexto zero

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/dev-tailscale-vpn-proxy/proposal.md`
4. `openspec/changes/dev-tailscale-vpn-proxy/design.md`
5. `openspec/changes/dev-tailscale-vpn-proxy/tasks.md`
6. Relatório do slice anterior: `/tmp/sirhosp-slice-S1-report.md`

Implemente **somente este slice**.

## Objetivo

Aplicar o helper opcional de proxy criado no S1 em todos os scripts Playwright
operacionais que chamam `chromium.launch`, preservando comportamento atual
quando `PLAYWRIGHT_PROXY_SERVER` não estiver configurada.

O S1 está aprovado. Use como base:

- `automation/source_system/proxy_config.py`
- padrão já aplicado em
  `automation/source_system/current_inpatients/extract_census.py`
- testes em `tests/unit/test_proxy_config.py`

Não reimplemente o helper.

## Escopo permitido

Arquivos sob `automation/source_system/` que chamam `chromium.launch`, mais
testes estritamente necessários.

Atenção: existem débitos preexistentes de lint em alguns arquivos de automação.
Evite reformat amplo. Faça edições mínimas e documente no relatório o que é
preexistente versus o que foi alterado pelo S2.

Busca inicial esperada:

```bash
rg -n "chromium\.launch" automation/source_system
```

## Limite de arquivos

Até 10 arquivos alterados.

Se a busca revelar mais pontos do que o limite permite, pare e reporte bloqueio.

## TDD / caracterização

- Manter os testes do S1 passando.
- Adicionar teste/mocking apenas se necessário para cobrir novo padrão não
  representado pelo S1.
- Usar busca textual como gate para garantir que todos os `chromium.launch` sob
  `automation/source_system/` foram revisados.
- Para cada chamada encontrada, registrar no relatório se foi atualizada neste
  slice, se já estava atualizada pelo S1 ou se foi excluída por justificativa
  explícita.

## Regras técnicas

- Não alterar `SOURCE_SYSTEM_URL`, login, senha ou fluxo funcional.
- Não remover `--ignore-certificate-errors`.
- Não remover `ignore_https_errors=True`.
- Não adicionar fallback para TUN, `network_mode`, capabilities ou host VPN.
- O comportamento sem env deve permanecer igual ao atual.
- Usar o helper `get_playwright_proxy()` existente; não duplicar lógica de env.
- Preservar o padrão de imports existente em cada script. Quando o script usar
  `sys.path.insert` para importar helpers locais, adicionar o import do proxy com
  o menor impacto possível.
- Não fazer reformat amplo para tentar corrigir débitos preexistentes fora do
  escopo.

## Validação

Execute:

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
rg -n "chromium\.launch" automation/source_system
```

Notas de validação:

- O lint oficial pode falhar por débitos preexistentes já conhecidos. Não marque
  o slice como limpo de forma absoluta se isso acontecer; registre exit code e
  evidência.
- O typecheck oficial pode sair com `139` conforme observado no S1. Registre o
  resultado real e não o esconda.
- Além dos gates oficiais, rode ruff direcionado nos arquivos novos ou tocados
  pelo S2 quando possível.
- Se um arquivo inteiro tiver erros antigos, use validação direcionada ou
  `--ignore` apenas para demonstrar que o S2 não introduziu erro novo, e
  documente claramente a razão.
- Documente no relatório quais chamadas de `chromium.launch` foram atualizadas.

## Relatório obrigatório

Gerar `/tmp/sirhosp-slice-S2-report.md` com antes/depois, comandos, exit codes e
pendências.

Pare ao final do slice.
