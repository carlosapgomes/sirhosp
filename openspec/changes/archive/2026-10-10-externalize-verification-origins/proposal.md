# Proposal: origens privadas para a verificação do portal

## Why

A entrega `add-dev-browser-verification-suite` funciona e possui evidências
CLI/MCP, mas publicou FQDNs operacionais em código, testes, runbook e skill.
Esses nomes não são credenciais; ainda assim, o operador decidiu não mantê-los
na árvore versionada. Remover somente os exemplos da skill deixaria cópias
no driver e nos testes, ou quebraria o roteiro assistido.

A mudança separa configuração local de documentação pública, preservando a
verificação do sistema real e a proteção contra atuação no ambiente errado.
Para diretoria, qualidade e gestão de prontuários, o valor é manter uma
verificação reproduzível sem expor desnecessariamente endereços de ambientes.

**Status:** aprovada pelo operador para execução via `/change-loop`.

## What Changes

- Ler duas origens HTTPS de `~/.config/sirhosp/verification.env`, fora do Git:
  `SIRHOSP_VERIFY_DEV_ORIGIN` e `SIRHOSP_VERIFY_PROD_ORIGIN`.
- Usar um resolvedor único, sem fallback para hostname compilado, `.env` da
  aplicação, `DJANGO_ALLOWED_HOSTS` ou overrides arbitrários de CLI.
- Bloquear configuração ausente/inválida e origens dev/produção equivalentes
  antes de iniciar serviços, registrar timer, alterar contas ou emitir senhas.
- Informar `origin` validada no JSON de `doctor` e `open`; transmitir a mesma
  origem da abertura ao driver, contexts, jornadas e política de requests.
- Fazer a skill obter o alvo do resultado canônico de `doctor`, sem ler o
  `.env` real da aplicação ou reproduzir um FQDN fixo.
- Manter `close`, recovery, callback e status independentes dessa configuração,
  inclusive quando o arquivo deixa de existir durante uma sessão.
- Remover os literais operacionais da árvore atual, usar origens sintéticas
  nos testes e fornecer template sem valores reais e instruções de bootstrap.
- Provar que CLI e MCP continuam operacionais e que todos os fences herdados
  da entrega anterior permanecem aplicáveis.

### Não objetivos

- Não reescrever histórico, tags, branches ou referências remotas; um novo
  commit não apaga a publicação anterior. Essa operação exige outro aceite.
- Não criar gerenciador de perfis, nova CLI/MCP, servidor, endpoint de
  identidade, cofre de segredos ou novas dependências.
- Não mudar engine, checkout, containers, banco, ownership, FSM ou timer.
- Não alterar autenticação do produto, dados clínicos, deploy, DNS ou TLS.
- Não iniciar workers, ingestão, sumários, exports ou CRUD administrativo.
- Não executar a implementação ou criar o arquivo privado nesta proposta.
- Não reeditar os aceites ou artefatos históricos da change anterior.

## Capabilities

### New Capabilities

- `verification-origin-configuration`: origens locais privadas, resolução
  canônica para CLI/MCP, bloqueio antes de efeitos e cleanup independente.

### Modified Capabilities

Nenhuma spec consolidada será modificada nesta proposta. As capacidades
`dev-verification-sessions` e `dev-browser-verification` ainda estão nos
artifacts da change anterior, não em `openspec/specs/`. Seus contratos são
herdados por referência; a nova capacidade acrescenta a configuração privada
sem duplicar as regras do ciclo e das jornadas.

## Impact

- Implementação esperada: resolvedor em `automation/verification/origins.py`,
  controlador, passagem explícita de origem no browser e respectivos testes.
- Documentação: runbook, skill/mapas afetados e template proposto em
  `docs/examples/verification.env.example`, com valores vazios.
- Compatibilidade: flags da CLI e campos existentes são preservados;
  `origin` é metadado aditivo. A ausência do novo arquivo passa a bloquear
  doctor/open/run, mas nunca deve impedir revogação ou consulta de estado.
- Nenhuma migration, alteração clínica, scraping ou nova dependência;
  `python-dotenv` já está disponível. O arquivo real não é criado pelo loader.
- Um único slice vertical mantém CLI, política de requests e roteiro MCP
  coerentes no mesmo estado aceito. Gate final separado confirma a entrega.

### Risco e mitigação

Classificação manual ESAA: **CRÍTICO** pelos critérios de segurança de acesso,
proteção de metadados, contrato JSON consumido pela automação e alteração de
mais de cinco arquivos. Não implica ampliação arquitetural ou clínica.

Uma configuração do operador continua sendo uma declaração confiável, não
prova isolada de que um hostname aponta ao dev. Preservar fences locais,
confirmação do dataset, validação TLS, recusa da produção configurada,
allowlist por origem/método/caminho e isolamento. Produção nunca será
consultada, nem para validar sua configuração.

Mitigar regressões com RED/GREEN para configuração e revogação, uma prova
CLI/MCP autorizada, review independente e gates oficiais no estado final.
Não reduzir segurança para tornar o alvo configurável.
