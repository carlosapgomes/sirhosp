# Deploy — SIRHOSP

Instruções para deploy em produção, ativação do worker contínuo e do
orquestrador adaptativo de censo.

## Deployment hospitalar por imagem de release

O servidor definitivo dentro do hospital usa somente:

- `compose.hospital.yml`, baixado do release correspondente;
- um `.env` local com permissões restritas;
- imagens versionadas de `ghcr.io/carlosapgomes/sirhosp`.

Não é necessário clonar o repositório, executar `git pull`, manter toolchain de
build ou executar `docker compose build`. O runtime doméstico descrito nas
demais seções continua separado para desenvolvimento e validação.

### Publicação da imagem

Releases futuras são criadas pelo workflow manual `Publish Release Image`. Não
publique primeiro uma release pela interface do GitHub: com releases imutáveis,
a tag e os assets são bloqueados no momento da publicação.

O repositório deve possuir o secret de Actions
`IMMUTABLE_RELEASES_TOKEN`, com acesso administrativo somente ao necessário
para consultar a configuração de releases imutáveis. O `GITHUB_TOKEN` padrão
não acessa esse endpoint. Nunca coloque esse token no código, no Compose ou no
`.env` hospitalar.

Antes da tag, crie e valide o runbook específico da versão em
`docs/releases/<release-tag>-upgrade.md`. O workflow exige esse arquivo e o
anexa à release junto com o Compose; como a release é imutável, ele não pode ser
acrescentado depois.

Crie e envie uma nova tag exata, nunca reutilizando uma anterior:

```bash
git tag v1.0.0-rc.2 <commit-validado>
git push origin v1.0.0-rc.2
```

Dispare o workflow na branch padrão, indicando a tag e se ela é pré-release:

```bash
gh workflow run publish-release-image.yml \
  -f release_tag=v1.0.0-rc.2 \
  -f prerelease=true
```

O workflow:

1. resolve a tag exata e executa
   `./scripts/test-in-container.sh quality-gate`;
2. confirma que releases imutáveis estão habilitadas no repositório;
3. recusa uma tag exata de imagem que já exista no GHCR;
4. exige `docs/releases/<release-tag>-upgrade.md`;
5. cria um draft e anexa `compose.hospital.yml`, o runbook da tag, o script
   `deploy/exit-reconciliation-scheduler.sh` e os seis units systemd da
   reconciliação de saídas (3 services + 3 timers) antes da publicação;
6. constrói e publica o target `prod` do `Dockerfile`;
7. publica o draft e confirma que o GitHub marcou a release como imutável.

Para um release estável, use `prerelease=false`. Ele publica a tag exata e
atualiza `latest`. Um pré-release publica a tag exata e atualiza `prerelease`,
sem alterar `latest`. Produção sempre usa a tag exata; não use os canais móveis
no `.env`.

Depois de publicada, uma release não pode ter sua tag ou seus assets alterados.
Toda correção recebe uma nova tag. Se o workflow falhar e deixar um draft, não o
publique manualmente sem confirmar que quality gate, imagem e asset concluíram;
inspecione a execução e o draft antes de decidir entre concluir ou descartá-lo.

### Pré-requisitos do servidor hospitalar

- Linux com Docker Engine e Docker Compose v2;
- acesso HTTPS de saída ao GitHub e ao GHCR;
- acesso direto do host ao sistema legado do hospital;
- container Cloudflared já conectado à rede Docker externa `hospital_edge`;
- ingress do FQDN configurado com origem `http://prisma:8000`;
- firewall permitindo a porta do portal somente para a rede autorizada;
- espaço protegido para backups do PostgreSQL.

O Compose hospitalar não cria containers Tailscale ou Cloudflared. Ele reutiliza
a rede externa `hospital_edge`, conecta nela os serviços Django e fornece ao
serviço `web` o alias `prisma`. O PostgreSQL permanece somente na rede interna e
sem porta publicada; somente o portal publica uma porta no host.

### Instalação inicial

Crie o diretório operacional:

```bash
sudo install -d -m 0750 -o "$USER" -g "$USER" /opt/sirhosp
cd /opt/sirhosp
```

Escolha a tag exata já publicada, por exemplo uma tag sintética
`v1.0.0-rc.1`, e baixe o Compose anexado ao mesmo release:

```bash
export SIRHOSP_VERSION=v1.0.0-rc.1
curl -fL \
  -o compose.hospital.yml \
  "https://github.com/carlosapgomes/sirhosp/releases/download/${SIRHOSP_VERSION}/compose.hospital.yml"
```

Se o pacote GHCR estiver privado, crie um token GitHub somente com
`read:packages` e autentique o Docker. Não grave esse token no `.env` da
aplicação:

```bash
printf '%s' "$GHCR_TOKEN" | \
  docker login ghcr.io -u SEU_USUARIO_GITHUB --password-stdin
unset GHCR_TOKEN
```

Crie `/opt/sirhosp/.env` com valores reais somente no servidor. Este exemplo
contém apenas placeholders:

```text
SIRHOSP_VERSION=v1.0.0-rc.1
SIRHOSP_BIND_ADDRESS=0.0.0.0
DJANGO_PORT=8000
DJANGO_SECRET_KEY=SUBSTITUIR
DJANGO_ALLOWED_HOSTS=sirhosp.hospital.local
POSTGRES_DB=sirhosp
POSTGRES_USER=sirhosp
POSTGRES_PASSWORD=SUBSTITUIR
SOURCE_SYSTEM_URL=https://sistema-legado.interno/
SOURCE_SYSTEM_USERNAME=SUBSTITUIR
SOURCE_SYSTEM_PASSWORD=SUBSTITUIR
```

Adicione as variáveis de LLM já usadas pelo ambiente somente quando
necessárias. Restrinja o arquivo:

```bash
chmod 600 /opt/sirhosp/.env
```

Confirme que a rede externa já existe e que o container Cloudflared aparece
entre os participantes:

```bash
docker network inspect hospital_edge --format '{{json .Containers}}'
```

Se a rede não existir ou o Cloudflared não aparecer, corrija primeiro o runtime
do túnel. Não execute `docker compose up`: o Compose hospitalar referencia essa
rede como externa e não deve criar uma rede paralela.

Valide interpolação, estrutura e campos obrigatórios sem imprimir a configuração
renderizada:

```bash
docker compose --env-file .env -f compose.hospital.yml config --quiet
```

### Primeiro start e migrations

Baixe todas as imagens e inicie o banco:

```bash
docker compose --env-file .env -f compose.hospital.yml pull
docker compose --env-file .env -f compose.hospital.yml up -d db
```

Execute migrations em um container one-shot da versão selecionada:

```bash
docker compose --env-file .env -f compose.hospital.yml run --rm web \
  uv run --no-sync python manage.py migrate --noinput
```

Inicie a topologia completa:

```bash
docker compose --env-file .env -f compose.hospital.yml \
  up -d --remove-orphans
```

Verifique containers e saúde HTTP:

```bash
docker compose --env-file .env -f compose.hospital.yml ps
curl -fsS http://127.0.0.1:8000/health/
```

### Atualização para um novo release

Baixe e leia o runbook anexado à mesma tag antes de iniciar. Ele contém
migrations, ativações e smoke tests específicos da versão. Por exemplo:

```bash
export NEW_VERSION=v1.0.0-rc.2
curl -fL \
  -o upgrade.md \
  "https://github.com/carlosapgomes/sirhosp/releases/download/${NEW_VERSION}/${NEW_VERSION}-upgrade.md"
```

Antes da migration, garanta que o banco esteja saudável e crie um backup local
com timestamp:

```bash
mkdir -p backups
chmod 700 backups
docker compose --env-file .env -f compose.hospital.yml up -d db
docker compose --env-file .env -f compose.hospital.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  > "backups/sirhosp-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

Confirme que o arquivo não está vazio. Depois altere somente
`SIRHOSP_VERSION` no `.env` para a nova tag exata e execute:

```bash
docker compose --env-file .env -f compose.hospital.yml config --quiet
docker compose --env-file .env -f compose.hospital.yml pull
docker compose --env-file .env -f compose.hospital.yml run --rm web \
  uv run --no-sync python manage.py migrate --noinput
docker compose --env-file .env -f compose.hospital.yml \
  up -d --remove-orphans
docker compose --env-file .env -f compose.hospital.yml ps
curl -fsS http://127.0.0.1:8000/health/
```

Não use `down -v`: a opção `-v` remove o volume PostgreSQL.

### Escala do worker persistente

O primeiro `up` inicia uma réplica. Para usar a concorrência validada pelo
hospital:

```bash
docker compose --env-file .env -f compose.hospital.yml \
  up -d --scale persistent_worker=15 persistent_worker
```

Repita o `--scale` após atualizações caso o Compose tenha convergido para uma
réplica. Observe status e consumo:

```bash
docker compose --env-file .env -f compose.hospital.yml ps
docker stats --no-stream
```

### Retorno para uma versão anterior

Para retornar somente a aplicação, altere `SIRHOSP_VERSION` para a tag exata
anterior, valide, faça pull e recrie os serviços:

```bash
docker compose --env-file .env -f compose.hospital.yml config --quiet
docker compose --env-file .env -f compose.hospital.yml pull
docker compose --env-file .env -f compose.hospital.yml \
  up -d --remove-orphans
