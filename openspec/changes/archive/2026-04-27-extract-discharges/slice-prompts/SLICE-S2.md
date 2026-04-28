# SLICE-S2: Agendamento systemd + deploy script + documentação

> **Handoff para executor com ZERO contexto adicional.**
> Este documento é autocontido — não requer leitura de outros arquivos do projeto.
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares.
Extrai dados clínicos do sistema fonte hospitalar via web scraping (Playwright),
persiste em banco PostgreSQL paralelo, e oferece portal web Django.

**Pré-requisito**: O Slice S1 (`extract-discharges`) já foi implementado.
O comando `uv run python manage.py extract_discharges` está funcional e
registra `IngestionRun` com `intent="discharge_extraction"`.

---

## 2. O que este Slice faz

Criar a infraestrutura de agendamento automático para que a extração de altas
rode 3 vezes por dia sem intervenção manual:

1. Script bash que executa o management command dentro do container Docker
2. Unit `systemd` oneshot (`sirhosp-discharges.service`)
3. Timer `systemd` com OnCalendar (`sirhosp-discharges.timer`)
4. Atualizar `deploy/README.md` com instruções de instalação

Após este slice, o operador poderá instalar as units e o sistema começará a
popular `Admission.discharge_date` automaticamente.

---

## 3. Estrutura atual do projeto (relevante)

```text
sirhosp/
├── deploy/
│   ├── README.md                        ← (modificar — adicionar seção de discharges)
│   ├── census-scheduler.sh              ← referência de script bash
│   └── systemd/
│       ├── sirhosp-census.service       ← referência de unit
│       └── sirhosp-census.timer         ← referência de timer
├── compose.yml
├── compose.prod.yml
└── ...
```

---

## 4. Modelos de referência (NÃO modificar)

Nenhum modelo é alterado neste slice. Apenas arquivos de deploy.

Os modelos existentes (`Patient`, `Admission`, `IngestionRun`) são referenciados
pelo management command criado no Slice S1, mas você não vai interagir com eles
neste slice.

---

## 5. Convenções de código do projeto

- Scripts bash: `#!/usr/bin/env bash`, `set -euo pipefail`
- systemd units: `Type=oneshot`, timeouts generosos, logs via journal
- systemd timers: `OnCalendar=` com formato ISO, `Persistent=true`, `RandomizedDelaySec`
- `deploy/README.md`: comandos copiáveis, troubleshooting com tabela
- Markdown: válido para `markdownlint-cli2` (rodar `./scripts/markdown-lint.sh`)

---

## 6. O que EXATAMENTE criar

### 6.1 `deploy/discharges-scheduler.sh`

Script bash executado pelo systemd timer. Segue o mesmo padrão do
`deploy/census-scheduler.sh`.

```bash
#!/usr/bin/env bash
# =============================================================================
# SIRHOSP — Discharges Scheduler Script
#
# Executado pelo systemd timer 3x/dia (11:00, 19:00, 23:55).
# Extrai a lista de altas do dia do sistema fonte e atualiza
# Admission.discharge_date para os pacientes que receberam alta.
#
# Deploy: copiar para /opt/sirhosp/deploy/ e tornar executável.
# =============================================================================
set -euo pipefail

PROJECT_DIR="/opt/sirhosp"
COMPOSE_FILES=(-f compose.yml -f compose.prod.yml)
LOG_TAG="sirhosp-discharges"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "=== Iniciando extração de altas ==="

cd "$PROJECT_DIR" || {
    log "ERRO: diretório do projeto não encontrado: $PROJECT_DIR"
    exit 1
}

# Verifica se o container web está rodando
if ! docker compose "${COMPOSE_FILES[@]}" ps --status running web | grep -q web; then
    log "ERRO: container 'web' não está rodando. Abortando."
    exit 1
fi

# Executar extração de altas
log "Extraindo altas do dia..."
docker compose "${COMPOSE_FILES[@]}" exec -T web \
    uv run --no-sync python manage.py extract_discharges

log "=== Extração de altas finalizada ==="
```

**Permissão**: o arquivo deve ser executável. No deploy, o operador roda `chmod +x`.

### 6.2 `deploy/systemd/sirhosp-discharges.service`

Unit oneshot que chama o script acima.

```ini
[Unit]
Description=SIRHOSP — Extração diária de altas do sistema fonte
Documentation=https://github.com/carlosapgomes/sirhosp
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/sirhosp
ExecStart=/opt/sirhosp/deploy/discharges-scheduler.sh

# Timeout generoso: login + download PDF + parse (10 minutos)
TimeoutStartSec=600

# Logs vão para o journal (acessível via journalctl -u sirhosp-discharges)
StandardOutput=journal
StandardError=journal
SyslogIdentifier=sirhosp-discharges

# Segurança: impede execução simultânea
RemainAfterExit=no

[Install]
WantedBy=multi-user.target
```

### 6.3 `deploy/systemd/sirhosp-discharges.timer`

Timer que dispara 3x por dia.

