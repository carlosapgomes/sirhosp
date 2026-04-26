# SLICE-PF-3: Hardening final e fechamento do change

> **Handoff para executor com ZERO contexto adicional.**
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares.

**Stack**: Python 3.12, Django 5.x, PostgreSQL, `uv`, pytest, Bootstrap 5,
HTMX.

---

## 2. Estado atual do projeto (o que já foi entregue)

### Slice PF-1 (backend)

- Template parcial `_run_progress.html` renderiza estágios com badges
- View `run_status_fragment` retorna HTML parcial
- URL `run_status_fragment` para polling
- View `run_status` inclui `stage_metrics` no contexto

### Slice PF-2 (frontend)

- HTMX carregado em `base.html`
- `run_status.html` usa HTMX polling em vez de meta-refresh
- Progress partial incluído na página principal
- Testes de integração atualizados

---

## 3. Objetivo do Slice

Consolidar o change: atualizar specs, rodar quality gate completo, validar
markdown, gerar relatório final.

---

## 4. O que EXATAMENTE fazer

### 4.1 Atualizar spec `ingestion-run-observability`

**Arquivo**: `openspec/specs/ingestion-run-observability/spec.md`

Adicionar ao final do arquivo (antes de qualquer linha de fechamento):

```markdown
## ADDED Requirements (run-status-progress-feedback)

### Requirement: Run status page exposes stage-level progress to users

Ingestion run tracking SHALL expose per-stage execution progress on the run
status page.

#### Scenario: Stage metrics displayed on run status

- **WHEN** an authenticated user opens the run status page
- **THEN** the page displays a progress section with per-stage execution status
- **AND** each stage shows its name, completion status, and duration
- **AND** the progress section updates automatically while the run is active

#### Scenario: Fragment endpoint returns stage progress HTML

- **WHEN** an authenticated client polls the progress fragment endpoint
- **THEN** the response contains an HTML fragment with stage names and statuses
- **AND** the fragment is suitable for HTMX partial swap
```

### 4.2 Validar spec `run-status-progress`

**Arquivo**: `openspec/changes/2026-04-26-run-status-progress-feedback/specs/run-status-progress/spec.md`

Revisar se todos os cenários estão implementados e marcar como verificados.
Adicionar nota no topo:

```markdown
> **Status**: Implemented ✅ (PF-1, PF-2)
```

### 4.3 Rodar quality gate completo

```bash
./scripts/test-in-container.sh quality-gate
```

Se houver falhas, corrigir e repetir até passar.

### 4.4 Validar markdown

```bash
./scripts/markdown-lint.sh
```

Corrigir erros de lint em TODOS os arquivos `.md` alterados/criados neste
change. **Não usar `<!-- markdownlint-disable -->`** — corrigir a causa raiz.

### 4.5 Atualizar tasks.md

Marcar todos os checkboxes dos slices PF-1, PF-2 e PF-3 como `[x]`.

### 4.6 Gerar relatório final do slice

**Arquivo**: `/tmp/sirhosp-slice-PF-3-report.md`

Incluir:

- Resumo do slice (1 parágrafo)
- Checklist de aceite (todos os checkboxes do tasks.md para PF-3)
- Lista de arquivos alterados (com paths absolutos)
- Fragmentos de código ANTES/DEPOIS por arquivo alterado
- Resultado do quality-gate (comando + exit code + resumo)
- Resultado do markdown-lint
- Riscos, pendências e próximo passo sugerido

---

## 5. Quality Gate

```bash
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
```

---

## 6. Relatório

Gerar `/tmp/sirhosp-slice-PF-3-report.md` com:

- Resumo do slice
- Checklist de aceite (todos os checkboxes do tasks.md para PF-3)
- Lista de arquivos alterados
- Fragmentos ANTES/DEPOIS
- Comandos executados e resultados
- Riscos, pendências e próximo passo

---

## 7. Anti-padrões PROIBIDOS

- ❌ Não usar `<!-- markdownlint-disable -->` em nenhum arquivo `.md`
- ❌ Não modificar código Python/HTML neste slice (apenas specs e docs)
- ❌ Não pular o quality-gate
- ❌ Não fechar o change sem todos os gates passando
