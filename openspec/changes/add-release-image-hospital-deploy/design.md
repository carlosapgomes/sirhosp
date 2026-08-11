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

1. Construir exatamente o commit associado ao release publicado.
2. Impedir publicação quando o quality gate oficial falhar.
3. Tornar release estável e pré-release distinguíveis sem sobrescrever `latest`
   com código de pré-release.
4. Permitir instalação e atualização hospitalar com um único Compose, `.env` e
   comandos Docker, sem checkout do repositório.
5. Manter migrations, backup e seleção de versão como ações explícitas do
   operador.

## Decisions

### Decision 1: GHCR and release-published trigger

Um workflow dedicado reage a `release` com tipo `published`, que cobre releases
estáveis e pré-releases publicados, mas não drafts. O checkout usa
`github.event.release.tag_name`; o target `prod` do `Dockerfile` é publicado em
`ghcr.io/${{ github.repository }}` somente após o quality gate oficial.

Tags publicadas:

- nome exato da tag do release, para deployment e rollback reproduzíveis;
- `latest`, somente quando `prerelease` for falso;
- `prerelease`, somente quando `prerelease` for verdadeiro.

A imagem inclui metadata OCI, SBOM e provenance do BuildKit. O Compose também é
anexado ao release para que o servidor não precise baixar o repositório.

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

- Release publicado com commit inválido: job de validação bloqueia a publicação
  da imagem e do Compose.
- Pré-release substitui produção estável: `latest` nunca é atualizado por
  pré-release; produção usa tag exata.
- Pacote GHCR privado: runbook exige token somente `read:packages` no host.
- Perda de dados: volume nomeado não é removido no update e backup antecede
  migration.
- Tag alterada ou removida: releases operacionais devem ser imutáveis; a
  provenance permite relacionar imagem, workflow e commit.
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
