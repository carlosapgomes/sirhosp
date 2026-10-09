# Design: verificação complementar com credenciais efêmeras

## Context

Ver motivação em [proposal.md](proposal.md). O portal usa Django Templates,
HTMX e Bootstrap. Playwright Python já existe no projeto, mas os conectores
de ingestão não são um harness de verificação e não serão reutilizados.

O dev observado usa o Docker de `dev`, volume
`sirhosp_sirhosp_db_data`, web no host 8001 e banco interno `db:5432`.
O Docker de `apps` e seu edge são independentes e ficam fora do controlador.
O domínio autorizado é `https://prismadev.projetoshgrs.com`; o domínio
`prisma.projetoshgrs.com` é produção e deve ser recusado.

`/health/` não verifica schema nem identidade do dataset. Há GET que enfileira
demografia em `apps/ingestion/views.py` e exportação estatística que grava
auditoria. Portanto workers parados e restrição a GET não bastam.

## Goals / Non-Goals

**Goals:** uma sessão local simples, revogável e verificável; provas reais de
UI/JavaScript; catálogo extensível; ausência de credenciais permanentes.

**Non-Goals:** mudar autenticação do portal, dados clínicos, migrations,
conectores, deployment compartilhado ou os gates oficiais existentes.
Ações que escrevem dados de negócio ficam para outro change.

## Decisions

### D1 — Um controlador local e contas reservadas

Interface futura: `uv run python scripts/verify_portal.py` com operações
`doctor`, `open`, `status`, `close` e, em S2, `run`.
Não criar CLI genérica de Docker nem servidor MCP próprio.

O controlador valida repo, engine/container/volume de dev e chama um management
command novo de `apps/accounts`. O serviço Django altera apenas
`verify_user` e `verify_admin`. Nunca aceitar username arbitrário.
Identificar ownership com e-mails reservados
`verify_user@verification.invalid` e `verify_admin@verification.invalid`:
criar contas ausentes; recusar colisão com conta existente sem esse marcador.
O marcador não é uma fronteira contra administrador malicioso; evita adoção
acidental de contas humanas neste ambiente controlado.

Comum: sem staff/superuser; admin: staff/superuser somente no dev.
Criar/usar `UserProfile` com `must_change_password=False` para o fluxo normal.
Não reutilizar `create_portal_user --reset-password`, que força troca de senha.
Não alterar essa funcionalidade do produto. Primeiro acesso fica fora do MVP.

### D2 — Preflight separado de reparo e identidade explícita

Antes de emitir senha: confirmar destino autorizado, caminho do checkout,
socket do Docker do operador, labels de projeto/serviço, volume esperado,
conexão do web ao IP do db daquele engine, schema com
`migrate --check --noinput`, DEBUG falso e workers parados.
O operador confirma que o dataset é fictício. `DEBUG` não identifica dev.

Usar valores de configuração não secretos e validação das informações locais,
sem imprimir `docker inspect` completo, ambiente ou dados clínicos.
Não mudar DNS/túnel nem consultar o domínio de produção.
Preflight inválido gera BLOCKED antes de escrever contas. Close/recovery
validam identidade e ownership, mas não exigem a prontidão de abertura:
DEBUG verdadeiro, worker ativo ou outra migration pendente não podem impedir
a revogação se o banco de autenticação correto continuar acessível.

`open --start` pode subir somente db/web, explicitamente pelo Compose dev.
Um schema pendente bloqueia a abertura: nunca aplicar migrations automaticamente.
Ao subir o web, preservar DEBUG falso sem editar `.env`.
Como a publicação HTTPS depende do edge existente, login real com a senha
recém-gerada deve confirmar o caminho antes de dirigir páginas autenticadas;
não inferir prontidão autenticada somente de HTTP 200.

### D3 — Abertura e fechamento reversíveis

Gerar senhas com `secrets.token_urlsafe(32)`, aplicar via `set_password()`,
ativar as duas contas em transação e emitir credenciais apenas na abertura
assistida. O modo `run` consome a mesma resposta internamente, sem imprimir
senhas. A execução assistida aceita a presença efêmera no histórico do LLM;
nenhum relatório, arquivo de estado ou argumento de processo contém a senha.

Fechamento: interromper ações do driver, executar
`set_unusable_password()` + `is_active=False` nas contas owned, verificar
revogação, fechar apenas recursos do browser criados pela execução e,
com opção explícita `--stop`, parar web/db. Nunca excluir contas humanas,
sessões globais, dados de negócio ou volumes.

Revogação é verificada no próximo request, como faz a autenticação Django;
não alegar que uma requisição já em andamento foi desautorizada retroativamente.
Outras contas e páginas públicas permanecem acessíveis se o web não for parado.

### D4 — Uma sessão ativa e recovery mínimo

Manter registro não secreto em
`~/.local/state/sirhosp-verification/`, fora do checkout: run-id, estado,
destino, IDs das contas, horário limite e unidade de timer. Nenhuma senha,
cookie ou storage-state. Usar lock local e IDs de execução para evitar
abertura concorrente e callback antigo revogando uma sessão nova.

