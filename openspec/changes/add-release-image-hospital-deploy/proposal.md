# Change Proposal: add-release-image-hospital-deploy

## Why

O deployment atual exige checkout do repositório, `git pull` e build local da
imagem no servidor doméstico. O servidor definitivo ficará dentro do hospital
e deve executar somente artefatos de release já validados e publicados pelo
GitHub, sem toolchain de build nem cópia do código-fonte.

## What Changes

- Publicar a imagem `prod` no GitHub Container Registry (GHCR) quando um release
  ou pré-release for publicado.
- Executar o quality gate oficial sobre o commit da tag antes de publicar a
  imagem.
- Publicar uma tag imutável correspondente ao nome do release e canais móveis
  separados para release estável e pré-release.
- Anexar ao release um único `compose.hospital.yml` autônomo, sem `build:` e sem
  dependência de checkout do repositório.
- Executar PostgreSQL, portal, worker persistente de ingestão, orquestrador de
  censo e worker de sumários a partir desse Compose.
- Documentar instalação inicial, autenticação no GHCR, backup, pull, migration,
  ativação, health check e retorno para uma versão anterior.
- Preservar o Compose doméstico atual para desenvolvimento e validação antes da
  produção hospitalar.

## Capabilities

### New Capabilities

- `release-image-hospital-deploy`: publicação versionada da imagem no GHCR e
  deployment hospitalar sem build local usando um único arquivo Compose.

### Modified Capabilities

Nenhuma capability clínica é modificada. A mudança atua somente na cadeia de
empacotamento e deployment.

## Impact

- GitHub Actions: novo workflow disparado por `release.published`.
- Registro: `ghcr.io/carlosapgomes/sirhosp` com tag exata do release, `latest`
  apenas para release estável e `prerelease` apenas para pré-release.
- Servidor hospitalar: requer Docker Engine, Docker Compose, um `.env` local e,
  enquanto o pacote não for público, login GHCR com token somente
  `read:packages`.
- Banco: volume nomeado persistente; migrations continuam explícitas e precedidas
  por backup operacional.
- Rede: não inclui containers Tailscale ou Cloudflared; reutiliza a rede Docker
  externa `hospital_edge`, já compartilhada com o Cloudflared hospitalar, e
  expõe o portal nessa rede pelo alias `prisma`.
- Segurança: nenhuma credencial entra na imagem, no workflow ou no Compose
  versionado.
- Não objetivos: deployment remoto automático, armazenamento de secrets no
  GitHub, Kubernetes/Swarm, múltiplas arquiteturas, proxy TLS interno, rollback
  automático ou alteração da topologia doméstica atual.