```ini
[Unit]
Description=SIRHOSP — Timer de extração de altas (3x ao dia)
Documentation=https://github.com/carlosapgomes/sirhosp

[Timer]
# Dispara às: 11:00, 19:00, 23:55 (horário do servidor)
# 11:00 — primeiras altas do dia (geralmente após 9h-10h)
# 19:00 — cobre altas da tarde
# 23:55 — captura o restante antes da virada do dia
OnCalendar=*-*-* 11:00:00
OnCalendar=*-*-* 19:00:00
OnCalendar=*-*-* 23:55:00

# Aleatoriza até 2 minutos para evitar picos
RandomizedDelaySec=120

# Se o servidor estava desligado no horário, executa no boot
Persistent=true

# Não dispara de novo se o ciclo anterior ainda estiver rodando
RemainAfterElapse=no

[Install]
WantedBy=timers.target
```

### 6.4 `deploy/README.md` — adicionar seção de discharges

Localize a seção "4. Ativar agendamento automático do censo" e adicione uma
nova seção **após** ela (antes da seção "5. Worker de ingestão").

#### Texto a inserir

````text
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
````

#### Tabela de troubleshooting

Na seção "7. Troubleshooting" (`deploy/README.md`), adicionar uma nova linha à tabela:

Localize a tabela:

```markdown
| Problema            | Verificação                                                                   |
| ------------------- | ----------------------------------------------------------------------------- |
| Censo não extrai    | `journalctl -u sirhosp-census.service -n 30` — ver credenciais, conectividade |
| Worker não processa | `docker compose logs worker` — ver fila, conexão DB                           |
| Container não sobe  | `docker compose logs web` — ver `.env`, secrets, porta ocupada                |
```

Adicione a nova linha **antes** da linha `| Container não sobe`:

```markdown
| Altas não extrai    | `journalctl -u sirhosp-discharges.service -n 30` — ver credenciais, PDF       |
```

A tabela final deve ficar:

```markdown
| Problema            | Verificação                                                                   |
| ------------------- | ----------------------------------------------------------------------------- |
| Censo não extrai    | `journalctl -u sirhosp-census.service -n 30` — ver credenciais, conectividade |
| Altas não extrai    | `journalctl -u sirhosp-discharges.service -n 30` — ver credenciais, PDF       |
| Worker não processa | `docker compose logs worker` — ver fila, conexão DB                           |
| Container não sobe  | `docker compose logs web` — ver `.env`, secrets, porta ocupada                |
```

---

## 7. Sequência de execução

1. Criar `deploy/discharges-scheduler.sh` com o conteúdo acima
2. Tornar executável: `chmod +x deploy/discharges-scheduler.sh`
3. Criar `deploy/systemd/sirhosp-discharges.service`
4. Criar `deploy/systemd/sirhosp-discharges.timer`
5. Editar `deploy/README.md`:
   - Inserir seção "4b. Ativar agendamento automático de extração de altas"
   - Adicionar linha na tabela de troubleshooting
6. Rodar `./scripts/markdown-lint.sh deploy/README.md` para validar
7. Rodar quality gate (apenas lint, sem testes unitários novos neste slice)

---

## 8. Quality Gate (obrigatório)

```bash
# Lint dos arquivos de deploy (bash e markdown)
./scripts/test-in-container.sh lint

# Markdown lint específico para o README
./scripts/markdown-lint.sh deploy/README.md
```

**Nota**: Este slice não altera código Python, portanto `check` e `unit` não são
estritamente necessários. Mas é recomendado rodar `./scripts/test-in-container.sh check`
para garantir que nada quebrou.

---

## 9. Relatório obrigatório

Gerar `/tmp/sirhosp-slice-DIS-S2-report.md` com:

```markdown
# Slice DIS-S2 Report

## Status
[PASS / FAIL]

## Arquivos criados
- deploy/discharges-scheduler.sh
- deploy/systemd/sirhosp-discharges.service
- deploy/systemd/sirhosp-discharges.timer

## Arquivos modificados
- deploy/README.md (adicionada seção 4b + troubleshooting)

## Snippets before/after
### deploy/README.md — seção troubleshooting
**Before:** (tabela com 3 linhas)
**After:** (tabela com 4 linhas, incluindo "Altas não extrai")

### deploy/README.md — nova seção 4b
(conteúdo completo da seção inserida)

## Comandos executados
- chmod +x deploy/discharges-scheduler.sh: [OK]
- ./scripts/markdown-lint.sh deploy/README.md: [output]
- ./scripts/test-in-container.sh lint: [output]

## Riscos / Pendências
- As units systemd NÃO foram testadas em produção (sem acesso ao servidor).
  Validação real será feita pelo operador seguindo as instruções do README.
- O timer usa OnCalendar com 3 horários. Verificar se o fuso horário do
  servidor está correto (America/Sao_Paulo).

## Próximo passo sugerido
Validação fim-a-fim: executar `extract_discharges` contra o sistema fonte real
e verificar que o dashboard mostra altas > 0.
```

---

## 10. Anti-padrões PROIBIDOS

- ❌ Esquecer `set -euo pipefail` no script bash
- ❌ Hardcodar caminhos diferentes de `/opt/sirhosp` (padrão do projeto)
- ❌ Usar nomes de arquivo diferentes do padrão (`sirhosp-discharges.*`)
- ❌ Criar timer com `OnCalendar` errado (são 3 entradas: 11:00, 19:00, 23:55)
- ❌ Esquecer `Persistent=true` no timer
- ❌ Esquecer `RemainAfterExit=no` e `RemainAfterElapse=no`
- ❌ Não rodar `markdownlint` no `deploy/README.md`
- ❌ Modificar `census-scheduler.sh` ou units do censo
- ❌ Alterar `compose.yml` ou `compose.prod.yml`