```

Isso é seguro somente quando a versão anterior é compatível com o schema já
migrado. Se a migration nova não for retrocompatível, interrompa os serviços
mutantes e faça uma restauração coordenada do backup correspondente; não tente
reverter automaticamente migrations em produção.

### Inspeção e logs

```bash
docker compose --env-file .env -f compose.hospital.yml ps
docker compose --env-file .env -f compose.hospital.yml \
  logs --tail 200 web persistent_worker census_orchestrator summary_worker
```

---

## 1. Pré-requisitos

- Linux com **systemd** (Ubuntu 20.04+, Debian 11+, RHEL 8+)
- **Docker** e Docker Compose instalados
- Credenciais do sistema fonte configuradas no `.env`:

```text
SOURCE_SYSTEM_URL=https://...
SOURCE_SYSTEM_USERNAME=...
SOURCE_SYSTEM_PASSWORD=...
```

---

## 2. Estrutura de diretórios no servidor

```text
/opt/sirhosp/
├── compose.yml              ← db
├── compose.prod.yml          ← web (Gunicorn) + worker
├── .env                      ← credenciais e secrets
└── deploy/
    └── systemd/
        ├── sirhosp-census-orchestrator.service  ← [OPCIONAL] long-running
        ├── sirhosp-discharges.service
        └── sirhosp-discharges.timer
```

---

## 3. Subir os containers

```bash
cd /opt/sirhosp

# Build e sobe em background
docker compose -f compose.yml -f compose.prod.yml up -d --build

# Verifica status
docker compose -f compose.yml -f compose.prod.yml ps

# Migrations (primeira vez ou após mudança de schema)
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py migrate

# Criar superuser (primeira vez)
docker compose -f compose.yml -f compose.prod.yml exec web \
  uv run --no-sync python manage.py createsuperuser
```

---

## 4. Worker de ingestão

O worker está configurado no `compose.prod.yml` com `--loop --sleep-seconds 5`.
Ele processa automaticamente os `IngestionRun` enfileirados pelo
`process_census_snapshot` (disparado pelo orquestrador) ou por outros comandos.

**Escalar workers** (paralelismo):

```bash
docker compose -f compose.yml -f compose.prod.yml up -d --scale worker=3
```

---

## 4a. Worker: armazenamento volátil (tmpfs)

O `worker` de produção escreve temporários, caches e config em **tmpfs**
(RAM volátil) em vez do overlay Docker/NVMe. Isso reduz escrita efêmera de
Playwright/Chromium e Python, preservando a vida útil do disco.

### 4a.1 Limites padrão por réplica

| Montagem | Padrão | Variável de override |
| --- | --- | --- |
| `/tmp` | `1g` | `WORKER_TMPFS_TMP_SIZE` |
| `/var/tmp` | `128m` | `WORKER_TMPFS_VAR_TMP_SIZE` |
| `/home/10001/.cache` | `256m` | `WORKER_TMPFS_CACHE_SIZE` |
| `/home/10001/.config` | `64m` | `WORKER_TMPFS_CONFIG_SIZE` |
| `/dev/shm` (`shm_size`) | `512m` | `WORKER_SHM_SIZE` |

Os limites são conservadores e suportam até 15 workers em um host com
~62 GiB de RAM. Overrides são opcionais e não exigem editar o Compose.

### 4a.2 Escalar até 15 workers

```bash
docker compose -f compose.yml -f compose.prod.yml up -d \
  --scale worker=15
```

### 4a.3 Overrides via `.env`

```bash
# Exemplos sintéticos (não usar valores reais em commit)
WORKER_SHM_SIZE=768m
WORKER_TMPFS_TMP_SIZE=2g
WORKER_TMPFS_VAR_TMP_SIZE=256m
WORKER_TMPFS_CACHE_SIZE=512m
WORKER_TMPFS_CONFIG_SIZE=128m
```

> **Aviso:** nunca imprimir nem versionar secrets.
`docker compose config` interpola variáveis do `.env`, incluindo
`DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD` e credenciais do sistema fonte.
Não redirecione essa saída para arquivos rastreados nem a cole em canais
de log. Use apenas para validação local e descarte a saída.

### 4a.4 Validação operacional

Inspecione `/tmp` e `/dev/shm` dentro de um worker:

```bash
docker compose -f compose.yml -f compose.prod.yml exec worker \
  sh -c 'df -h /tmp /var/tmp /dev/shm && ls -ld /tmp/xdg-cache /tmp/xdg-config'
```

Inspecione Block I/O, RAM e swap do host e dos containers:

```bash
# Block I/O e memória dos containers (procure BlockIO/MemUsage)
docker stats --no-stream

# RAM e swap do host
free -h
swapon --show
```

### 4a.5 Problemas conhecidos

- **`ENOSPC` em `/tmp`** (tmpfs cheio em picos de evolução clínica): suba
  `WORKER_TMPFS_TMP_SIZE` para `2g` no `.env` e recrie os workers.
- **Chromium falha por memória compartilhada** (`/dev/shm` insuficiente):
  suba `WORKER_SHM_SIZE` para `768m` ou `1g`.

### 4a.6 Rollback

Remover os overrides do `.env` (ou redefinir os limites para valores
menores) e recriar os containers reverte o runtime volátil ao tamanho
padrão sem alterar persistência clínica ou PostgreSQL:

```bash
docker compose -f compose.yml -f compose.prod.yml up -d --force-recreate worker
```

---

## 4c. Persistent-session ingestion worker

> **Status: ativo em produção hospitalar desde a RC5.**
>
> O runtime hospitalar usa
> `process_ingestion_runs_persistent_session --loop --real-handle
> --enable-real-queue`. A `RealHandleBridge` foi validada contra a interface
> real, incluindo autenticação, admissões, demografia, full-sync, evoluções,
> renovação de sessão, restart e saída sanitizada.
>
> O cutover da RC5 ativou quatro réplicas no servidor hospitalar. A quantidade
> de réplicas continua sendo uma decisão operacional: após cada atualização,
> reaplique explicitamente `--scale persistent_worker=<quantidade>` e monitore
> fila, heartbeat, estados finais, CPU, memória, tmpfs e logs. O Compose inicia
> uma réplica quando nenhuma escala é informada.
>
> Histórico de rollout, guardas do modo real, observabilidade e rollback:
> `docs/operations/persistent-worker-rollout.md`.

---

## 5. Orquestrador adaptativo de censo

O censo hospitalar é extraído pelo **orquestrador adaptativo**, que monitora a
fila de ingestão e dispara `extract_census` + `process_census_snapshot` apenas
quando for seguro (fila drenada, cooldown respeitado, sem batch aberto).

Não há timer fixo: o orquestrador executa em modo contínuo
(`--loop`), dormindo entre verificações e aplicando backoff em caso de falha.

### Por que um serviço dedicado?

Em produção, o orquestrador roda em um container dedicado (`census_orchestrator`)
com armazenamento volátil próprio (tmpfs), memória compartilhada parametrizável
para Chromium e limites de log. Isso:

- evita que a automação pesada do censo compartilhe temporários e runtime com o
  portal web (Gunicorn);
- reduz escrita efêmera no overlay Docker/NVMe — as escritas do Playwright vão
  para tmpfs em RAM;
- permite monitorar e dimensionar o custo real do orquestrador separadamente do
  worker e do web;
- evita que picos de `ENOSPC` no orquestrador afetem usuários do portal.

> **Aviso:** não execute o loop contínuo do orquestrador simultaneamente via
> `exec -T web` **e** pelo serviço dedicado `census_orchestrator`. Os dois
> loops competem pelo advisory lock e podem causar ciclos sobrepostos e
> comportamento imprevisível. Use **apenas um** dos métodos de execução
> contínua.

### 5.1 Executar como serviço systemd (recomendado para produção)

O arquivo `deploy/systemd/sirhosp-census-orchestrator.service` é um serviço
long-running, **não** um timer `OnCalendar`.

O serviço usa `docker compose --profile orchestrator up
--abort-on-container-exit`. O `ExecStart` roda em foreground — quando o
container morre (exit code != 0), o Compose encerra e o systemd reinicia
com `Restart=on-failure` e `RestartSec=10`. Isso garante que o orquestrador
volte a operar automaticamente após falhas transientes.

```bash
# Copiar unit para o systemd
cp /opt/sirhosp/deploy/systemd/sirhosp-census-orchestrator.service \
  /etc/systemd/system/

# Recarregar configuração
systemctl daemon-reload

# Habilitar e iniciar o serviço
systemctl enable --now sirhosp-census-orchestrator.service

# Verificar status
systemctl status sirhosp-census-orchestrator.service
```

### 5.2 Executar com o serviço dedicado (debug / testes)

Os comandos abaixo usam o serviço `census_orchestrator` diretamente via Docker
Compose (profile `orchestrator`). Isso valida o mesmo runtime volátil
(tmpfs, `/dev/shm`) da operação em produção.

```bash
cd /opt/sirhosp

