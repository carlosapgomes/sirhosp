# Proposal: add-user-profile-and-self-service-password

## Problema

O portal Prisma autentica usuários no Django, mas não oferece nenhuma
superfície de conta: não há página de perfil nem troca de senha pelo
próprio usuário. Hoje existem dois usuários (admin do sistema e a
diretora do hospital) geridos via `/admin`; a adição de cinco
enfermeiras iminente tornaria o administrador o responsável por escolher
e retransmitir senhas de todos — sem responsabilidade individual por
ação (accountability) e sem política mínima de senha no primeiro acesso.

Autenticação institucional (Kerberos via KDC, sem LDAP) foi investigada
e é viável, mas depende de negociação com a TI do hospital e merece ADR
própria; não bloqueia o onboarding das enfermeiras.

## Objetivo

Entregar autosserviço de conta no portal (opção 2 da decisão do
operador, 2026-09-08):

1. Página `/perfil/` para o usuário autenticado ver os próprios dados
   (identidade, somente leitura) e trocar a própria senha (com senha
   atual obrigatória e os validadores de senha já configurados).
2. Fluxo de senha provisória: o operador provisiona usuários do portal
   por comando (sem escolher senha — o sistema gera e exibe uma única
   vez) e o usuário é obrigado a trocar a senha no primeiro login antes
   de usar o portal.

## Escopo

O sistema tem exatamente **dois papéis** (decisão do operador,
2026-09-08):

- **admin** — superuser do Django (administrador do sistema): mantém o
  `/admin`, provisiona usuários e opera a infraestrutura;
- **usuário comum** — usuário ativo, sem `is_staff`/`is_superuser`:
  acessa todo o portal autenticado (diretora e enfermeiras).

Não há papéis intermediários, grupos ou permissões finas neste change.

- App `apps/accounts` (hoje vazia) passa a abrigar views, URLs,
  middleware e o comando de provisionamento (que cria sempre usuários
  comuns; admin continua sendo criado pelo próprio Django admin).
- Templates novos seguem o estilo Bootstrap do portal (`base_sidebar`,
  cards e formulários no padrão de `registration/login.html`).
- Link "Perfil" na área do usuário do sidebar.

## Fora de escopo

- Autenticação Kerberos/institucional (futuro change + ADR; este change
  não altera `AUTHENTICATION_BACKENDS`).
- Recuperação de senha por e-mail (sem SMTP no hospital; perda de senha
  é resolvida pelo operador com reemissão de senha provisória).
- Custom user model (`AUTH_USER_MODEL` permanece o padrão do Django).
- Qualquer superfície de gestão de usuários além do provisionamento por
  comando (bloqueio/permissões continuam no `/admin`, restrito ao
  administrador do sistema).

## Sucesso

- As cinco enfermeiras e a diretora acessam o portal com contas
  individuais provisionadas por comando, trocam a senha provisória no
  primeiro login (forçado) e thereafter autogerenciam a própria senha em
  `/perfil/`.
- O administrador do sistema deixa de conhecer senhas de usuários.
