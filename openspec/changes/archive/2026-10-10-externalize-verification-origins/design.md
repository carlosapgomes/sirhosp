# Design: origem canônica privada sem dependência no cleanup

## Context

Ver [proposal.md](proposal.md) para a motivação e
[spec da capacidade](specs/verification-origin-configuration/spec.md) para os
requisitos. Planejamento baseado em `35a0e6a`, posterior aos commits aceitos
S1 `1ec13ac`, S2 `87e85ee` e S3 `36ed7ee`.

Constatações no código, sem ler o `.env` real:

- `automation/verification/browser.py` define `DEV_ORIGIN` e a usa em defaults
  de `RequestPolicy`, `SmokeDriver` e `PlaywrightBrowser`.
- `_default_driver_factory` usa essa constante; `cmd_run` abre a sessão antes
  de construir o driver. A validação nova não pode ser adiada até esse ponto.
- `DoctorReport` e `OpenCredentials` não expõem a origem; MCP depende hoje de
  URLs escritas na skill/mapas.
- `_resolve_target` valida o alvo local/Docker/banco, não resolve uma URL.
  Não existe um cadastro de origens a simplesmente reaproveitar.
- `close`, recovery, callback e status resolvem identidade/estado locais.
  O callback one-shot não pode depender do ambiente do terminal de abertura.
- `python-dotenv` já consta das dependências. `config/settings.py` carrega o
  `.env` da aplicação, mas isso não configura automaticamente esta CLI.
- A `.gitignore` ignora `.env`; o arquivo escolhido fica fora do checkout e
  não precisa de regra nova. A política de changes ativos ignorados permanece.
- Os dois FQDNs aparecem em oito arquivos tracked: driver, runbook, dois
  testes e quatro documentos da skill/mapa. Não reproduzir os valores aqui.

A change anterior continua preservada e não será sincronizada/arquivada por
este planejamento. Suas specs ainda não existem em `openspec/specs/`;
esta change adiciona uma capacidade própria e referencia os contratos herdados.

## Goals / Non-Goals

**Goals:** origem explicitamente configurada e imutável por operação; CLI e
MCP consistentes; ausência de URL operacional compilada; bootstrap manual
simples; regressão de cleanup impossível por falta da configuração.

**Non-Goals:** resolver identidade remota por um novo endpoint, suportar
múltiplos perfis/paths de configuração, ampliar rotas permitidas, mudar
estado de sessão ou gerenciar histórico Git.

Nenhuma alteração no domínio clínico, scraping, schema ou workers. A operação
continua sendo o mesmo monólito/CLI local, com o mesmo browser e lifecycle.

## Decisions

### D1 — Um arquivo dedicado fora do checkout

Caminho único: `Path.home() / ".config/sirhosp/verification.env"`.
Chaves obrigatórias:

- `SIRHOSP_VERIFY_DEV_ORIGIN`;
- `SIRHOSP_VERIFY_PROD_ORIGIN`.

Usar o parser dotenv existente sem interpolação. Ler as duas chaves, sem
atualizar `os.environ` globalmente. Não aceitar overrides de processo,
`--base-url`, profiles, arquivo de configuração arbitrário ou fallback nos
hosts Django. Resolver as origens somente quando doctor/open/run precisarem.

O loader não cria diretório/arquivo nem recebe valores reais nos documentos
versionados. O operador cria o arquivo privado após aprovação e autorização
operacional, com recomendação de permissão `0600`.

Alternativas: o `.env` da aplicação mistura dados operacionais com senhas e
pode ser copiado para deploy; `.env.verification` no checkout cria risco de
commit acidental; JSON/profile manager acrescentaria outro padrão sem ganho.
O dotenv dedicado evita esses problemas sem nova dependência.

### D2 — Validar somente dados, sem consultar produção

Um resolvedor coeso em `automation/verification/origins.py` retorna um par
imutável de origens validadas. Expor uma função de leitura e o mínimo de
validação necessário; não criar framework de configuração.

Validar ausência, acessibilidade, chaves/valores obrigatórios e URL absoluta
HTTPS. Rejeitar host/porta inválidos, userinfo, query, fragmento e path além
de vazio ou `/`. Canonizar scheme, host e porta efetiva; remover barra final
e tratar porta 443 explícita como equivalente à omitida. Dev equivalente à
produção é BLOCKED. Preservar portas não default quando válidas e distintas.