Estados: CLOSED → OPENING → ACTIVE → CLOSING → CLOSED.
Falha de limpeza permanece identificável e exige recovery; não anunciar CLOSED
se a revogação falhou. `close` repetido não reativa nada; recovery só toca as
contas owned e o destino confirmado.

Programar, antes de entregar credenciais, um timer one-shot do systemd do
usuário para `close` com o run-id, com limite padrão de 60 minutos.
Se o timer não puder ser registrado, revogar a abertura e retornar BLOCKED.
O controlador não instala unidades permanentes nem altera deploy/systemd.

No scripted run, usar também `try/finally` e timeout do driver. O timer cobre
interrupção do agente/processo com user manager ativo, mas não é garantia
persistente após reboot. Registro durável permite detectar sessão órfã;
novo `open` precisa encerrar/revogar a órfã antes de emitir outras senhas.
Após queda/reboot, orientar `close`/recovery antes de reabrir o portal;
não afirmar inacessibilidade durante reinício automático do Docker.

### D5 — Driver real, não novo teste de view

Driver isolado em `automation/verification/`, sem importar conectores.
Usar contexto novo por papel, login pelo formulário, TLS normal e logout pelo
botão; nada de `force_login`, mock de auth ou setters internos na prova real.

Rotas iniciais de negócio: `/painel/`, `/censo/`, `/perfil/` e
`/atualizacao-censo/`; landing/login/logout e assets completam a allowlist.
Proibir exportações, `/ingestao/`, submissão de senha, CRUD e sumários.
Somente POST de login/logout é permitido no modo sem alterações de negócio.
Assets externos conhecidos: caminhos versionados de Bootstrap, Bootstrap Icons
e TomSelect em cdn.jsdelivr.net e HTMX em unpkg.com; não liberar esses hosts
inteiros para chamadas arbitrárias.

No Playwright, aplicar allowlist por origem, método e caminho, inclusive
redirects/popups. Falhar por erro de página, asset obrigatório ausente,
HTTP inesperado ou efeito de negócio detectado. Login/session/last_login e
estado das contas de teste são as únicas escritas esperadas.
Comparar metadados de filas antes/depois; nunca apagar jobs para mascarar falha.

### D6 — Escopo de provas e dados esperados

| Caso | Prova complementar |
| --- | --- |
| Login/logout, ambos os papéis | Formulário, CSRF HTTPS, painel autenticado, logout e acesso protegido |
| Navegação/perfil | Links reais, menu ativo e identidade da conta de teste |
| Permissões | Item Estatísticas ausente no comum e presente no admin, sem exportar |
| Censo | TomSelect inicializado, filtros pela UI e estado esperado de resultados |
| Topbar | Duas chamadas periódicas reais, um badge após swaps e ausência de login inserido |
| Mobile | Menu abre/fecha por clique e conteúdo acessível, sem overflow global indevido |

Desktop: 1440×900; mobile: 390×844. Para HTMX, aguardar o período real de 60s;
não substituir a prova por atribuição manual de DOM. Foto antiga é um estado
legítimo com workers parados: não executar ingestão para tornar o badge verde.

Filtro positivo exige descritor explícito de registro fictício e resultado
esperado, informado pelo operador fora do repositório. Não inferir a resposta
esperada da própria tabela filtrada, copiar dados reais ou criar fixtures no
banco automaticamente. Se faltar esse descritor/registro, o caso é BLOCKED.
Isso não impede provar autenticação e shell, mas impede declarar a suíte
inteira aprovada.

Usar labels reais: Usuário, Senha, Entrar, Censo, Perfil, Sair, Nome ou Registro,
Filtrar. IDs úteis: id_username, id_password, q, unidade, especialidade,
sidebarToggle, sidebarOverlay; o badge usa a classe .sirhosp-topbar-sync,
não um ID. Não modificar templates somente por conveniência de seletores.

### D7 — Evidência pequena e catálogo honesto

Diretório por run em `/tmp/sirhosp-verification/<run-id>/`, com relatório JSON,
resumo Markdown e screenshots antes/depois de ações relevantes, sem campos
de senha preenchidos. Registrar métodos/status/URLs sanitizados e console
filtrado; não capturar HAR, headers/cookies ou payloads de login.

Resultados: PASS/0; FAIL/1; BLOCKED/2; SKIPPED/3 em execução só omitida.
No agregado, FAIL prevalece sobre BLOCKED, depois SKIPPED; exit 0 exige todos
os casos solicitados PASS e cleanup aprovado. Separar resultado do caso e da
limpeza. Timeout e falta de browser/credencial/dataset não são sucesso.

O mapa de features distingue caso implementado/provado de expansão futura.
Evidência sobrevive ao cleanup. Logs brutos de auth e storage-state não são
evidências públicas. Os artefatos só contêm o dataset fictício confirmado.

### D8 — MCP assistido sem fingir isolamento técnico

A skill usa o mesmo doctor/open/close e contextos MCP com nomes exclusivos
por run/papel. `new_page` expõe `isolatedContext`, mas isso ainda precisa
ser comprovado na instância instalada; não usar a sessão pessoal do operador.

