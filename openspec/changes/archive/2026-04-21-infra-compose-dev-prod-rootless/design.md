<!-- markdownlint-disable MD013 -->

# Design: infra-compose-dev-prod-rootless

## Context

A Fase A de ingestão sob demanda está concluída e arquivada. O próximo passo funcional será a Fase B, porém há um gap operacional: falta um ambiente containerizado padrão para validar manualmente o fluxo web + worker com PostgreSQL.

A base atual já possui:

- Django 5 + `uv`;
- seleção automática de banco PostgreSQL por variáveis `POSTGRES_*`;
- worker `process_ingestion_runs`;
- telas HTML para criação/status de ingestão.

## Goals

- Subir stack completa com um comando Compose.
- Permitir teste manual via browser do host (`http://localhost:<porta>`).
- Ter modo dev e modo prod claramente separados.
- Manter compatibilidade com execução rootless.

## Non-Goals

- Não alterar domínio clínico/modelos/migrações.
- Não criar pipeline CI/CD completo nesta change.
- Não resolver observabilidade avançada (fica para outra change).

## Decisions

### 1) Dockerfile multi-stage com alvos `dev` e `prod`

**Decisão:** usar um único Dockerfile com estágios nomeados para evitar duplicação.

- `dev`: foco em produtividade local, comando de desenvolvimento.
- `prod`: imagem final enxuta para execução com Gunicorn.

### 2) Compose em camadas: base + override dev + override prod

**Decisão:** adotar três arquivos:

- `compose.yml` (serviços comuns e infraestrutura base);
- `compose.dev.yml` (override de desenvolvimento);
- `compose.prod.yml` (override de deploy/local-prod).

Isso evita arquivos gigantes e reduz drift entre modos.

### 3) Serviços mínimos da stack

**Decisão:** padronizar os serviços:

- `db` (PostgreSQL com volume persistente);
- `web` (Django);
- `worker` (processa `IngestionRun` em loop simples/polling leve).

### 4) Compatibilidade rootless por padrão

**Decisão:** não usar `privileged`, `host network`, nem bindings especiais.

- portas explícitas para acesso host;
- volumes nomeados para dados;
- UID/GID padrão sem permissões elevadas.

### 5) Estratégia de validação (anti-drift)

**Decisão:** para change de infraestrutura, usar **TDD operacional (red/green por smoke checks)** em vez de suíte unitária nova.

Exemplos de RED/GREEN:

- RED: `compose up` falha por comando/imagem inexistente.
- GREEN: stack sobe, `manage.py check` passa, `/health/` responde.

## Execution flow (dev)

1. `compose` sobe `db`, `web`, `worker`.
2. `web` aplica migrações no startup (ou comando explícito documentado).
3. usuário acessa `http://localhost:8000` no host.
4. usuário testa login + `/ingestao/criar/`.
5. worker processa runs enfileirados.

## Execution flow (prod local)

1. build target `prod`.
2. `web` inicia com Gunicorn.
3. staticfiles coletados no build/startup conforme decisão do slice.
4. `worker` executa comando de processamento contínuo configurado.

## Risks / Trade-offs

- `uv.lock` pode mudar ao adicionar dependências de runtime (ex.: gunicorn).
- startup automático com migração pode mascarar falhas operacionais; precisa ficar documentado.
- rootless em ambientes diferentes (Docker vs Podman) pode exigir pequenas diferenças de comando.

## Anti-drift guardrails

- Um slice por vez, sem antecipar próximos.
- Limite explícito de arquivos por slice.
- Se precisar exceder limite: parar e reportar bloqueio.
- Executar gates mínimos por slice (comandos definidos nos prompts).
- Relatório obrigatório em `/tmp/sirhosp-slice-<ID>-report.md`.

## Open questions

- `worker` deve rodar loop contínuo interno ou agendamento externo (cron/systemd) no host?
- staticfiles será coletado no build ou no startup do container `web` em prod?