Nenhuma resolução DNS ou request de validação para produção. Configuração
é uma declaração confiável do operador, não prova de ligação do HTTPS com
a instância local. Não deduzir dev de prefixo de hostname, DEBUG ou URL válida.
As verificações locais e a prova de login real continuam necessárias.

Erros mostram chave/motivo, não o conteúdo inválido: até um arquivo destinado
a URLs pode receber por engano userinfo ou query com segredo.

### D3 — Resolver antes dos efeitos e propagar uma fotografia da abertura

Doctor valida a configuração antes de seu preflight e retorna `origin` quando
PASS. Open valida antes de qualquer início de serviço, checkpoint, timer,
prepare/open de contas ou emissão de senha. Uma falha nessa validação mantém
a abertura sem efeitos.

Open devolve `origin` junto com os campos atuais de `OpenCredentials`.
`cmd_run` obtém a origem da própria abertura, não a reinterpreta depois nem
recarrega o arquivo por caso/context. Passa-a explicitamente à factory,
`PlaywrightBrowser`, `SmokeDriver`, `RequestPolicy` e jornadas. A metadata
usada pelo MCP e o valor usado pelo runner vêm do mesmo resolvedor.

Remover `DEV_ORIGIN` operacional e defaults de origem dos componentes
runtime. Testes e construtores internos passam origem sintética explicitamente;
a camada de browser continua podendo aceitar HTTP loopback para os testes
nativos existentes, sem permitir HTTP na configuração real da CLI.

A probe de scheme inseguro em `case_policy_allowlist` deriva da origem do
contexto, em vez de conter outro FQDN fixo. Manter scheme/host/porta,
CDNs versionados, métodos/paths, redirects, popups, SW/WS, observações,
sanitização e aborto fatal já aceitos.

Os consumidores internos e factories de teste são atualizados para a origem
explícita. Campos existentes e flags públicas não são removidos; o contrato
JSON ganha somente `origin` nas respostas pertinentes.

### D4 — Cleanup não lê essa configuração

Não exigir origens em `Target`, records/FSM, parâmetros do callback ou
management commands de revogação. Não ler o arquivo durante import.

`cmd_close`, recovery, `cmd_callback` e `cmd_status` permanecem sem chamada
obrigatória ao loader. A ausência/invalidez deve ser coberta pelos caminhos
reais desses comandos em testes, não por mock que desabilite o loader.
Se o arquivo mudar durante run, a origem capturada permanece e o finally
continua fechando browser e sessão com as verificações locais existentes.

Não confundir independência de URL com bypass de fingerprint, engine,
volume, ownership ou revogação. Esses requisitos continuam obrigatórios.

### D5 — Skill consome metadata, não configura o ambiente

Atualizar SKILL.md, índice e mapas afetados para usar `origin` retornada por
`doctor --target dev --confirm-fictitious`, com placeholder `<origin>` nos
exemplos versionados e caminhos concretos separados.

Antes de navegar, confirmar `open.origin == doctor.origin`. Se houver mudança
entre os comandos, não dirigir a origem nova silenciosamente: fechar a sessão
owned pelo mecanismo canônico e retornar BLOCKED para revalidar com o operador.
Não mandar o LLM ler `.env` da aplicação ou preencher URLs por adivinhação.

Manter isolamento MCP, TLS normal, rotas permitidas, dados fictícios,
evidências sanitizadas e cobertura honesta. A skill continua não-firewall;
produção e origins externas permanecem fora do roteiro.

### D6 — Bootstrap e remoção atual, sem mecanismo de segredos novo

Adicionar `docs/examples/verification.env.example` com as duas chaves vazias.
O runbook descreve criação manual em `~/.config/sirhosp/`, permissão `0600`,
preenchimento privado e doctor. Copiar o template vazio não pode habilitar
abertura. Não inserir valores reais em exemplos, defaults ou testes.

Substituir URLs de fixtures por domínios `.invalid`/loopback. Os testes de
configuração usam valores sintéticos, sem depender do arquivo pessoal ou dev.
Inventariar os nomes a remover a partir da baseline já versionada, sem gravá-los
em uma nova blacklist do teste. Scan final inclui tracked e candidatos novos;
mostrar somente paths/contagens, não valores. CDNs e hosts públicos de terceiros
necessários ao contrato não são alvos desta remoção.