MCP usa apenas roteiros de leitura mapeados e credenciais temporárias emitidas
por open. A skill não é um firewall nem assegura a allowlist de transporte do
Playwright: não prometer essa proteção para ferramentas MCP irrestritas.
Verificar alvo antes de dirigir, supervisionar ações e comparar efeitos ao
encerrar. Desvio, recurso indisponível ou ausência de isolamento gera BLOCKED
ou FAIL; não reconfigurar `.pi/mcp.json` ou anexar a browser pessoal por conta própria.

### D9 — Validação containerizada e limites de execução

Antes de S1, registrar BASE_REF e baseline/CI conhecido. Se não existir baseline
confiável, executar o gate global uma vez antes do primeiro RED, sem repetir
esse preflight em cada slice. Confirmar que a imagem test-runner corresponde
ao lockfile atual; reconstruí-la nesse projeto de testes se estiver obsoleta,
sem confundir dependência ausente na imagem com RED da funcionalidade.

RED/GREEN focados usam o test-runner existente com projeto distinto do dev:

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test \
  -f compose.yml -f compose.test.yml run --rm test-runner \
  uv run --no-sync pytest -q CAMINHOS_DOS_TESTES_DO_SLICE
```

Substituir somente o argumento final pelos caminhos exatos do slice-prompt;
essa linha é um molde, não um comando pronto. Não executar contra o db de dev.
Ao terminar os diagnósticos focados, encerrar somente esse projeto de testes:

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test \
  -f compose.yml -f compose.test.yml down --remove-orphans
```

Os gates oficiais do slice são `check`, `unit`, `lint` e `typecheck` via
`./scripts/test-in-container.sh`; integration oficial quando houver mudança
Django/persistência. Como scripts/automation não entram nos alvos atuais de
lint/mypy, verificar também explicitamente os arquivos novos no test-runner:

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test \
  -f compose.yml -f compose.test.yml run --rm test-runner \
  uv run --no-sync ruff check scripts/verify_portal.py
POSTGRES_PORT=55433 docker compose -p sirhosp-test \
  -f compose.yml -f compose.test.yml run --rm test-runner \
  uv run --no-sync mypy --cache-dir /tmp/.mypy_cache scripts/verify_portal.py
```

A partir de S2, acrescentar `automation/verification` aos dois comandos acima.
Gate global completo uma vez ao final, incluindo integration separadamente
porque `quality-gate` atualmente executa check/unit/lint/typecheck, não integration.
Toda alteração Markdown passa por `./scripts/markdown-lint.sh` e o change por
`openspec validate add-dev-browser-verification-suite --strict`. O script
exclui `.pi/`; em S3 validar também explicitamente os arquivos da skill com
markdownlint-cli2 e a configuração do projeto.

Não executar `scripts/container-smoke.sh`: ele faz `down -v` e inicia workers.
Não reutilizar `smoke-vpn-connectivity.sh` sem auditar seus efeitos; não é driver
UI nem preflight de dataset. Nunca usar pytest host-only como gate oficial.

## Risks / Trade-offs

- [Conta privilegiada temporária] → marcador/nomes reservados, timer e revogação;
  revogação não desfaz ações eventualmente feitas durante a janela.
- [Crash/reboot] → finally + timer enquanto o host estiver ativo + recovery;
  limite residual declarado, sem daemon ou alteração de autenticação global.
- [GET mutante/filas] → roteiros e allowlist do driver, comparação de metadados,
  sem crawler e sem auto-cleanup de negócios.
- [Estado compartilhado] → uma sessão de verificação, workers parados e
  coordenação com o operador; concorrência humana pode tornar prova inconclusiva.
- [Drift de spec antiga] → services-portal-navigation cita /patients/ no
  pós-login, mas settings e test_portal_entry_auth consolidam /painel/.
  Esta suíte adota o comportamento atual explicitamente e registra o drift;
  não corrige outras specs ou o produto silenciosamente.
- [Scripts fora do gate padrão] → validar explicitamente scripts/automation
  em container, além do gate oficial, que hoje não inclui esses diretórios.

## Migration Plan

Não há migration. Entregar S1, S2 e S3 em ordem, com TDD e STOP após cada slice.
A política atual do Git ignora changes ativos (`openspec/changes/*/`) e
versiona o archive. Estes artefatos são locais: preservar a política e fazer
handoff explícito dos prompts se o executor usar outro checkout/worktree;
não presumir que o plano estará no HEAD nem adicionar arquivos à força.
Antes da primeira ativação real, revisar destino e efeitos com o operador.
Criar somente contas owned; preservar todo o resto do banco.

Rollback: executar close/recovery, comprovar contas inativas e senhas
inutilizáveis, cancelar apenas o timer owned, opcionalmente parar web/db e só
então reverter os arquivos deste change. Não remover volumes nem reativar
workers. O gate global final inclui integration e uma prova real separada
da suíte unitária, sem depender de dev ligado em CI.
