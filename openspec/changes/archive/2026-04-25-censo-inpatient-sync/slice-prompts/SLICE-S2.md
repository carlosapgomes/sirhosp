# SLICE-S2: Script de extração do censo integrado

> **Handoff para executor com ZERO contexto adicional.**
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares. Extrai dados clínicos do sistema fonte hospitalar via web scraping (Playwright), persiste em PostgreSQL paralelo, oferece portal Django.

**Stack**: Python 3.12, Django 5.x, PostgreSQL, `uv`, Playwright (Chromium), pytest, Bootstrap+HTMX.

**Regras**: sem Celery/Redis na fase 1, sem dados reais no código, TDD obrigatório.

**Execução de scripts de scraping**: via `subprocess.run()` disparado por management commands Django. Padrão estabelecido pelo `PlaywrightEvolutionExtractor` em `apps/ingestion/extractors/playwright_extractor.py`.

---

## 2. Estado atual do projeto (após Slice S1)

```text
sirhosp/
├── config/settings.py          ← INSTALLED_APPS inclui "apps.census"
├── apps/
│   └── census/                 ← criado no S1: models.py, admin.py, apps.py
│       └── models.py           ← CensusSnapshot, BedStatus
├── automation/
│   └── source_system/
│       ├── medical_evolution/
│       │   ├── source_system.py    ← helpers compartilhados: login, fechar_dialogos_iniciais, aguardar_pagina_estavel
│       │   └── path2.py
│       ├── patient_demographics/
│       └── current_inpatients/
│           └── README.md           ← "Conector planejado para sincronização..."
```text

O módulo `automation/source_system/medical_evolution/source_system.py` exporta:

```python
DEFAULT_TIMEOUT_MS = 180000       # timeout padrão Playwright
def aguardar_pagina_estavel(page: Page) -> None: ...
def fechar_dialogos_iniciais(page: Page) -> None: ...
```text

---

## 3. Objetivo do Slice

Copiar e adaptar o MVP `busca_todos_pacientes_slim.py` do projeto `pontelo/` para dentro do SIRHOSP como:

```text
automation/source_system/current_inpatients/extract_census.py
```text

O script mantém a mesma lógica de scraping (login → abrir Censo → listar setores → iterar setores → extrair pacientes com paginação → salvar CSV+JSON), mas adaptado para usar os helpers compartilhados do projeto.

---

## 4. Arquivo de referência (LEIA ANTES)

O arquivo fonte está em:

```text
/home/carlos/projects/pontelo/busca_todos_pacientes_slim.py
```text

Leia-o integralmente. Você vai COPIAR o conteúdo e fazer as adaptações abaixo.

**Resumo da estrutura do arquivo original**:

- `CENSO_FRAME_NAME = "i_frame_censo_diário_dos_pacientes"`
- `DOWNLOADS_DIR = Path("downloads")`
- `DEBUG_DIR = Path("debug")`
- `required_env(name)` — valida variáveis de ambiente
- `parse_args()` — CLI com `--headless`, `--max-setores`, `--pause-ms`, `--table-timeout-ms`, `--search-retries`
- `wait_visible(locator, timeout)` — helper interno
- `safe_click(locator, label, timeout)` — helper interno
- `get_censo_frame(page, timeout_ms)` — aguarda iframe do censo
- `wait_ajax_idle(frame, page, timeout_ms)` — aguarda fila AJAX esvaziar
- `click_censo_icon(page)` — clica no ícone do Censo
- `extract_setores(frame, page)` — extrai lista de setores do dropdown
- `clear_setor(frame, page)` — limpa setor selecionado
- `select_setor(frame, page, setor)` — seleciona um setor
- `click_pesquisar(frame)` — clica botão Pesquisar
- `table_state(frame)`, `wait_table_change(...)`, `wait_table_ready(...)` — polling da tabela
- `extract_current_page(frame)` — extrai pacientes da página atual
- `paginator_state(frame)`, `click_next_page(frame, page)` — paginação
- `extract_all_pages(frame, page)` — itera páginas
- `save_results(results)` — salva CSV+JSON
- `save_debug(page)` — screenshot + HTML
- `run(...)` — fluxo principal
- `main()` — entry point

---

## 5. Adaptações EXATAS a fazer

### 5.1 Imports

**Remover**:

```python
from dotenv import load_dotenv
from source_system import DEFAULT_TIMEOUT_MS, aguardar_pagina_estavel, fechar_dialogos_iniciais
```text

**Adicionar** (caminho relativo a partir de `automation/source_system/current_inpatients/`):

```python
import sys
from pathlib import Path

# Add parent automation/source_system so we can import shared helpers
_CURRENT_DIR = Path(__file__).resolve().parent
_SOURCE_SYSTEM_DIR = _CURRENT_DIR.parent
sys.path.insert(0, str(_SOURCE_SYSTEM_DIR))

# Shared helpers from medical_evolution connector
from source_system import aguardar_pagina_estavel, fechar_dialogos_iniciais

# Configurar timeout — mesmo valor do original
DEFAULT_TIMEOUT_MS = 180000
```text

E remover as funções `load_dotenv` e `required_env`. Em vez de `required_env`, usar `os.getenv` direto com fallback. Não usar `python-dotenv` — o SIRHOSP carrega variáveis via Django settings ou arquivo `.env` no diretório raiz.

### 5.2 Manter TODOS os helpers internos

