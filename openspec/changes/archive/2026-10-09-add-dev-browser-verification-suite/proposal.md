# Proposal: suíte complementar de verificação do portal dev

## Why

Os testes existentes comprovam regras e respostas Django, mas não asseguram que
uma instância já implantada tenha esquema atualizado, login real funcional,
JavaScript/HTMX operante e navegação utilizável. Uma suíte complementar no dev
com dados fictícios reduz regressões visíveis para diretoria, qualidade e gestão
de prontuários, sem acessar produção ou iniciar processamento clínico.

## What Changes

- Introduzir sessões de verificação com contas exclusivas `verify_user` e
  `verify_admin`, senhas fortes efêmeras e um único controlador local.
- Na abertura, executar preflight, gerar senhas e ativar somente as contas de
  teste; no fechamento, aplicar `set_unusable_password()` e desativá-las.
- Aceitar conscientemente que senhas temporárias possam aparecer na interação
  assistida com o LLM; não criar cofre, `.env` com senhas de teste ou mecanismo
  elaborado de transporte de segredos. Relatórios não incluem credenciais.
- Oferecer fechamento idempotente, exclusão mútua e encerramento independente
  por timer local para sessões interrompidas enquanto a máquina estiver ativa.
- Permitir subir/parar explicitamente apenas web/db, preservando volumes.
- Executar smoke por Playwright Python sobre o portal real: autenticação,
  navegação, perfil, censo, atualização HTMX e larguras desktop/mobile.
- Criar a skill local `verify-sirhosp`, com mapa de funcionalidades e roteiro
  assistido pelo Chrome DevTools MCP; provar uma funcionalidade real antes de
  considerar a skill entregue.
- Produzir evidências por execução e resultados `PASS`, `FAIL`, `BLOCKED` ou
  `SKIPPED`, sem confundir ausência de pré-requisito com sucesso.

### Escopo inicial e sucesso

O primeiro slice entrega abertura/fechamento verificável de contas efêmeras;
os seguintes acrescentam o navegador repetível e a skill assistida. O change
termina quando um fluxo real de login, navegação e logout produz evidências,
as contas ficam inativas/inutilizáveis após sucesso e falha controlada, e uma
execução MCP segue o mesmo contrato de sessão sem modificar dados de negócio.

### Não objetivos

- Não substituir nem enfraquecer os gates oficiais de unit/integration.
- Não alterar autenticação do produto, permissões de usuários reais,
  models/migrations, domínio clínico ou conectores Playwright operacionais.
- Não usar produção, dados reais, workers, scraping ou provedores LLM.
- Não testar nesta entrega exportações, troca de senha, CRUD administrativo,
  criação de ingestão ou geração de sumários pela interface.
- Não resetar/reescrever o banco fictício existente, alterar `.env`, DNS,
  tokens, túnel Cloudflare ou infraestrutura edge compartilhada.
- Não introduzir dependências pesadas, novo servidor MCP, Celery ou Redis.

## Capabilities

### New Capabilities

- `dev-verification-sessions`: preflight de desenvolvimento, contas efêmeras,
  exclusão mútua, encerramento/recovery e operação limitada a web/db.
- `dev-browser-verification`: cenários reais por navegador, evidências,
  catálogo extensível e skill assistida complementar aos testes existentes.

### Modified Capabilities

Nenhuma. O contrato de verificação observa o produto existente; não modifica
os requisitos de autenticação, censo ou navegação do portal.

## Impact

- Código futuro concentrado em helpers de `apps/accounts`, um management
  command novo, controlador em `scripts/verify_portal.py`, driver isolado em
  `automation/verification/` e testes sintéticos específicos.
- Documentação futura em `docs/dev-verification.md` e
  `.pi/skills/verify-sirhosp/`. Os nomes e limites exatos estão nos slice-prompts.
- Reutiliza Python 3.12, uv, Django, PostgreSQL e Playwright já presentes;
  Chrome DevTools MCP e systemd do usuário são capacidades externas a verificar.
- Nenhuma API HTTP nova, migration ou mudança de infraestrutura de produção.
- A suíte inicialmente é um comando complementar explícito, não uma dependência
  silenciosa do quality-gate ou da instância pública de dev durante testes unitários.

### Risco e mitigação

Classificação manual ESAA: **PROFISSIONAL**, três critérios — autenticação,
persistência das contas sintéticas e segurança de acesso. Não há refatoração
ampla ou mudança arquitetural do produto; uma futura ampliação para produção
exige nova decisão e reclassificação.

Os riscos principais são destino errado, colisão com conta humana, admin de
teste ativo após interrupção, efeitos de GETs mutantes e evidências indevidas.
Mitigar com destino local explicitamente validado, nomes/ownership reservados,
revogação/timer, roteiros restritos e evidências limitadas a dados fictícios.
O timer não promete proteção após queda/reboot; recovery e fechamento manual
fazem parte do contrato. Revisão humana de escopo e acesso é necessária antes
da primeira ativação real.
