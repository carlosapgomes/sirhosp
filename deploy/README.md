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

## 5. Orquestrador adaptativo de censo

O censo hospitalar é extraído pelo **orquestrador adaptativo**, que monitora a
fila de ingestão e dispara `extract_census` + `process_census_snapshot` apenas
quando for seguro (fila drenada, cooldown respeitado, sem batch aberto).

Não há timer fixo: o orquestrador executa em modo contínuo
(`--loop`), dormindo entre verificações e aplicando backoff em caso de falha.

### 5.1 Executar como serviço systemd (recomendado para produção)

O arquivo `deploy/systemd/sirhosp-census-orchestrator.service` é um serviço
long-running, **não** um timer `OnCalendar`.

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

### 5.2 Executar em foreground (debug / testes)

```bash
cd /opt/sirhosp

# Um ciclo (comportamento dry-run: diagnóstico, sem mutação)
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py run_adaptive_census_cycles --dry-run

# Um ciclo real
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py run_adaptive_census_cycles --once

# Modo contínuo (foreground)
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py run_adaptive_census_cycles --loop
```

### 5.3 Execução manual (fallback)

Caso o orquestrador não esteja disponível, o operador pode executar o ciclo
manualmente:

```bash
cd /opt/sirhosp

# Passo 1: extrair censo do sistema fonte
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py extract_census

# Passo 2: processar o snapshot (cria/atualiza pacientes, enfileira extrações)
docker compose -f compose.yml -f compose.prod.yml exec -T web \
  uv run --no-sync python manage.py process_census_snapshot
```

### 5.4 Comandos úteis

```bash
# Ver logs do orquestrador
journalctl -u sirhosp-census-orchestrator.service -n 50 --no-pager

# Ver logs em tempo real
journalctl -u sirhosp-census-orchestrator.service -f

# Parar o serviço
systemctl stop sirhosp-census-orchestrator.service

# Desabilitar o serviço
systemctl disable --now sirhosp-census-orchestrator.service
```

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

## 7. Troubleshooting

| Problema | Verificação |
| --- | --- |
| Orquestrador não inicia | `journalctl -u sirhosp-census-orch -n 30`: fila |
| Stale running detected | `IngestionRun` `running` > 3h; intervir |
| Extração de censo falha | `docker compose logs web`: credenciais |
| Altas não extrai | `journalctl -u sirhosp-discharges -n 30`: credenciais |
| Worker não processa | `docker compose logs worker`: fila, conexão DB |
| Container não sobe | `docker compose logs web`: `.env`, secrets, porta |
| Lock preso no orquestrador | Lock advisory liberado ao fechar sessão DB |