As funções `wait_visible`, `safe_click`, `get_censo_frame`, `wait_ajax_idle`, `click_censo_icon`, `extract_setores`, `clear_setor`, `select_setor`, `click_pesquisar`, `table_state`, `wait_table_change`, `wait_table_ready`, `extract_current_page`, `paginator_state`, `click_next_page`, `extract_all_pages`, `save_results`, `save_debug` — **manter idênticas**. Elas são específicas do censo e não existem no `source_system.py` compartilhado.

### 5.3 Ajustar `DOWNLOADS_DIR` e `DEBUG_DIR`

```python
# Diretórios relativos à raiz do projeto sirhosp
# extract_census.py está em automation/source_system/current_inpatients/
# raiz do projeto = 4 níveis acima
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DOWNLOADS_DIR = _PROJECT_ROOT / "downloads"
DEBUG_DIR = _PROJECT_ROOT / "debug"
```text

### 5.4 CLI: adicionar `--output-dir`

Manter todos os argumentos originais. Adicionar:

```python
parser.add_argument(
    "--output-dir",
    type=str,
    default=None,
    help="Diretório de saída para CSV/JSON (default: <project_root>/downloads)",
)
```text

Se `--output-dir` for informado, sobrescrever `DOWNLOADS_DIR`.

### 5.5 CLI: adicionar `--csv-output`

```python
parser.add_argument(
    "--csv-only",
    action="store_true",
    help="Gerar apenas CSV (não gerar JSON)",
)
```text

### 5.6 Função `run()` — login

A função `run()` atual faz login via Playwright. **Manter a lógica idêntica**. O login usa:

```python
page.get_by_role("textbox", name="Nome de usuário").fill(username)
page.get_by_role("textbox", name="Senha").fill(password)
page.get_by_role("button", name="Entrar").click()
aguardar_pagina_estavel(page)
fechar_dialogos_iniciais(page)
```text

Isso já é compatível com os helpers do `source_system.py`.

### 5.7 Função `main()` — remover load_dotenv

```python
def main() -> None:
    args = parse_args()
    run(
        source_system_url=os.getenv("SOURCE_SYSTEM_URL", ""),
        username=os.getenv("SOURCE_SYSTEM_USERNAME", ""),
        password=os.getenv("SOURCE_SYSTEM_PASSWORD", ""),
        headless=args.headless,
        max_setores=args.max_setores,
        pause_ms=args.pause_ms,
        table_timeout_ms=args.table_timeout_ms,
        search_retries=args.search_retries,
    )
```text

### 5.8 Atualizar `README.md`

Substituir o conteúdo de `automation/source_system/current_inpatients/README.md` por:

```markdown
# Current Inpatients Connector

Extrai pacientes internados atualmente de todos os setores do Censo
Diário do sistema fonte.

## Uso

```bash
uv run python automation/source_system/current_inpatients/extract_census.py \
    --headless \
    --output-dir downloads/
```text

## Output

- CSV: `downloads/censo-todos-pacientes-slim-<timestamp>.csv`
- JSON: `downloads/censo-todos-pacientes-slim-<timestamp>.json`

CSV columns: `setor`, `qrt_leito`, `prontuario`, `nome`, `esp`

## Variáveis de ambiente

- `SOURCE_SYSTEM_URL` — URL do sistema fonte
- `SOURCE_SYSTEM_USERNAME` — Usuário de acesso
- `SOURCE_SYSTEM_PASSWORD` — Senha de acesso

```text

---

## 6. Sequência de execução

1. Ler `/home/carlos/projects/pontelo/busca_todos_pacientes_slim.py`
2. Copiar conteúdo para `automation/source_system/current_inpatients/extract_census.py`
3. Aplicar as 8 adaptações da seção 5
4. Atualizar `automation/source_system/current_inpatients/README.md`
5. Verificar que o script é executável e `--help` funciona

---

## 7. Quality Gate

```bash
# Verificar que o script carrega sem erro de sintaxe/import
uv run python -c "import ast; ast.parse(open('automation/source_system/current_inpatients/extract_census.py').read()); print('Syntax OK')"

# Verificar que --help funciona
uv run python automation/source_system/current_inpatients/extract_census.py --help

# Lint do script
uv run ruff check automation/source_system/current_inpatients/

# Django check (garante que nada quebrou)
./scripts/test-in-container.sh check

# Lint do projeto
./scripts/test-in-container.sh lint
```text

**Nota**: NÃO é possível rodar o script de scraping nos testes (precisa de credenciais reais + sistema fonte). O gate verifica sintaxe, lint e integridade do projeto.

---

## 8. Relatório

Gerar `/tmp/sirhosp-slice-CIS-S2-report.md` com:

```markdown
# Slice CIS-S2 Report

## Status
[PASS / FAIL]

## Arquivos criados
- automation/source_system/current_inpatients/extract_census.py

## Arquivos modificados
- automation/source_system/current_inpatients/README.md

## Adaptações realizadas
(lista das 8 adaptações, com antes/depois resumido)

## Comandos executados
(comando + output resumido)

## Riscos / Pendências
- Script não testado com sistema fonte real (precisa de credenciais)

## Próximo slice
S3 — Management command extract_census + parser CSV + classificador
```text

---

## 9. Anti-padrões PROIBIDOS

- ❌ Reescrever o script do zero (deve ser cópia + adaptações mínimas)
- ❌ Remover helpers internos do censo (wait_ajax_idle, get_censo_frame, etc.)
- ❌ Importar `dotenv` ou adicionar dependências novas
- ❌ Alterar a lógica de scraping (seletores, fluxo de setores, paginação)
- ❌ Usar caminho hardcoded para diretórios (usar `__file__` relativo)
- ❌ Rodar o script contra o sistema fonte real durante implementação
