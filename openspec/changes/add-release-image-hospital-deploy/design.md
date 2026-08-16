# Release Image and Hospital Deployment Design

## Context

O runtime doméstico atual combina `compose.yml` e `compose.prod.yml`, constrói a
imagem no próprio host e inclui serviços Tailscale/Cloudflared. O host hospitalar
não deve empacotar essas pontes nem depender de Git, Dockerfile, lockfile ou
compilação local, mas deve reutilizar a rede externa `hospital_edge` já usada
pelo container Cloudflared do hospital.

O repositório é público, mas pacotes GHCR podem continuar privados até sua
visibilidade ser alterada. Por isso o procedimento de produção admite login no
registro sem tornar essa autenticação parte do Compose.

## Goals

1. Construir exatamente o commit associado a uma tag de release existente.
2. Impedir criação de draft, imagem ou publicação quando o quality gate oficial
   falhar.
3. Anexar todos os assets antes de publicar e bloquear tag e assets com releases
   imutáveis do GitHub.
4. Tornar release estável e pré-release distinguíveis sem sobrescrever `latest`
   com código de pré-release.
5. Permitir instalação e atualização hospitalar com um único Compose, `.env` e
   comandos Docker, sem checkout do repositório.
6. Manter migrations, backup e seleção de versão como ações explícitas do
   operador.

## Decisions

### Decision 1: Draft-first immutable release workflow

Um workflow dedicado usa `workflow_dispatch` com uma tag Git exata existente e
um booleano de pré-release. O job de validação resolve o commit da tag e executa
o quality gate oficial. O job de publicação usa esse SHA validado, confirma que
a tag continua no mesmo commit e exige que releases imutáveis estejam
habilitadas no repositório.

Antes de qualquer publicação, o workflow recusa uma tag exata que já exista no
GHCR e cria um draft contendo `compose.hospital.yml`. Em seguida publica o target
`prod` do `Dockerfile`, publica o draft e verifica `immutable=true` pela API do
GitHub. Assets nunca são anexados ou substituídos depois da publicação.

Tags de imagem publicadas:

- nome exato da tag do release, nunca reutilizado, para deployment e rollback
  reproduzíveis;
- `latest`, somente quando `prerelease` for falso;
- `prerelease`, somente quando `prerelease` for verdadeiro.

A imagem inclui metadata OCI, SBOM e provenance do BuildKit. Imutabilidade de
release bloqueia a Git tag e os assets; a recusa prévia da tag exata protege o
canal versionado da imagem contra sobrescrita pelo workflow.

### Decision 2: One standalone hospital Compose

`compose.hospital.yml` contém todos os serviços necessários e não possui
`build:`. Todos os serviços Django compartilham uma única referência:

```text
ghcr.io/carlosapgomes/sirhosp:${SIRHOSP_VERSION}
```

`SIRHOSP_VERSION` é obrigatória e deve ser a tag exata do release ou
pré-release. Canais móveis existem para descoberta, mas o runbook não os usa em
produção. Assim, `docker compose pull` não muda silenciosamente a versão
implantada.

Serviços incluídos:

- `db` com volume PostgreSQL persistente e sem porta publicada;
- `web` com health check HTTP e porta de host parametrizável;
- `persistent_worker`, escalável e sem `container_name` fixo;
- `census_orchestrator`;
- `summary_worker`.

O arquivo não contém serviços Tailscale ou Cloudflared. Todos os serviços Django
usam o bridge interno e a rede Docker externa preexistente `hospital_edge`, em
paridade com `compose.prod.yml`; `web` também recebe o alias `prisma` usado como
origem pelo Cloudflared. O PostgreSQL permanece somente no bridge interno e sem
porta publicada.

### Decision 3: Secrets remain host-local

O `.env` do host fornece secrets e parâmetros operacionais. Variáveis críticas
usam interpolação Compose com `:?`, fazendo o comando falhar antes de criar
containers quando estiverem ausentes. O token GHCR fica no credential store do
Docker, nunca no `.env` da aplicação.

### Decision 4: Explicit transactional deployment procedure

O procedimento operacional é:

1. selecionar uma tag exata em `SIRHOSP_VERSION`;
2. autenticar no GHCR se necessário;
3. baixar o Compose anexado ao release;
4. confirmar que a rede externa `hospital_edge` existe e contém o Cloudflared;
5. validar `docker compose config --quiet`;
6. executar backup PostgreSQL;
7. executar `docker compose pull`;
8. garantir `db` saudável;
9. executar migration one-shot com a nova imagem;
10. executar `up -d --remove-orphans`;
11. verificar containers, endpoint `/health/` e rota Cloudflared para
    `http://prisma:8000`.

A imagem anterior permanece no registry. Retorno de aplicação altera
`SIRHOSP_VERSION` para a tag anterior. Se migrations não forem compatíveis com a
versão anterior, o rollback exige parada coordenada e restauração do backup; o
runbook não promete downgrade automático de schema.

### Decision 5: Home runtime remains separate

`compose.yml`, `compose.prod.yml`, Tailscale e Cloudflared permanecem como estão.
O novo arquivo é um artefato específico do servidor hospitalar. Isso evita
condicionais de rede e build que tornariam os dois ambientes ambíguos.

## Risks and Mitigations

- Tag com commit inválido: o job de validação bloqueia draft, imagem e release.
- Imutabilidade habilitada com fluxo antigo: o fluxo draft-first anexa o Compose
  antes da publicação e verifica a proteção depois dela.
- Tag exata de imagem já existente: o workflow falha antes de criar o draft ou
  sobrescrever o artefato versionado; correções recebem nova tag.
- Pré-release substitui produção estável: `latest` nunca é atualizado por
  pré-release; produção usa tag exata.
- Pacote GHCR privado: runbook exige token somente `read:packages` no host.
- Perda de dados: volume nomeado não é removido no update e backup antecede
  migration.
- Tag alterada ou asset substituído: releases imutáveis bloqueiam ambas as
  operações após publicação; a provenance relaciona imagem, workflow e commit.
- Imagem e Compose incompatíveis: ambos saem do mesmo release; o operador deve
  baixar o Compose correspondente à tag selecionada.
- Rede externa ausente ou Cloudflared desconectado: o preflight inspeciona
  `hospital_edge` antes de criar containers; o portal mantém o alias `prisma`.

## Alternatives Rejected

- Build no servidor hospitalar: aumenta superfície, tempo e variação do
  artefato.
- Usar apenas `latest`: impede rollback determinístico e mistura pré-release com
  produção estável.
- Auto-update por Watchtower: aplica versões sem migration, backup ou decisão do
  operador.
- Deployment remoto por SSH no GitHub Actions: exige credenciais e conectividade
  de entrada no hospital e não é necessário para o primeiro contrato.
- Reutilizar os dois Compose atuais: mantém dependência de checkout e inclui
  topologia doméstica que não pertence ao hospital.