# Iniciar o serviço dedicado em background (loop contínuo)
docker compose -f compose.yml -f compose.prod.yml --profile orchestrator up -d \
  census_orchestrator

# Um ciclo dry-run (diagnóstico, sem mutação) — container efêmero
docker compose -f compose.yml -f compose.prod.yml --profile orchestrator run \
  --rm census_orchestrator uv run --no-sync python manage.py \
  run_adaptive_census_cycles --dry-run

# Um ciclo real — container efêmero
docker compose -f compose.yml -f compose.prod.yml --profile orchestrator run \
  --rm census_orchestrator uv run --no-sync python manage.py \
  run_adaptive_census_cycles --once

# Modo contínuo em foreground (logs no terminal)
docker compose -f compose.yml -f compose.prod.yml --profile orchestrator up \
  census_orchestrator
```

### 5.3 Execução manual via web (fallback)

Caso o serviço dedicado não esteja disponível (ex.: durante migração ou
rollback), o operador pode executar o ciclo manualmente pelo container `web`.
Use apenas para diagnóstico pontual; não mantenha loops long-running por este
método.

```bash
cd /opt/sirhosp

# Passo 1: extrair censo do sistema fonte
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py extract_census

# Passo 2: processar o snapshot (cria/atualiza pacientes, enfileira extrações)
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py process_census_snapshot
```

### 5.4 Comandos de monitoramento

```bash
# Ver logs do serviço systemd
journalctl -u sirhosp-census-orchestrator.service -n 50 --no-pager

# Logs em tempo real
journalctl -u sirhosp-census-orchestrator.service -f

# Status do container Docker
docker compose -f compose.yml -f compose.prod.yml --profile orchestrator ps \
  census_orchestrator

# Logs Docker do container
docker compose -f compose.yml -f compose.prod.yml --profile orchestrator logs \
  census_orchestrator

# Estatísticas de recursos (CPU, memória, Block I/O)
docker stats --no-stream sirhosp-census-orchestrator
```

### 5.5 Validação do runtime volátil

> **Pré-condição:** garanta que o serviço `census_orchestrator` está rodando
> (seções 5.1 ou 5.2) antes de executar os comandos `exec` abaixo.

#### Inspecionar tmpfs e /dev/shm dentro do orquestrador

```bash
docker compose -f compose.yml -f compose.prod.yml --profile orchestrator exec \
  census_orchestrator sh -c 'df -h /tmp /var/tmp /dev/shm; ls -d /tmp/xdg-*'
```

A saída deve mostrar sistemas de arquivos `tmpfs` com os limites
configurados e `/dev/shm` com o tamanho definido em `CENSUS_ORCHESTRATOR_SHM_SIZE`.

#### Verificar escrita em disco do host

Compare `wMB/s` (write MB/s) do device antes e durante a extração:

```bash
# Monitorar escrita no device principal (ex.: sda, nvme0n1)
iostat -x 5
```

Com tmpfs, a escrita física deve ser baixa durante o censo (a maior parte
permanece em RAM). Picos sustentados indicam que temporários podem estar
vazando para o overlay Docker.

### 5.6 Variáveis de sizing do orquestrador

O orquestrador usa variáveis próprias, independentes dos `WORKER_*`:

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `CENSUS_ORCHESTRATOR_SHM_SIZE` | `512m` | Chrome (`/dev/shm`) |
| `CENSUS_ORCHESTRATOR_TMPFS_TMP_SIZE` | `1g` | Máximo de `/tmp` |
| `CENSUS_ORCHESTRATOR_TMPFS_VAR_TMP_SIZE` | `128m` | `/var/tmp` |
| `CENSUS_ORCHESTRATOR_TMPFS_CACHE_SIZE` | `256m` | `~/.cache` |
| `CENSUS_ORCHESTRATOR_TMPFS_CONFIG_SIZE` | `64m` | `~/.config` |

Overrides são feitos no `.env`, sem editar o Compose:

```bash
# Exemplos sintéticos (não usar valores reais em commit)
CENSUS_ORCHESTRATOR_SHM_SIZE=768m
CENSUS_ORCHESTRATOR_TMPFS_TMP_SIZE=2g
CENSUS_ORCHESTRATOR_TMPFS_VAR_TMP_SIZE=256m
CENSUS_ORCHESTRATOR_TMPFS_CACHE_SIZE=512m
CENSUS_ORCHESTRATOR_TMPFS_CONFIG_SIZE=128m
```

> **Aviso:** nunca imprimir nem versionar secrets.
> `docker compose config` interpola variáveis do `.env`, incluindo
> `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD` e credenciais do sistema fonte.
> Use `--profile orchestrator` ao inspecionar apenas o orquestrador.

### 5.7 Troubleshooting

| Problema | Causa provável | Ação |
| --- | --- | --- |
| `ENOSPC` (`/tmp`) | tmpfs cheio | Ajustar TMPFS_TMP_SIZE |
| Chromium (shm) | `/dev/shm` cheio | Ajustar `CENSUS_ORCHESTRATOR_SHM_SIZE` |
| Container não sobe | Config/.env | Ver logs do container |

### 5.8 Rollback e desabilitação

Para parar o orquestrador dedicado e voltar ao método anterior (execução
manual via `web`):

1. **Desabilitar o serviço systemd:**

   ```bash
   systemctl disable --now sirhosp-census-orchestrator.service
   ```

2. **Parar o container Compose (se estiver rodando fora do systemd):**

   ```bash
   docker compose -f compose.yml -f compose.prod.yml --profile orchestrator down
   ```

3. **Usar comandos manuais via `web`** conforme a seção 5.3 enquanto o
   problema é resolvido.

4. **Reverter overrides de variáveis** no `.env` (ou removê-las) e recriar
   o serviço quando reabilitar.

5. **Para reativar:** repita o passo 5.1 (copiar unit, habilitar e iniciar).

---

## 5a. Recuperação histórica dedicada (runtime batch-only)

A recuperação histórica consolidada (`recover_historical_data`) executa
Playwright/Chromium para extrair altas, admissões, óbitos e censo oficial de um
período retroativo. Em produção, o operador utiliza o serviço dedicado
`historical_recovery` em vez do container `web`, isolando o portal do impacto de
IO, memória e logs de batches manuais.

O runtime é **batch-only**: usado exclusivamente com `docker compose run --rm`.
Não é um daemon long-running, não executa em loop, não possui timer systemd e
não usa Celery/Redis. Cada execução é um container efêmero que persiste apenas
os resultados duráveis no PostgreSQL.

### 5a.1 Por que um runtime dedicado?

- Isola o portal web (Gunicorn) de picos de memória, CPU e escrita efêmera
  durante batches pesados.
- Reduz escrita no overlay Docker/NVMe: temporários do Playwright/Chromium vão
  para tmpfs em RAM.
- Permite parametrizar tmpfs e `/dev/shm` para batches históricos sem afetar
  workers contínuos.
- Evita que falhas de `ENOSPC` no recovery impactem usuários do portal.

### 5a.2 Execução dry-run (planejamento seguro)

O modo `--dry-run` imprime o plano sem chamar Playwright nem os extratores
reais. Use sempre antes de uma execução real para validar o escopo:

```bash
cd /opt/sirhosp

docker compose -f compose.yml -f compose.prod.yml --profile recovery run \
  --rm historical_recovery uv run --no-sync python manage.py \
  recover_historical_data --date 01/06/2026 --dry-run
```

### 5a.3 Execução real — data única

```bash
docker compose -f compose.yml -f compose.prod.yml --profile recovery run \
  --rm historical_recovery uv run --no-sync python manage.py \
  recover_historical_data --date 01/06/2026
```

### 5a.4 Execução real — intervalo de datas

Use `--start-date` e `--end-date` para um intervalo inclusivo:

```bash
docker compose -f compose.yml -f compose.prod.yml --profile recovery run \
  --rm historical_recovery uv run --no-sync python manage.py \
  recover_historical_data --start-date 01/06/2026 --end-date 05/06/2026
```

### 5a.5 Seleção de extratores

Use `--extractor` para limitar o escopo. O argumento pode ser repetido para
múltiplos extratores:

```bash
# Extrator único
docker compose -f compose.yml -f compose.prod.yml --profile recovery run \
  --rm historical_recovery uv run --no-sync python manage.py \
  recover_historical_data --date 01/06/2026 --extractor admissions --dry-run

# Múltiplos extratores (repetir --extractor)
docker compose -f compose.yml -f compose.prod.yml --profile recovery run \
  --rm historical_recovery uv run --no-sync python manage.py \
  recover_historical_data --date 01/06/2026 --extractor admissions \
  --extractor discharges --dry-run
