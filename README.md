# SIRHOSP

## SIRHOSP - Sistema Interno de Relatórios Hospitalares - Extração Inteligente de Dados Clínicos

Sistema interno para extração automatizada de dados clínicos do sistema fonte hospitalar, armazenamento em banco paralelo e geração de consultas rápidas, buscas textuais e resumos direcionados para gestão, qualidade, jurídico e diretoria.

## Status

Fase inicial de especificação e fundação arquitetural.

## Objetivo da fase 1

Entregar uma primeira versão utilizável que permita:

1. extrair dados do sistema fonte em janelas programadas
2. armazenar os dados em PostgreSQL
3. consultar rapidamente por paciente, período e internação
4. realizar busca livre por palavras-chave no texto clínico
5. gerar resumo de internação atualizado
6. oferecer login interno simples com perfis básicos

## Escopo prioritário da fase 1

- evolução médica
- prescrições
- pacientes internados atualmente
- resumo de internação
- busca textual livre
- dashboard operacional básico

## Decisões arquiteturais iniciais

- **Aplicação principal:** Django
- **Banco de dados:** PostgreSQL
- **Jobs agendados:** systemd timers ou cron
- **Coordenação de execução:** PostgreSQL com locks e tabelas de controle
- **Automação web:** Playwright + Python
- **Gerenciamento de ambiente e dependências Python:** uv
- **Frontend inicial:** Django Templates + HTMX + Bootstrap
- **Busca textual:** PostgreSQL Full Text Search
- **Integração LLM:** camada própria, desacoplada da captura

## Documentação inicial

- [Arquitetura inicial](docs/architecture.md)
- [ADRs](docs/adr/README.md)
- [ADR-0001](docs/adr/ADR-0001-monolito-django-postgresql-e-jobs-agendados.md)

## Princípios iniciais

- não usar dados reais no repositório
- manter credenciais fora do Git
- separar modo laboratório de automações do modo produção
- tratar o projeto como sistema interno institucional, mas sem supercomplexidade
  desnecessária
- privilegiar simplicidade operacional na fase 1
- padronizar setup e execução local com `uv`

## Quality Gate oficial (container)

O caminho oficial para validação do projeto é a suíte containerizada:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
# ou tudo de uma vez
./scripts/test-in-container.sh quality-gate
```

### Por que esse é o caminho oficial?

- O projeto usa PostgreSQL e o hostname `db` dentro da rede Compose.
- Fora de container, `POSTGRES_HOST=db` pode falhar com:
  `failed to resolve host 'db'`.
- O script oficial já faz `up -> wait -> run -> down`, evitando gestão manual do
  banco para cada execução.

### Execução host-only (diagnóstico)

`uv run pytest ...` pode ser usado para diagnóstico rápido local, mas não deve
ser tratado como gate oficial para aprovação de slice.

### Troubleshooting do quality gate containerizado

#### 1) Docker indisponível

Sintoma: erro `docker: command not found` ou daemon indisponível.

Ação:

```bash
docker --version
docker info
```

Inicie o Docker Desktop/daemon antes de rodar os gates.

#### 2) Porta PostgreSQL ocupada

O script usa `SIRHOSP_TEST_DB_PORT=55432` por padrão para evitar conflito com
stacks locais.

Se ainda houver conflito, execute com outra porta:

```bash
SIRHOSP_TEST_DB_PORT=55433 ./scripts/test-in-container.sh quality-gate
```

#### 3) Timeout de healthcheck do banco

Sintoma: `db did not become healthy` no `test-in-container.sh`.

Ações:

```bash
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml logs db
```

Reexecute após estabilização do Docker/IO do host.

#### 4) Cleanup de containers órfãos

Se houver resíduos de execução anterior:

```bash
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml down --remove-orphans
```

O script já executa teardown automático, mas este comando força limpeza manual.

## Execução containerizada

### Requisitos

- Docker 20.10+ ou Podman 4.0+
- `docker compose` ou `docker compose plugin`
- Variáveis de ambiente configuradas (ver [Configuração](#configuração))

### Configuração

```bash
# Criar arquivo .env com suas configurações
cp .env.example .env
# Editar .env com valores apropriados
```

**Precedência de variáveis de ambiente:**

O container usa a seguinte ordem de precedência (da mais alta para a mais baixa):

1. Variáveis definidas pelo Docker Compose (`environment:` no compose)
2. Variáveis exportadas pelo shell antes do container
3. Variáveis definidas em `/app/.env` (apenas para vars ausentes)

Isso permite que o Compose defina valores canônicos (ex: `DATABASE_URL`, `SECRET_KEY`) enquanto o `.env` local adiciona apenas o que faltar.

**Variáveis obrigatórias para produção:**

- `DJANGO_SECRET_KEY` - Chave secreta do Django (gerar com `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
- `DJANGO_ALLOWED_HOSTS` - Hosts permitidos (ex: `localhost,127.0.0.1,meu-servidor.local`)
- `POSTGRES_PASSWORD` - Senha do banco PostgreSQL
- `SOURCE_SYSTEM_URL` - URL do sistema legado (fonte para scraping)
- `SOURCE_SYSTEM_USERNAME` - Usuário do sistema legado
- `SOURCE_SYSTEM_PASSWORD` - Senha do sistema legado