Não editar a change anterior nem apagar relatórios para fingir que a exposição
não ocorreu. Evidências runtime podem ficar fora do Git conforme o contrato;
histórico publicado continua contendo versões antigas e exige outro aceite.

### D7 — Um único slice vertical, não parser isolado

O slice ORIG-001 entrega loader, integração CLI/browser, instruções MCP,
template, remoção dos literais e provas. Separar backend e documentação
permitiria um estado em que a CLI segue configuração nova e a skill aponta
ao alvo antigo. O tamanho permanece proporcional: duas chaves, propagação
explícita e mudanças localizadas nos consumidores existentes.

A decomposição segue `openspec-vertical-change-writer`. Não impõe número
arbitrário de arquivos, não escolhe agentes/modelos e não controla execução.
Gate final e review seguem `AGENTS.md`, após aceite e autorização operacional.

### D8 — Verification sobre as superfícies afetadas

RED/GREEN: resolução pura, campos JSON, configuração inválida sem efeitos,
propagação integral e close/recovery/callback/status sem perfil válido.
Regressões nativas de transporte/aborto de S2 continuam sem skips.

Verification autorizada: autenticação CLI e uma jornada smoke com expectativas
fictícias conhecidas; autenticação MCP usando metadata `origin`; revogação e
recursos owned comprovados. A regra doctor/open divergentes recebe dry-run
com respostas sintéticas e inspeção independente do roteiro; registrar esse
limite, sem chamar dry-run de prova de revogação real. A revogação real é
comprovada na jornada positiva. Não reconstruir infraestrutura TLS local ou
outra suíte de browser para esta configuração; reutilizar superfícies existentes.

Teste de cleanup com configuração ausente deve usar arquivo temporário próprio
ou remoção simulada no seam da configuração. Não renomear/apagar o perfil real
com uma sessão ativa para fabricar prova. Demonstrar o caminho canônico de
revogação, não resolver tudo com um close externo ao driver.

## Risks / Trade-offs

- [Configuração privada incorreta] → validação estrita, comparação de origens,
  inspeção pelo operador e fences locais. Não prometer identidade remota a
  partir de nome/URL; não abrir endpoint novo de fingerprint.
- [Configuração obrigatória muda o bootstrap] → template vazio, instrução de
  migração e BLOCKED acionável; nenhuma senha é emitida antes de configurar.
- [Callback sem ambiente do shell] → cleanup sem loader; nenhum import lê
  perfil obrigatório; regressões reais de command paths com perfil ausente.
- [Drift CLI/MCP] → metadata única, comparação doctor/open e um slice atômico.
- [Contrato JSON aditivo] → manter campos anteriores, testar consumidores e
  atualizar a skill; escalar consumidor que exija compatibilidade não prevista.
- [Remoção parcial] → scan dos arquivos atuais/candidatos e fixtures sintéticas;
  não codificar os nomes privados no próprio mecanismo de verificação.
- [Histórico continua público] → declarar limitação; sem force-push ou purga
  por este contrato, nem promessa de desfazer descoberta em DNS/certificados.

## Migration Plan

1. Após aprovação, registrar baseline e RED; implementar somente ORIG-001.
2. O operador prepara o arquivo privado, sem colocar valores reais no Git.
   Essa preparação e as provas dev/MCP exigem autorização operacional explícita.
3. Executar focused tests, review e verification do slice; preservar árvore
   concorrente e atualizar tasks somente após aceite.
4. Executar gate completo, integração e validações explícitas no estado final;
   fazer commit/publicação somente conforme autorização do controller/operador.
5. Se for necessária purga do histórico, planejar outra operação com o dono
   do remoto e colaboradores, sem assumir que já foi realizada.

Rollback: revogar qualquer sessão owned pelos comandos canônicos primeiro,
comprovar cleanup, e somente depois reverter os commits desta mudança se isso
for explicitamente autorizado. O rollback pode reintroduzir FQDNs na árvore;
registrar essa consequência e não realizá-lo silenciosamente. Não apagar
volumes, alterar DNS, iniciar workers ou editar records de sessão à mão.