```

Valores aceitos para `--extractor`:

| Extrator | Descrição |
| --- | --- |
| `discharges` | Altas do dia |
| `admissions` | Admissões do dia |
| `deaths` | Óbitos do dia |
| `official_census` | Censo oficial (arquivo TXT via ZIP) |

Os extratores selecionados executam na ordem determinística padrão
(`discharges`, `admissions`, `deaths`, `official_census`),
independentemente da ordem em que `--extractor` foi informado.

### 5a.6 Validação do runtime volátil

Antes de iniciar um batch real, valide tmpfs, `/dev/shm`, status do container
host e escrita em disco:

```bash
# Inspecionar tmpfs e /dev/shm dentro do runtime (container efêmero)
docker compose -f compose.yml -f compose.prod.yml --profile recovery run \
  --rm historical_recovery sh -c \
  'df -h /tmp /var/tmp /dev/shm; ls -d /tmp/xdg-*'

# Status do container (se ainda ativo)
docker compose -f compose.yml -f compose.prod.yml --profile recovery ps \
  historical_recovery

# Logs (ex.: após execução)
docker compose -f compose.yml -f compose.prod.yml --profile recovery logs \
  historical_recovery

# Estatísticas de recursos (CPU, memória, Block I/O)
docker stats --no-stream

# RAM e swap do host
free -h

# Escrita em disco (monitore wMB/s do device principal, ex.: sda, nvme0n1)
iostat -x 5
```

> Com tmpfs, a escrita física deve ser baixa durante o recovery (a maior parte
> permanece em RAM). Picos sustentados indicam que temporários podem estar
> vazando para o overlay Docker.

### 5a.7 Variáveis de sizing

O runtime `historical_recovery` usa variáveis próprias, independentes dos
`WORKER_*` e `CENSUS_ORCHESTRATOR_*`:

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `HISTORICAL_RECOVERY_SHM_SIZE` | `1g` | Chrome (`/dev/shm`) |
| `HISTORICAL_RECOVERY_TMPFS_TMP_SIZE` | `2g` | Máximo de `/tmp` |
| `HISTORICAL_RECOVERY_TMPFS_VAR_TMP_SIZE` | `256m` | `/var/tmp` |
| `HISTORICAL_RECOVERY_TMPFS_CACHE_SIZE` | `512m` | `~/.cache` |
| `HISTORICAL_RECOVERY_TMPFS_CONFIG_SIZE` | `128m` | `~/.config` |

Overrides são feitos no `.env`, sem editar o Compose:

```bash
# Exemplos sintéticos (não usar valores reais em commit)
HISTORICAL_RECOVERY_SHM_SIZE=2g
HISTORICAL_RECOVERY_TMPFS_TMP_SIZE=4g
HISTORICAL_RECOVERY_TMPFS_VAR_TMP_SIZE=512m
HISTORICAL_RECOVERY_TMPFS_CACHE_SIZE=1g
HISTORICAL_RECOVERY_TMPFS_CONFIG_SIZE=256m
```

> **Aviso:** nunca imprimir nem versionar secrets.
> `docker compose config` interpola variáveis do `.env`, incluindo
> `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD` e credenciais do sistema fonte.
> Use `--profile recovery` ao inspecionar apenas o runtime de recuperação.

### 5a.8 Troubleshooting

| Problema | Causa | Ação |
| --- | --- | --- |
| `ENOSPC` `/tmp` | tmpfs cheio | Subir `HISTORICAL_RECOVERY_TMPFS_TMP_SIZE` |
| Chromium (shm) | `/dev/shm` pequeno | Subir `HISTORICAL_RECOVERY_SHM_SIZE` |
| Container não inicia | Config ausente | `docker compose logs` |

### 5a.9 Paralelismo e segurança

> **Aviso:** não execute múltiplos batches pesados de recuperação histórica em
> paralelo sem decisão operacional explícita. Contenção em tmpfs e no sistema
> fonte pode causar `ENOSPC`, timeouts e dados inconsistentes. Execute um batch
> por vez.

### 5a.10 Rollback e fallback

Para parar de usar o runtime dedicado e voltar à execução via `web` durante
diagnóstico de emergência:

1. Simplesmente não use o perfil `recovery`. O runtime dedicado não interfere
   com outros serviços.
2. Execute a recuperação pelo container `web` conforme os comandos originais:

   ```bash
   docker compose -f compose.yml -f compose.prod.yml exec -T web \
     uv run --no-sync python manage.py recover_historical_data \
     --date 01/06/2026 --dry-run
   ```

3. Corrija o problema no runtime (ex.: ajuste de variáveis, `.env`).
4. Reabilite o runtime dedicado quando estiver funcional.

> A persistência clínica está no PostgreSQL e não depende do runtime. Nenhum
> dado é perdido ao alternar entre `historical_recovery` e `web`.

---

## 4b. Agendamento legado de extração de altas (DEPRECATED)

> **Status: DEPRECADO.** O contrato legado de **3 vezes ao dia**
> (11:00, 19:00 e 23:55, horário do servidor) executado por
> `deploy/discharges-scheduler.sh` contra `/opt/sirhosp` (par
> `compose.yml` + `compose.prod.yml`, via container `web`) foi
> substituído pela suíte de agendamento da reconciliação de saídas da
> **seção 5b** (runner one-shot `historical_recovery` do
> `compose.hospital.yml`, agendado por systemd em `America/Bahia`). O par
> legado `sirhosp-discharges.{service,timer}` do repositório foi
> reescrito para o novo contrato horário e `discharges-scheduler.sh`
> permanece no repositório **apenas como referência histórica**: não
> instale, não habilite e não agende nada desta seção.

---

## 5b. Reconciliação de saídas — agendamento systemd e runbook (RPSA-S12)

Esta seção descreve a suíte de agendamento **desabilitada por padrão** da
reconciliação de saídas no servidor hospitalar (`/srv/apps/prisma`, sem clone
do repositório). A execução usa o runner one-shot `historical_recovery` do
`compose.hospital.yml` (RPSA-S11) e os comandos `run_exit_reconciliation_runtime`
(modos `hourly`/`d1`/`catchup`) e `reconcile_stale_admissions`. Toda automação
da fonte executa pelo perfil `recovery` com `run --rm` — **nunca** pelo serviço
`web` e **nunca** pelo comando legado `process_discharge_pdf` (o PDF não é
agendado em hipótese alguma). A ativação exige smoke test e benchmarks
documentados abaixo; instalar os arquivos nunca habilita nem inicia nada.

### 5b.1 Agendamentos (America/Bahia, offsets fixos sem aleatorização de disparo)

| Timer | Modo do script | Agendamento (`OnCalendar`) | `Persistent` | O que executa |
| --- | --- | --- | --- | --- |
| `sirhosp-historical-recovery.timer` | `d1-recovery` | `OnCalendar=*-*-* 05:00:00 America/Bahia` | `true` | D-1 (dia anterior em `America/Bahia`) com os quatro extratores na ordem canônica `discharges, admissions, deaths, official_census` via `run_exit_reconciliation_runtime --mode d1`. |
| `sirhosp-discharges.timer` | `hourly-discharges` | `OnCalendar=*-*-* *:13:00 America/Bahia` | `true` | Altas do dia corrente via `run_exit_reconciliation_runtime --mode hourly` (13 minutos após cada hora). |
| `sirhosp-stale-reconciliation.timer` | `stale-sweep` | `OnCalendar=*-*-* *:47:00 America/Bahia` | `true` | Varredura horária limitada de internações órfãs via `reconcile_stale_admissions` (lock advisory próprio, enfileira no máximo 100 confirmações, sem Playwright). |

`America/Bahia` no literal `OnCalendar=` torna os agendamentos independentes do
fuso do host. Os offsets fixos 05:00 / :13 / :47 (sem aleatorização de disparo) mantêm
os lançamentos Playwright agendados afastados entre si; a verificação de fila,
batch aberto e locks é a segunda linha de defesa (RPSA-S11).

### 5b.2 Artefatos, instalação e baseline desabilitado

A mesma release imutável (mesma tag) entrega `compose.hospital.yml`, o runbook
específico da versão, o script `deploy/exit-reconciliation-scheduler.sh` e os
seis units de `deploy/systemd/` (3 services + 3 timers). O workflow de release
anexa todos esses assets antes da publicação; a tag e os assets não podem mais
ser alterados depois.

Instalação no servidor hospitalar (exemplo sintético com a tag `v1.0.0-rc.N`;
troque pela tag exata publicada):

```bash
cd /srv/apps/prisma

# Baixa o script e os seis units da mesma tag da release imutável
curl -fL -O \
  "https://github.com/carlosapgomes/sirhosp/releases/download/v1.0.0-rc.N/exit-reconciliation-scheduler.sh"
mkdir -p deploy/systemd
for unit in sirhosp-discharges.service sirhosp-discharges.timer \
  sirhosp-historical-recovery.service sirhosp-historical-recovery.timer \
  sirhosp-stale-reconciliation.service sirhosp-stale-reconciliation.timer; do
  curl -fL -o "deploy/systemd/${unit}" \
    "https://github.com/carlosapgomes/sirhosp/releases/download/v1.0.0-rc.N/${unit}"
done
chmod +x exit-reconciliation-scheduler.sh
mv exit-reconciliation-scheduler.sh deploy/

