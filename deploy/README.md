# Deploy — SIRHOSP

<!-- markdownlint-disable MD040 MD060 MD031 -->

Instruções para deploy em produção e ativação do agendamento automático de censo.

---

## 1. Pré-requisitos

- Linux com **systemd** (Ubuntu 20.04+, Debian 11+, RHEL 8+)
- **Docker** e Docker Compose instalados
- Credenciais do sistema fonte configuradas no `.env`:
  ```
  SOURCE_SYSTEM_URL=https://...
  SOURCE_SYSTEM_USERNAME=...
  SOURCE_SYSTEM_PASSWORD=...
  ```

---

## 2. Estrutura de diretórios no servidor

```
/opt/sirhosp/
├── compose.yml              ← db
├── compose.prod.yml          ← web (Gunicorn) + worker
├── .env                      ← credenciais e secrets
├── deploy/
│   ├── census-scheduler.sh   ← script de extração + processamento
│   └── systemd/
│       ├── sirhosp-census.service
│       └── sirhosp-census.timer
└── ...
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

## 4. Ativar agendamento automático do censo

O censo hospitalar é extraído a cada **8 horas** (00:00, 08:00, 16:00)
via systemd timer. O ciclo executa dois passos:

1. `extract_census` — Playwright extrai dados do sistema fonte
2. `process_census_snapshot` — cria/atualiza pacientes e enfileira extrações

O worker (já rodando no container) processa as extrações enfileiradas automaticamente.

### 4.1 Instalar o script

```bash
# Tornar executável
chmod +x /opt/sirhosp/deploy/census-scheduler.sh

# Testar manualmente (opcional, valida credenciais)
/opt/sirhosp/deploy/census-scheduler.sh
```

### 4.2 Instalar units do systemd

```bash
# Copiar units para o systemd
cp /opt/sirhosp/deploy/systemd/sirhosp-census.service /etc/systemd/system/
cp /opt/sirhosp/deploy/systemd/sirhosp-census.timer /etc/systemd/system/

# Recarregar configuração
systemctl daemon-reload

# Habilitar e iniciar o timer
systemctl enable --now sirhosp-census.timer

# Verificar status
systemctl status sirhosp-census.timer
systemctl list-timers --no-pager | grep sirhosp
```

### 4.3 Comandos úteis

```bash
# Ver próximo disparo
systemctl list-timers sirhosp-census.timer

# Disparar manualmente (para teste)
systemctl start sirhosp-census.service

# Ver logs do último ciclo
journalctl -u sirhosp-census.service -n 50 --no-pager

# Ver logs em tempo real
journalctl -u sirhosp-census.service -f

# Desabilitar agendamento
systemctl disable --now sirhosp-census.timer

# Ver histórico de execuções
journalctl -u sirhosp-census.service --output=short
```

---

## 5. Worker de ingestão

O worker já está configurado no `compose.prod.yml` com `--loop --sleep-seconds 5`.
Ele processa automaticamente os `IngestionRun` enfileirados pelo `process_census_snapshot`.

**Escalar workers** (paralelismo):

```bash
docker compose -f compose.yml -f compose.prod.yml up -d --scale worker=3
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

| Problema            | Verificação                                                                   |
| ------------------- | ----------------------------------------------------------------------------- |
| Censo não extrai    | `journalctl -u sirhosp-census.service -n 30` — ver credenciais, conectividade |
| Worker não processa | `docker compose logs worker` — ver fila, conexão DB                           |
| Container não sobe  | `docker compose logs web` — ver `.env`, secrets, porta ocupada                |
