# AGENTS.md

## 1. Stack e versões
- Python: 3.12
- Gerenciamento Python: `uv`
- Backend: Django 5.x
- Banco principal: PostgreSQL
- Frontend inicial: Django Templates + HTMX + Bootstrap
- Automação: Playwright + Python
- Extração de PDF: PyMuPDF
- Workflow: DevLoop + OpenSpec
- Execução programada: `systemd timers` ou `cron`
- Processamento assíncrono fase 1: **sem Celery/Redis**; coordenação via PostgreSQL

## 2. Comandos de validação (Quality Gate)
- Instalar dependências: `uv sync`
- Django check: `uv run python manage.py check`
- Testes: `uv run pytest -q`
- Lint: `uv run ruff check config apps tests manage.py`
- Type check: `uv run mypy config apps tests manage.py`
- Markdown autofix: `./scripts/markdown-format.sh`
- Markdown lint: `./scripts/markdown-lint.sh`

## 3. Comandos essenciais (operação local)
### Setup
```bash
uv sync
uv run playwright install chromium
cp .env.example .env
```

### Rodar local
```bash
uv run python manage.py migrate
uv run python manage.py runserver
```

### Testes rápidos
```bash
uv run pytest -q tests/unit
```

### Jobs e automações
```bash
uv run python manage.py run_due_jobs
uv run python manage.py sync_current_inpatients
uv run python manage.py extract_medical_evolutions
uv run python manage.py extract_prescriptions
uv run python manage.py refresh_admission_summaries
```

### Hooks
```bash
git config core.hooksPath .githooks
```

## 4. Arquitetura e constraints
- Manter o projeto como **monólito modular Django** na fase 1.
- Não introduzir Celery, Redis ou microserviços sem decisão explícita em ADR/OpenSpec.
- Usar PostgreSQL tanto para persistência clínica quanto para coordenação operacional básica de jobs.
- Separar claramente código de **modo laboratório** e **modo produção** das automações Playwright.
- Não versionar dados reais de pacientes, PDFs reais, dumps reais ou credenciais.
- Tratar o MVP `resumo-evolucoes-clinicas` como fonte de reaproveitamento técnico, não como arquitetura final.
- Preservar separação entre portal web, domínio clínico e conectores de ingestão.

## 5. Política de testes
- TDD para novas funcionalidades relevantes, especialmente domínio, ingestão e parsing.
- Priorizar testes unitários para regras de negócio e parsers.
- Usar testes de integração para management commands, queries e persistência.
- Usar fixtures **sintéticas/anônimas** para scraping, parsing e geração de resumo.
- Ao corrigir bug, adicionar ao menos um teste de caracterização ou regressão.

## 6. Stop Rule (CRUCIAL)
- Implementar **um slice por vez**.
- Rodar os comandos de validação da seção 2 para o escopo alterado.
- Atualizar OpenSpec, ADRs, tasks e docs quando necessário.
- Parar ao fim do slice e decidir conscientemente o próximo passo.

## 7. Definition of Done (DoD)
- [ ] `uv run python manage.py check` sem erro
- [ ] testes relevantes passando
- [ ] `uv run ruff check config apps tests manage.py` sem erro
- [ ] `uv run mypy config apps tests manage.py` sem erro relevante ou com exceções justificadas
- [ ] markdown lint sem erro quando houver mudança em `.md`
- [ ] artefatos OpenSpec atualizados quando aplicável
- [ ] sem credenciais nem dados reais no diff
- [ ] commit claro e rastreável

## 8. Anti-patterns proibidos
- Não colocar lógica de negócio complexa em views, templates ou management commands.
- Não misturar código exploratório de scraping com código operacional de produção.
- Não acoplar seletores de Playwright diretamente ao portal web.
- Não introduzir dependências pesadas sem justificativa arquitetural.
- Não persistir textos clínicos brutos fora do modelo/versionamento definido.
- Não subir arquivos de debug reais contendo dados sensíveis.

## 9. Prompt de reentrada
```text
Read AGENTS.md and PROJECT_CONTEXT.md first.
Review active OpenSpec changes before coding.
Implement ONLY the next incomplete slice.
Use uv for Python commands.
Run relevant validation commands, update artifacts, then STOP.
```