**Conector legado integrado no próprio repositório:**

- O script de scraping MVP foi internalizado em
  `automation/source_system/medical_evolution/path2.py`.
- O worker usa esse script por padrão no comando `process_ingestion_runs`.
- Não é necessário clonar um repositório externo para executar o fluxo.

### Criar usuário admin

Após aplicar as migrações, crie um superusuário para acessar o Django Admin:

```bash
# Opção 1: modo interativo (recommended)
docker compose -f compose.yml -f compose.dev.yml exec web \
  uv run --no-sync python manage.py createsuperuser

# Opção 2: criar diretamente com senha definida
docker compose -f compose.yml -f compose.dev.yml exec web \
  uv run --no-sync python manage.py shell -c \
  "from django.contrib.auth import get_user_model; User = get_user_model(); \
  User.objects.create_superuser('admin', 'admin@local', 'SUA_SENHA')"
```

Após criado, acesse `http://localhost:8000/admin/`.

### Modo Desenvolvimento

```bash
# Construir imagens
docker compose -f compose.yml -f compose.dev.yml build web worker

# Subir stack (db + web + worker)
docker compose -f compose.yml -f compose.dev.yml up -d db web worker

# Aplicar migrações
docker compose -f compose.yml -f compose.dev.yml exec -T web uv run --no-sync python manage.py migrate

# Verificar health
curl http://localhost:8000/health/

# Ver logs
docker compose -f compose.yml -f compose.dev.yml logs -f web

# Encerrar
docker compose -f compose.yml -f compose.dev.yml down -v
```

**Características do modo dev:**

- Bind mount do código (`.:/app`) para hot-reload
- Django runserver com DEBUG=1
- Volumes para persistência de dados

### Modo Produção

```bash
# Construir imagens (target prod)
docker compose -f compose.yml -f compose.prod.yml build web worker

# Subir stack (db + web + worker)
docker compose -f compose.yml -f compose.prod.yml up -d db web worker

# Aplicar migrações
docker compose -f compose.yml -f compose.prod.yml exec -T web uv run --no-sync python manage.py migrate

# Verificar health
curl http://localhost:8000/health/

# Ver logs (Gunicorn)
docker compose -f compose.yml -f compose.prod.yml logs -f web

# Encerrar
docker compose -f compose.yml -f compose.prod.yml down -v
```

**Características do modo prod:**

- Imagem imutável com código baked-in
- Gunicorn com 2 workers
- `UV_NO_CACHE=1` para evitar escrita em runtime
- Health checks robustos

### Smoke Test

Valida ambos os modos (dev e prod) de forma automatizada:

```bash
./scripts/container-smoke.sh
```

O script executa:

1. Build das imagens
2. Startup da stack
3. Migrações
4. Health check
5. Verificação de Gunicorn em prod
6. Shutdown limpo

### Notas sobre rootless (Docker/Podman)

O projeto é compatível com execução rootless:

- Usuário não-root (UID 10001) dentro dos containers
- Diretórios de cache configurados para gravação pelo usuário do container
- `GUNICORN_WORKER_TMP_DIR=/tmp/gunicorn` evita erros de permissão no socket

Se encontrar erros `Permission denied` em ambiente rootless:

1. Verifique que o usuário do container tem permissão nos volumes
2. O volume `sirhosp_db_data` é gerenciado pelo Docker e deve funcionar
3. Logs detalhados: `docker compose logs web --tail=200`