# Copia os units para o systemd (NÃO habilita nem inicia nada)
sudo install -m 0644 deploy/systemd/*.service deploy/systemd/*.timer \
  /etc/systemd/system/
systemctl daemon-reload
```

**Baseline desabilitado:** os services são `Type=oneshot`, com saída em journal
e `SyslogIdentifier` próprio, sem `Restart=`; os timers só disparam após
`systemctl enable`. Não existem arquivos de preset. Confirme que nada foi
ativado na primeira instalação:

```bash
systemctl is-enabled sirhosp-discharges.timer \
  sirhosp-historical-recovery.timer sirhosp-stale-reconciliation.timer
systemctl list-timers --all | grep -E 'sirhosp-(discharges|historical-recovery|stale-reconciliation)' || true
```

A saída esperada é `disabled` até a ativação explícita da seção 5b.3. Execuções
manuais de validação usam `systemctl start sirhosp-<nome>.service` (oneshot);
nenhum destes passos liga o agendamento.

### 5b.3 Ativação: smoke test D-1 manual e enablement

Deploy, validação manual e ativação de timers são **checkpoints separados**.
Antes de habilitar o timer de D-1, execute um smoke test manual com os quatro
extratores para a data anterior em `America/Bahia` e confira sucesso e
contadores agregados de reconciliação:

```bash
cd /srv/apps/prisma
docker compose --env-file .env -f compose.hospital.yml --profile recovery run \
  --rm historical_recovery uv run --no-sync python manage.py \
  run_exit_reconciliation_runtime --mode d1
```

Somente depois do smoke test dos quatro extratores, habilite o timer de D-1:

```bash
sudo systemctl enable --now sirhosp-historical-recovery.timer
systemctl list-timers sirhosp-historical-recovery.timer
```

O timer horário de altas só deve ser habilitado depois da aprovação do
benchmark horário (seção 5b.4):

```bash
sudo systemctl enable --now sirhosp-discharges.timer
```

A varredura de segurança (`sirhosp-stale-reconciliation.timer`) é livre de
Playwright e pode ser habilitada após o smoke test de D-1 e observação da fila
drenada; mantenha os demais timers desabilitados até os respectivos gates.

### 5b.4 Gates de benchmark independentes e calibração

As aprovações de benchmark **horário** e de **catch-up de sete datas** são
**independentes** entre si:

- Aprovação do benchmark horário é pré-condição para habilitar
  `sirhosp-discharges.timer` (extração horária de altas do dia corrente).
- Aprovação do benchmark de catch-up (até sete datas, quatro extratores) é
  pré-condição para execução de catch-up multi-data autorizada pelo operador.
  Enquanto não aprovado, o planejamento automático permanece **somente D-1**;
  nada agenda catch-up automaticamente e lacunas maiores que sete datas param
  antes da extração, reportando apenas contagem e limites agregados.

Benchmarks são executados com `benchmark_exit_reconciliation_runtime`
(fixtures sintéticas; nunca contra produção):

```bash
cd /srv/apps/prisma
docker compose --env-file .env -f compose.hospital.yml --profile recovery run \
  --rm historical_recovery uv run --no-sync python manage.py \
  benchmark_exit_reconciliation_runtime --mode hourly
docker compose --env-file .env -f compose.hospital.yml --profile recovery run \
  --rm historical_recovery uv run --no-sync python manage.py \
  benchmark_exit_reconciliation_runtime --mode catchup
```

#### Calibração de limiares de benchmark

Os limiares abaixo são defaults seguros e **documentados como placeholders**
aguardando calibração com carga real (nota RPSA-S11):

| Threshold | Default horário | Default catch-up |
| --- | ---: | ---: |
| `max_latency_seconds` | `30.0` | `300.0` |
| `max_error_rate` | `0.10` | `0.10` |
| `max_db_seconds` | `15.0` | `180.0` |
| `max_queue_depth` | `0` | `0` |

Caveat de calibração da fila: `max_queue_depth` avalia a fila **residual**
amostrada após o fechamento dos serviços síncronos, e não o pico
(`peak_active`) rastreado durante a execução — o limiar não detecta impacto
transitório ativo. Ao calibrar, meça também o pico observado e documente a
decisão de elevar o limiar com base na medição residual, não no placeholder.

### 5b.5 Contenção: exit 75, locks e limites

Quando a fila de ingestão não está drenada ou existe batch de censo aberto, o
runtime de modo fonte sai com o código fixo **75** (`EX_TEMPFAIL`) antes de
lançar Playwright. O **script** `exit-reconciliation-scheduler.sh` retenta
somente esse código, com bound fixo de **seis invocações no total** (tentativa
inicial mais no máximo cinco retries) e intervalo fixo de **600 segundos
(10 minutos)** entre tentativas — o script nunca excede esse limite e os
valores não são configuráveis. Qualquer outro código de saída diferente de zero
falha imediatamente. Não existe loop infinito e os units não possuem `Restart=`
para falhas — a contenção é resolvida no script, dentro do bound, e depois
disso a falha é definitiva e observável no journal.

Se um runtime equivalente já estiver ativo, o lock advisory falha e a execução
sai **0** com `result=skip` (sem duplicar trabalho). As guardas:

- fila drenada e sem batch de censo aberto antes de Playwright (modos fonte);
- locks advisory de sessão distintos: orquestrador de censo
  (`ADVISORY_LOCK_KEY`), varredura de órfãs (`STALE_ADMISSION_SWEEP_LOCK_KEY`),
  discharge horária (`HOURLY_LOCK_KEY`) e recuperação histórica D-1/catch-up
  (`RECOVERY_LOCK_KEY`);
- offsets fixos dos timers (seção 5b.1) afastam lançamentos Playwright
  agendados; sobreposição manual residual permanece monitorada.

Inspeção da contenção:

```bash
journalctl -u sirhosp-historical-recovery.service -n 200 --no-pager
journalctl -u sirhosp-discharges.service -n 200 --no-pager
journalctl -u sirhosp-stale-reconciliation.service -n 200 --no-pager
```

Nas linhas de log, `result=busy ... exit_code=75 attempt=N/6` identifica a
tentativa corrente dentro do bound de seis invocações totais (linha impressa
antes de cada nova tentativa, após o intervalo fixo de 600 s) e
`result=failed exit_code=<código>` marca a falha definitiva.

### 5b.6 Monitoramento (RPSA-S10)

A seção 6.1 documenta `check_ingestion_pipeline_health` com as **quatro opções**
de reconciliação do RPSA-S10 (`--missing-dates-max`, `--backlog-age-max-hours`,
`--conflict-max-count`, `--duplicate-max-count`) e seus defaults, além do
comando diário `report_admission_reconciliation_integrity`. A saída é
estritamente agregada e read-only (nunca identidade de paciente, texto clínico,
credenciais ou corpo de CSV). Use o relatório diário de integridade como
verificação periódica; falhas retornam exit 1 com códigos fixos. Os logs de
cada execução agendada da seção 5b.1 permanecem agregados (contadores, status,
datas e reasons seguros).

### 5b.7 Runbook de backfill autorizado (RPSA-S9)

Backfill em produção é uma **operação separada e explicitamente autorizada**;
nunca parte do deploy ou do agendamento. Plano e apply usam
`reconcile_admission_history` (dry-run por padrão) e `rollback_admission_reconciliation`.
Cohorts na ordem determinística: duplicatas confirmadas na fonte, altas com data
exata, óbitos com data/hora completas; ambiguidades apenas contadas para
revisão. Saída sempre agregada.

Procedimento autorizado:

1. **Backup:** crie backup local com timestamp do PostgreSQL e registre a
   referência (`--backup-ref`), nunca um caminho vazio.
2. **Plano em dry-run:** revise contagens por cohort e limites antes de aplicar.
   Atenção: `--limit` acima do cap de apply não é rejeitado em dry-run — o
   preview pode exceder o que o apply aceitaria; mantenha o dry-run dentro do
   cap.
3. **Identificação:** `--label` obrigatório, identificando a operação.
4. **Canário 50:** o primeiro apply de um histórico sem lotes anteriores aceita
   no máximo 50 itens (`--apply --limit 50`); lotes seguintes sobem até o
   máximo de **100** por lote.
5. **Gate do cohort de duplicatas:** a confirmação de fonte deste cohort é
   **derivada** do par (proxy de frescor `closed.updated_at >= open.updated_at`),
   não uma confirmação independente da fonte. Antes de aplicar o cohort de
   duplicatas, exija **sincronização `admissions_only` prévia** que renove o
   catálogo de internações dos pares afetados e/ou **revisão operador
   par-a-par** pela ferramenta protegida de revisão.
6. **Rollback:** para reverter um lote, use `rollback_admission_reconciliation
   --batch <uuid>` (valida o estado posterior de todos os itens e reverte
   atomicamente na ordem inversa) ou `--operation <uuid>` para uma operação.
   Assimetria documentada: o rollback reverte o estado das internações e anexa
   eventos inversos, mas as linhas de `DischargeRecord`/`DeathRecord` continuam
   `reconciled`; um item revertido não é replanejado, e um replay posterior da
   mesma evidência **reconcilia e fecha novamente** a internação.
7. **Cap pós-rollback:** eventos inversos reutilizam o `batch_uuid` do lote
   original — um primeiro canário totalmente revertido ainda conta como lote
   registrado e o cap permanece 100 (conservador por desenho).

Exemplos sintéticos (não executar sem autorização):

```bash
docker compose --env-file .env -f compose.hospital.yml exec -T web \
  uv run --no-sync python manage.py reconcile_admission_history \
  --backup-ref "sirhosp-2026-09-06T030000Z.dump" --label "saneamento-RPSA-S12" \
  --apply --limit 50
```

### 5b.8 Desativação e rollback dos timers

Desativar um agendamento não apaga dados nem altera o runtime:

```bash
sudo systemctl disable --now sirhosp-historical-recovery.timer
sudo systemctl disable --now sirhosp-discharges.timer
sudo systemctl disable --now sirhosp-stale-reconciliation.timer
systemctl list-timers --all | grep sirhosp || true
```

Rollback completo da suíte (remoção das unidades):

```bash
sudo systemctl disable --now \
  sirhosp-historical-recovery.timer sirhosp-discharges.timer \
  sirhosp-stale-reconciliation.timer 2>/dev/null || true
sudo rm -f /etc/systemd/system/sirhosp-historical-recovery.{service,timer} \
  /etc/systemd/system/sirhosp-discharges.{service,timer} \
  /etc/systemd/system/sirhosp-stale-reconciliation.{service,timer}
systemctl daemon-reload
```

### 5b.9 Restrições operacionais (sem cron, sem PDF, legado deprecado)

- **Sem cron:** nenhuma entrada em cron (root ou de container) pode duplicar
  recuperação D-1, extração horária de altas ou varredura de órfãs; um único
  agendador canônico (systemd) é dono de cada responsabilidade periódica.
- **PDF nunca agendado:** `process_discharge_pdf` está inativo e **nunca** é
  agendado por timer, cron ou runbook.
- **Legado deprecado:** `discharges-scheduler.sh` e o antigo contrato 3x/dia
  (seção 4b) estão deprecados e não devem ser instalados; o par
  `sirhosp-discharges.{service,timer}` reescrito na seção 5b.1 é o dono atual
  do agendamento de altas.
- **Sem clone:** a operação usa somente assets da release imutável sob
  `/srv/apps/prisma`; não há `git pull` nem toolchain no servidor.

### 5b.10 Notas de coordenação (RPSA-S5 e RPSA-S8)

- **Janela varredura × orquestrador (RPSA-S5):** a varredura de :47
  (`reconcile_stale_admissions`) e a orquestração adaptativa de censo
  coordenam por locks advisory distintos; o enfileiramento usa dedup
  caller-side (query-then-insert), portanto permanece uma janela residual
  alcançável de trabalho ativo duplicado — aceita e consistente com o padrão
  existente; um guarda a nível de banco é considerada em slice posterior.
- **Eixo da série de sumários (RPSA-S8):** a segunda série do gráfico
  (sumários médicos por `alta_em`) é ancorada ao eixo de linhas agregadas e
  renderiza onde existem linhas de `DailyDischargeCount` — comportamento
  transicional (o refresh roda após cada extração); indicadores de saída usam
  `saida_em` em `America/Bahia` e óbitos não entram nas contagens de alta.

---

## 6. Healthcheck

```bash
# API health
curl http://localhost:8000/health/

# Status dos containers
docker compose -f compose.yml -f compose.prod.yml ps
```

### 6.1 Health check do pipeline de ingestão (RPAP-S5 e RPSA-S10)

O comando one-shot `check_ingestion_pipeline_health` avalia o pipeline
censo → internações → demografia → full-sync → evoluções com métricas
estritamente agregadas. É read-only: não cria, altera ou apaga linhas e
não chama Playwright, rede, subprocesso ou outro comando. A saída contém
apenas nomes de métricas, contagens, percentuais, durações arredondadas,
booleanos e reasons allowlisted — nunca identificadores de run/batch/
paciente/internação/evento, parâmetros, texto clínico, URL ou erro bruto.

- **Exit 0:** pipeline saudável na janela e nos limiares configurados.
- **`CommandError` (exit 1):** ao menos uma invariante/limiar falhou; a
  mensagem traz somente códigos fixos e contagens.

#### 6.1.1 Flags e interpretação

| Flag | Default | Significado |
| --- | ---: | --- |
| `--window-hours` | `24` | Janela de avaliação em horas (positivo). |
| `--settling-minutes` | `60` | Tempo mínimo após o fim do run de internações para exigir o full-sync correspondente (não negativo). |
| `--max-active-age-minutes` | `120` | Idade máxima da run queued/running mais antiga entre intents suportados (positivo). |
| `--max-full-sync-failure-percent` | `20.0` | Percentual máximo de falhas terminais de full-sync (0..100). |
| `--min-full-sync-terminal-sample` | `5` | Amostra mínima terminal para a taxa alarmar (positivo). |
| `--max-movement-age-hours` | desligado | Alarme de frescor da última `PatientMovement` (positivo quando ativo). |
| `--max-admission-age-hours` | desligado | Alarme de frescor da última atualização de `Admission` (positivo quando ativo). |
| `--max-event-age-hours` | desligado | Alarme de frescor do último `ClinicalEvent` (positivo quando ativo). |
| `--missing-dates-max` (RPSA-S10) | `7` | Datas de extração de altas ausentes/incompletas aceitas antes do alarme de ação operacional (não negativo). |
| `--backlog-age-max-hours` (RPSA-S10) | `48` | Idade máxima da evidência de reconciliação `pending`/`ambiguous` mais antiga (positivo). |
| `--conflict-max-count` (RPSA-S10) | `0` | Evidências de reconciliação `conflict` toleradas (não negativo). |
| `--duplicate-max-count` (RPSA-S10) | `0` | Pares de internações duplicadas confirmados pela fonte tolerados (não negativo). |

Invariantes batch-bound (qualquer contagem positiva torna unhealthy):

- `empty_success` — run `admissions_only` batch-bound succeeded com
  `admissions_seen=0` na janela;
- `missing_full_sync` — run `admissions_only` batch-bound succeeded não
  vazio, encerrado há mais de `--settling-minutes`, sem
  `full_sync`/`full_admission_sync` no mesmo batch+patient;
- `duplicate_demographics` — mais de um `demographics_only` batch-owned
  para o mesmo batch+patient na janela.

Limiares:

- `active_queue_age` — a run queued/running suportada mais antiga excede
  `--max-active-age-minutes`;
- `full_sync_failure_rate` — amostra terminal ≥
  `--min-full-sync-terminal-sample` e percentual de falhas acima de
  `--max-full-sync-failure-percent`; abaixo da amostra mínima o percentual
  é informativo e não altera o exit;
- `movement_freshness`, `admission_freshness`, `event_freshness` — ativados
  somente quando a flag correspondente é fornecida; ausência do dado com a
  flag ativa também é unhealthy.

#### 6.1.2 Timer systemd (canário contínuo)

**Instalação de produção (variant Docker, instalada em `eon` em
2026-08-29, release `v0.1.0-rc.15`):** a aplicação roda em Docker Compose,
portanto o health check executa dentro do container `web` a partir do
diretório de instalação:

```ini
# /etc/systemd/system/sirhosp-ingestion-health.service (produção eon)
[Unit]
Description=SIRHOSP ingestion pipeline health check (canary 6.1.2)
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/srv/apps/prisma
ExecStart=/usr/bin/docker compose --env-file .env -f compose.hospital.yml \
    exec -T web uv run --no-sync python manage.py \
    check_ingestion_pipeline_health \
    --max-movement-age-hours 12 --max-event-age-hours 24
TimeoutStartSec=900
```

```ini
# /etc/systemd/system/sirhosp-ingestion-health.timer (produção eon)
[Unit]
Description=Run SIRHOSP ingestion health check hourly

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

Ativação e observação (saída agregada fica no journald):

```bash
systemctl daemon-reload
systemctl enable --now sirhosp-ingestion-health.timer
systemctl list-timers sirhosp-ingestion-health.timer
systemctl start sirhosp-ingestion-health.service   # validação manual
journalctl -u sirhosp-ingestion-health.service -n 20
```

**Variante genérica (instalações sem Docker):** ajuste apenas o `ExecStart`
para o ambiente local, por exemplo:

```ini
# variante host (não usada na produção hospitalar atual)
[Service]
Type=oneshot
ExecStart=/usr/local/bin/uv run --no-sync python \
    manage.py check_ingestion_pipeline_health \
    --max-movement-age-hours 12 --max-event-age-hours 24
```

O exit code 1 é o sinal de alarme: pode alimentar `OnFailure=` de um
service wrapper ou qualquer monitoramento já existente. **Provider de
alerta (e-mail, webhook, Prometheus) fica fora do escopo deste change** e
não é configurado aqui.

#### 6.1.3 Canário, recuperação, drenagem, stop e rollback

- **Canário:** rode o comando por 1–2 semanas em paralelo ao fluxo normal
  antes de alarmar. Falso positivo esperado de `missing_full_sync` em
  janela curta é evitado com `--settling-minutes`; taxa em amostra pequena
  é evitada elevando `--min-full-sync-terminal-sample`.
- **Recuperação:** quando `empty_success`/`missing_full_sync` alarmarem
  após um ciclo, planeje primeiro com dry-run (sem mutação):

  ```bash
  docker compose -f compose.yml -f compose.prod.yml exec -T web \
    uv run --no-sync python manage.py recover_current_census_admissions
  ```

  Aplique em lotes pequenos e reavalie entre lotes:

  ```bash
  docker compose -f compose.yml -f compose.prod.yml exec -T web \
    uv run --no-sync python manage.py recover_current_census_admissions \
    --apply --limit 20
  ```

- **Drenagem:** acompanhe `queue: active=` e `oldest_age_minutes=` na
  saída do health check; um batch saudável drena com fila em zero e sem
  `empty_success`/`missing_full_sync` novos.
- **Stop conditions:** pare o apply se a fila ativa persistir acima do
  limiar, se novas `empty_success` surgirem após o apply ou se
  `full_sync_failure_rate` subir após a recuperação.
- **Rollback:** nenhum run histórico é reaberto; a recuperação cria runs
  novos em batch próprio. Para reverter, basta não enfileirar novos lotes
  e aguardar a drenagem; o health check permanece diagnóstico (read-only)
  durante todo o processo.

#### 6.1.4 Rollout canário do reconhecimento de atendimentos (PFIF-S5)

Procedimento **somente agregado** para ativar o reconhecimento de
`Atendimentos` em produção. Nenhuma etapa lista run, batch, paciente,
data de atendimento ou profissional; toda observação usa o health check
e a página de métricas, que exibem apenas contagens e rótulos fechados.

**Baseline (24 horas antes do rollout):** com a imagem atual ainda em
execução, registre por 24 h a saída horária do health check e os cartões
de métricas de ingestão (falhas por intent, taxa de timeout, fila). Estes
números são a linha de base comparativa; não os reclassifique depois.

```bash
docker compose --env-file .env -f compose.hospital.yml exec -T web \
  uv run --no-sync python manage.py check_ingestion_pipeline_health
```

**Canário (um worker, um ciclo completo):** atualize a imagem de
apenas um worker persistente (placeholder `WORKER_CANARIO` no Compose)
e deixe-o processar exatamente um ciclo completo de censo, sem escalar
para os demais workers.

```bash
docker compose --env-file .env -f compose.hospital.yml up -d WORKER_CANARIO
docker compose --env-file .env -f compose.hospital.yml logs --since 1h WORKER_CANARIO
```

**Critérios de avanço (todos obrigatórios, comparando com o baseline):**

- `recognized_recent_encounter` sobe e `empty_success` permanece `0` na
  saída do health check;
- o percentual de `invalid_payload` em runs `admissions_only` cai na
  página de métricas;
- taxa de timeout de full-sync e idade de fila (`oldest_age_minutes`)
  não pioram em relação ao baseline;
- logs do worker canário permanecem sanitizados (sem HTML, URL do
  legado, profissional ou dado de paciente).

**Critérios de parada (qualquer um interrompe o canário imediatamente):**

- qualquer `empty_success` novo ou contador de outcome desconhecido;
- timeout ou fila crescendo além do baseline;
- qualquer saída sensível (identificador, texto clínico, HTML, cookie)
  em logs ou no health check;
- instabilidade da sessão persistente do worker (reinicios repetidos).

**Rollback:** reverta a imagem do worker canário para a anterior. Runs,
stages e batches já persistidos NÃO são reescritos, reclassificados ou
apagados: o outcome fechado no stage metric permanece auditável e é
inócuo para a imagem antiga.

```bash
docker compose --env-file .env -f compose.hospital.yml up -d --no-deps \
  --force-recreate WORKER_CANARIO
```

**Proibido durante o canário:** requeue de runs, backfill, reprocesso
manual de batch e qualquer reclassificação manual de histórico. O
reconhecimento vale somente para execuções novas; evidências antigas
nunca são reavaliadas em massa.

#### 6.1.5 Relatório diário de integridade da reconciliação (RPSA-S10)

O comando one-shot `report_admission_reconciliation_integrity` executa a
mesma avaliação read-only compartilhada com a configuração padrão e
renderiza o bloco de reconciliação (RPSA-S10): cobertura durável de
extração de altas com zero confirmado, lacunas e limites, idade do backlog
por grupo de status (`pending`/`ambiguous`/`conflict`/casos órfãos abertos),
evidencias `conflict`, pares duplicados confirmados e a contagem de
internações canônicas abertas ausentes do último censo. Não enfileira
trabalho, não chama a fonte e não muta estado clínico; a saída carrega
somente datas, idades, nomes de grupos, contagens e limites — nunca
identificadores de paciente/internação/fonte, nomes, prontuários ou texto
clínico. Exit 0 quando saudável; `CommandError` (exit 1) quando alguma
violação dos limiares da seção 6.1.1 dispara, com mensagem de códigos
fixos e contagens.

Execução manual (hospitalar, read-only):

```bash
cd /srv/apps/prisma
docker compose --env-file .env -f compose.hospital.yml exec -T web \
  uv run --no-sync python manage.py report_admission_reconciliation_integrity
```

A cadência diária do comando é decisão do operador (por exemplo, um timer
próprio desabilitado por padrão junto aos timers da seção 5b); o comando é
seguro para execução repetida. O conteúdo dos limiares RPSA-S10 e seus
defaults vive na tabela 6.1.1 e no módulo `pipeline_health` (comentário
que referencia esta seção 6.1).

---

### 6.2 Caracterização da coorte fail-only de full-sync (CFC)

O change `characterize-fullsync-chronic-failures` é **diagnóstico
read-only**: nenhum comando deste change cria, altera ou apaga linhas,
não existe flag `--apply` e não há qualquer mutação em produção. Os
passos abaixo podem ser executados sob demanda, sem janela de
manutenção.

#### 6.2.1 Caracterização em produção (one-shot read-only)

**Pré-requisito de versão:** o command `characterize_fullsync_failures`
existirá em produção somente a partir da imagem `v0.1.0-rc.14` (o change
CFC é posterior à tag `v0.1.0-rc.13`). Antes de executar, confirme a
disponibilidade sem tocar dados:

```bash
docker compose --env-file .env -f compose.hospital.yml exec -T web \
  uv run --no-sync python manage.py help characterize_fullsync_failures \
  >/dev/null && echo AVAILABLE
```

Captura a saída agregada do command para um arquivo:

```bash
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py characterize_fullsync_failures \
  --window-hours 168 --min-attempts 3 > /tmp/cfc-characterization.txt
```

| Flag | Default | Significado |
| --- | ---: | --- |
| `--window-hours` | `168` | Janela de caracterização em horas (positivo). |
| `--min-attempts` | `3` | Mínimo de runs terminais por paciente para entrar na coorte fail-only (exclui ruído de alta recente). |
| `--max-per-stage-rows` | `5000` | Teto de segurança de linhas de perfil por estágio (positivo). |

Interpretação da saída: `cohort:` (pacientes fail-only, runs falhos,
mediana/máximo de tentativas, idade da primeira/última falha),
`cohort_failure_reasons:` e `contrast_failure_reasons:` (distribuição de
reasons da coorte e do contraste fail-then-ok), `stage_profiles:` e
`terminal_failing_stages:` (duração mediana/p90 por estágio e estágio
terminal falho) e `hourly_histogram:` (24 buckets por hora UTC). A saída
é estritamente agregada e o exit é sempre 0 quando a caracterização
completa — diagnóstico, não gate.

Exemplo systemd opcional (uma execução por dia):

```ini
# /etc/systemd/system/sirhosp-cfc-characterization.service
[Unit]
Description=SIRHOSP full-sync fail-only cohort characterization (read-only)

[Service]
Type=oneshot
ExecStart=/bin/bash -lc 'docker compose -f /opt/sirhosp/compose.yml -f /opt/sirhosp/compose.prod.yml exec -T web uv run --no-sync python manage.py characterize_fullsync_failures --window-hours 168 > /var/log/sirhosp/cfc-characterization.txt'
```

#### 6.2.2 Relatório e validação da ADR de decisão

Gera o relatório Markdown com as cinco seções fixas (coorte, reasons,
timing por estágio, histograma horário, contraste) e valida a ADR de
decisão por regras objetivas (veredito com evidência, recomendação
presente, zero identidade/conteúdo clínico):

```bash
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py generate_fullsync_failure_report \
  --input /tmp/cfc-characterization.txt \
  --output /tmp/cfc-characterization-report.md \
  --check-adr docs/adr/ADR-0008-fullsync-failure-characterization-decision.md
```

O gerador falha fechado (exit 1, mensagem sanitizada) se a entrada
contiver sentinela de identidade ou estiver malformada.

#### 6.2.3 Laboratório sintético (fora de produção)

Pré-requisitos: `uv sync` e Python 3.12. O harness usa apenas fakes
duck-typed e dados 100% sintéticos — nenhum browser, nenhuma rede,
nenhum dado real.

```bash
PYTHONPATH=/app uv run --no-sync python \
  automation/lab/playwright_experiments/fullsync_failure_lab.py \
  --output /tmp/cfc-verdicts.json
```

Artefatos: `verdicts.json` (consolidado, com sentinela sintética e um
veredito por experimento H1/H2) e as fixtures em
`automation/lab/playwright_experiments/fixtures/` (conteúdo e bloco de
relatório sintéticos). O harness nunca é importado por código
operacional (`apps/`).

**Sem mutação:** este change não possui flag `--apply` nem qualquer
comando de escrita; caracterização, relatório, validação e laboratório
são read-only e não enfileiram, reabrem ou alteram runs de produção.

### 6.3 Correção do esgotamento de tentativas de full-sync (FX)

O change `fix-fullsync-failure-exhaustion` corrige a queima de tentativas
da coorte fail-only de full-sync (causa registrada na ADR-0008) sem mudar
taxonomia, mensagens persistidas, limiares ou contratos do health check.
Não há comando novo, nem contrato novo, nem flag `--apply`: a observação
pós-rollout usa somente os comandos das seções 6.1 e 6.2.

#### 6.3.1 O que mudou operacionalmente

1. **Fail-fast de payload determinístico:** falhas com reason
   `invalid_payload` (validação determinística de payload) terminam o run
   `failed` na primeira tentativa, registram `FinalRunFailure`
   (`attempts_exhausted` refletindo a contagem corrente) e fecham o batch
   — sem requeue. A decisão vem da política pura
   `should_retry_failure_reason`, aplicada pelos dois workers
   (`process_ingestion_runs` e
   `process_ingestion_runs_persistent_session`); `timeout` e demais
   reasons mantêm o retry com backoff de +60s (inalterado).
2. **Orçamento por volume no worker persistente:** a extração de
   evoluções por janela de gap usa `evolution_window_budget_seconds`
   (base 120s + 2s por dia de span da janela, teto 600s) em vez do
   `timeout=120` fixo. Janelas curtas ficam inalteradas (base 120s);
   janelas longas legítimas ganham tempo proporcional; volume acima do
   teto continua falhando `timeout` (comportamento bounded preservado).
   O worker clássico mantém o orçamento fixo (fora da topologia de
   produção; backlog documentado no design do change).

#### 6.3.2 Como observar após o rollout

A correção entra em vigor quando a imagem com o change é implantada; antes
do rollout, os agregados servem de baseline (canário da seção 6.1.3). Use
os comandos existentes:

- **Health check (`check_ingestion_pipeline_health`, seção 6.1):** o campo
  `full_sync_failure_reasons` deve passar a mostrar menos tentativas para
  `invalid_payload` (fail-fast na 1ª tentativa) e `failure_percent` deve
  cair à medida que a queima semanal de tentativas reduz.
- **Caracterização (`characterize_fullsync_failures`, seção 6.2):** os
  agregados `attempts_median` e `attempts_max` da coorte fail-only devem
  cair após o rollout (runs determinísticos terminam com 1 tentativa) e
  os runs fail-fast aparecem com `FinalRunFailure.attempts_exhausted=1`.
- **Stage metrics (seção 6.2):** para janelas longas legítimas, a duração
  mediana/p90 de `evolution_extraction` pode subir até o teto de 600s —
  o esperado é que o p90 convirja para valores abaixo do teto conforme
  as janelas longas deixam de estourar o orçamento fixo.

**Rollback e escopo:** a correção é exclusivamente de comportamento dos
workers; reverter a imagem para a versão anterior restaura o retry cego e
o orçamento fixo. Nenhum run histórico é mutado ou reaberto por esta
correção.

## 7. Stale ingestion run recovery

### 7.1 Why job-level stale recovery exists

O orquestrador adaptativo de censo pode ficar bloqueado
indefinidamente quando uma única `IngestionRun` permanece em
`running` após o worker morrer ou perder o controle do job.
Um job abandonado não deve impedir 4-5 ciclos de censo por dia.

### 7.2 Heartbeat and worker life signal

O worker de ingestão atualiza `worker_heartbeat_at` no banco a
cada 60 segundos enquanto processa uma `IngestionRun`. Este
heartbeat é a fonte de verdade sobre a atividade do worker —
não depende de PID, Docker socket ou acesso ao processo do
container. O orquestrador no host (systemd) lê o heartbeat
diretamente no PostgreSQL mesmo com workers em Docker
rootless.

- **Intervalo de heartbeat:** 60 segundos
- **Margem de heartbeat stale:** 10 minutos
  (`--heartbeat-grace-minutes 10`)

### 7.3 Default stale limits by intent

Cada `intent` possui um limite de idade individual diferente:

| Intent | Limite stale |
| --- | ---: |
| `admissions_only` | 20 min |
| `demographics_only` | 20 min |
| `full_sync` | 60 min |
| `census_extraction` | 120 min |
| vazio/desconhecido | 60 min |

Uma run é candidata a stale quando:

1. `status = 'running'`
2. Idade individual > limite por `intent`
3. `worker_heartbeat_at` ausente ou mais antigo que 10 min

### 7.4 Heartbeat grace and sweep circuit breaker

- **Heartbeat grace** (`--heartbeat-grace-minutes`, default 10):
  uma run com heartbeat mais recente que este valor é
  considerada ativa.
- **Circuit breaker** (`--max-runs-per-sweep`, default 20): se
  o número de candidatos exceder este limite, a execução
  aborta sem mutar dados e emite alerta operacional. Isso
  protege contra falsos positivos em massa durante falha
  sistêmica.

### 7.5 Dry-run command (manual inspection)

```bash
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py recover_stale_ingestion_runs --dry-run
```

Exibe candidatos sem alterar o banco: run IDs, intents, idade,
worker_label, heartbeat. A saída contém apenas identificadores
operacionais, nunca nomes de pacientes ou dados clínicos.

Parâmetros opcionais:

```bash
# Sobrescrever limites por intent
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py recover_stale_ingestion_runs --dry-run \
  --heartbeat-grace-minutes 15 \
  --max-runs-per-sweep 50 \
  --default-limit-minutes 120
```

### 7.6 Apply command (manual intervention)

```bash
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py recover_stale_ingestion_runs --apply
```

Marca runs candidatas como `failed` terminal:

- `status = 'failed'`
- `finished_at = now()`
- `timed_out = True`
- `failure_reason = 'timeout'`
- `next_retry_at = None`
- `error_message` seguro (run_id, intent, age, limit)

Não faz requeue automático. Fecha o batch se a fila do batch
drenar.

### 7.7 Orchestrator loop integration

Em modo `--loop`, o orquestrador
`run_adaptive_census_cycles` executa stale recovery
automaticamente **antes** de verificar elegibilidade da fila.
Isso significa que runs abandonadas são limpas antes de
decidir se um novo ciclo de censo pode começar.

**Comportamento padrão (recomendado para produção):** stale
recovery ativo no loop. O systemd unit
`sirhosp-census-orchestrator.service` já opera com recovery
habilitado.

**Desabilitar recovery temporariamente:**

```bash
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py run_adaptive_census_cycles --loop \
  --disable-stale-recovery
```

Uso típico: durante diagnóstico de falha sistêmica, para
evitar que o circuit breaker dispare repetidamente.

### 7.8 Terminal failed semantics (no requeue)

Uma run marcada como `failed` pelo stale recovery é terminal:

- A perda é de **um job**, não do batch inteiro.
- O batch pode fechar e liberar o próximo ciclo de censo.
- Não há requeue automático. Pacientes perdidos serão
  reenfileirados pelo próximo censo se ainda estiverem ativos.

### 7.9 Safe rollback / disable procedure

1. **Desabilitar recovery no orquestrador:** adicione
   `--disable-stale-recovery` ao `ExecStart` do systemd unit
   e recarregue:

   ```bash
   systemctl daemon-reload
   systemctl restart sirhosp-census-orchestrator.service
   ```

2. **Parar uso manual do comando:** simplesmente não execute
   `recover_stale_ingestion_runs --apply`.

3. **Reverter heartbeat:** a coluna `worker_heartbeat_at` é
   nullable e não afeta outras operações. Pode permanecer no
   schema sem uso.

4. **Monitorar:** com recovery desabilitado, runs abandonadas
   voltam a bloquear o orquestrador. O troubleshooting da
   seção 8 se aplica.

---

## 8. Troubleshooting

| Problema | Verificação |
| --- | --- |
| Orquestrador não inicia | `journalctl -u sirhosp-census-orch -n 30`: fila |
| Stale running detected | `IngestionRun` `running` > 3h; ver seção 7 |
| Stale recovery circuit breaker | Comando abortou sem mutar; ver workers/logs |
| Extração de censo falha | `docker compose logs web`: credenciais |
| Altas não extrai | `journalctl -u sirhosp-discharges -n 30`: credenciais |
| Worker não processa | `docker compose logs worker`: fila, conexão DB |
| Container não sobe | `docker compose logs web`: `.env`, secrets, porta |
| Lock preso no orquestrador | Lock advisory liberado ao fechar sessão DB |
