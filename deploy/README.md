# Deploy — SIRHOSP

Instruções para deploy em produção, ativação do worker contínuo e do
orquestrador adaptativo de censo.

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

## 4b. Ativar agendamento automático de extração de altas

A extração de altas do dia é executada **3 vezes ao dia** (11:00, 19:00, 23:55)
via systemd timer. O ciclo consulta a página "Altas do Dia" do sistema fonte
e atualiza o campo `discharge_date` nas internações correspondentes, alimentando
o indicador "Altas (24h)" do dashboard.

### 4b.1 Instalar o script

```bash
# Tornar executável
chmod +x /opt/sirhosp/deploy/discharges-scheduler.sh

# Testar manualmente (opcional, valida conectividade)
/opt/sirhosp/deploy/discharges-scheduler.sh
```

### 4b.2 Instalar units do systemd

```bash
# Copiar units para o systemd
cp /opt/sirhosp/deploy/systemd/sirhosp-discharges.service /etc/systemd/system/
cp /opt/sirhosp/deploy/systemd/sirhosp-discharges.timer /etc/systemd/system/

# Recarregar configuração
systemctl daemon-reload

# Habilitar e iniciar o timer
systemctl enable --now sirhosp-discharges.timer

# Verificar status
systemctl status sirhosp-discharges.timer
systemctl list-timers --no-pager | grep sirhosp
```

### 4b.3 Comandos úteis

```bash
# Ver próximo disparo
systemctl list-timers sirhosp-discharges.timer

# Disparar manualmente (para teste)
systemctl start sirhosp-discharges.service

# Ver logs da última execução
journalctl -u sirhosp-discharges.service -n 50 --no-pager

# Ver logs em tempo real
journalctl -u sirhosp-discharges.service -f

# Desabilitar agendamento
systemctl disable --now sirhosp-discharges.timer
```

---

## 6. Healthcheck

```bash
# API health
curl http://localhost:8000/health/

# Status dos containers
docker compose -f compose.yml -f compose.prod.yml ps
```

---

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
