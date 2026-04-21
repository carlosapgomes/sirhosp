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
- tratar o projeto como sistema interno institucional, mas sem supercomplexidade desnecessária
- privilegiar simplicidade operacional na fase 1
- padronizar setup e execução local com `uv`

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
