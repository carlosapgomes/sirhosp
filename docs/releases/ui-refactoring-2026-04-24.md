<!-- markdownlint-disable MD013 MD040 -->
# Release Evidence Pack — UI Refactoring (2026-04-24)

## 1. Identificação

| Campo      | Valor                                                                 |
| ---------- | --------------------------------------------------------------------- |
| **Data**   | 2026-04-24                                                            |
| **Branch** | `ui-refactoring` (a partir de `master`, commit `d549460` → `50c27a1`) |
| **Tipo**   | Refatoração de frontend (UI/UX)                                       |
| **Escopo** | 6 slices, 32 arquivos                                                 |
| **Status** | ✅ Concluído — todos os gates aprovados                               |

---

## 2. Objetivo

Migrar o portal SIRHOSP de páginas isoladas com navbar Bootstrap básica para uma
arquitetura de templates moderna com:

- Sidebar fixa com 4 itens de menu navegáveis
- Topbar com título de página + badge de status de sincronização
- 5 páginas novas conforme wireframes desenhados pela gestão
- Design homogêneo, coerente e compatível com ambiente hospitalar
- Dados demo/stub onde o backend ainda não está implementado
- Total responsividade mobile (offcanvas, cards, touch targets)

---

## 3. Identidade Visual

### Paleta de cores

| Token                   | Valor                 | Uso                                  |
| ----------------------- | --------------------- | ------------------------------------ |
| `--bs-primary`          | `#0D9488` (Teal 600)  | Botões, links, badges, ícones ativos |
| `--bs-primary-dark`     | `#0F766E` (Teal 700)  | Hover de botões                      |
| `--bs-primary-darker`   | `#115E59` (Teal 800)  | Texto de destaque                    |
| `--bs-primary-lightest` | `#CCFBF1` (Teal 100)  | Fundo de badges, alerts de sucesso   |
| `--sirhosp-sidebar-bg`  | `#0F172A` (Slate 900) | Fundo da sidebar                     |
| `--sirhosp-bg`          | `#F8FAFC` (Slate 50)  | Fundo do conteúdo                    |
| Sync status             | `#0D9488` (Teal)      | Badge "Sincronizado"                 |

**Justificativa:** O teal é amplamente utilizado em interfaces healthcare por
transmitir calma, profissionalismo e confiança. O contraste com o slate escuro
da sidebar cria hierarquia visual clara sem cansar os olhos em uso prolongado.

### Tipografia

- **Font family:** system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue"
  (stack nativa do Bootstrap 5.3.3)
- **Escala:** Bootstrap padrão (16px base)
- Mobile: inputs com `font-size: 16px` para evitar zoom automático no iOS

### Ícones

- **Bootstrap Icons 1.11.3** via CDN
- Mapeamento menu: `bi-grid-1x2-fill` (Dashboard), `bi-hospital` (Censo),
  `bi-people` (Pacientes), `bi-exclamation-triangle` (Monitor)

---

## 4. Arquitetura de Templates

```
templates/
├── base.html                  ← Público: landing, login (sem sidebar)
├── base_sidebar.html          ← Autenticado: sidebar + topbar + conteúdo
├── includes/
│   ├── sidebar.html           ← 4 itens + footer (user/logout)
│   └── topbar.html            ← Título da página + badge sync
├── registration/
│   └── login.html             ← extends base.html
│
apps/
├── core/templates/core/
│   └── home.html              ← Landing page (extends base.html)
├── patients/templates/patients/
│   ├── patient_list.html      ← Busca de pacientes (extends base_sidebar.html)
│   ├── admission_list.html    ← Detalhes unificados (extends base_sidebar.html)
│   ├── timeline.html          ← Timeline standalone (extends base_sidebar.html)
│   └── 404.html               ← Página 404 (extends base_sidebar.html)
├── ingestion/templates/ingestion/
│   ├── create_run.html        ← Extração por período (extends base_sidebar.html)
│   ├── create_admissions_only.html ← Sync internações (extends base_sidebar.html)
│   └── run_status.html        ← Status do run (extends base_sidebar.html)
└── services_portal/templates/services_portal/
    ├── dashboard.html          ← Dashboard (extends base_sidebar.html)
    ├── censo.html              ← Censo hospitalar (extends base_sidebar.html)
    └── monitor_risco.html      ← Monitor de risco (extends base_sidebar.html)
```

### Diagrama de herança

```
base.html (Bootstrap CSS + Icons + JS)
  ├── base_sidebar.html (+ sidebar + topbar + offcanvas JS)
  │     ├── dashboard.html
  │     ├── censo.html
  │     ├── monitor_risco.html
  │     ├── patient_list.html
  │     ├── admission_list.html  ← unificado com timeline
  │     ├── timeline.html
  │     ├── 404.html
  │     ├── create_run.html
  │     ├── create_admissions_only.html
  │     └── run_status.html
  ├── home.html              ← landing pública
  └── login.html             ← login pública
```

### Layout autenticado

```
┌─────────────────────────────────────────────────────────┐
│ TOPBAR: [☰] Dashboard                      [🟢 Sync 12:45] │
├──────────────┬──────────────────────────────────────────┤
│ SIDEBAR      │                                          │
│ (260px fixa) │  CONTEÚDO                                │
│              │  (scrollável, max-width 1400px)          │
│ 🏠 Dashboard │                                          │
│ 🏥 Censo     │  ┌─────────────────────────────────┐     │
│ 👥 Pacientes │  │ Cards / Tabelas / Formulários    │     │
│ ⚠️ Monitor   │  └─────────────────────────────────┘     │
│              │                                          │
│ 👤 user      │                                          │
│ [🚪 Sair]    │                                          │
└──────────────┴──────────────────────────────────────────┘
```

### Layout mobile (≤991px)

```
┌─────────────────────────┐
│ [☰] Dashboard    [🟢]  │ ← topbar com hamburger
├─────────────────────────┤
│                         │
│  CONTEÚDO               │
│  (sidebar fechada)       │
│                         │
└─────────────────────────┘

        ↓ clique no ☰

┌────────────────────┬────┐
│ ╔══════════════╗   │    │ ← overlay semi-transparente
│ ║ EHR Mirror   ║   │    │
│ ║ 🏠 Dashboard ║   │    │
│ ║ 🏥 Censo     ║   │    │
│ ║ 👥 Pacientes ║   │    │
│ ║ ⚠️ Monitor   ║   │    │
│ ║ 👤 user      ║   │    │
│ ║ [🚪 Sair]    ║   │    │
│ ╚══════════════╝   │    │
└────────────────────┴────┘
```

---

## 5. Páginas Implementadas

### 5.1 Landing Page (`/`)

**Template:** `apps/core/templates/core/home.html`  
**View:** `apps/core/views.py:home()`  
**Autenticação:** Pública

```
┌──────────────────────────────────────┐
│         Fundo gradiente teal          │
│  ┌────────────────────────────────┐   │
│  │     ♥ EHR Mirror               │   │
│  │  Sistema de Relatórios          │   │
│  │  Hospitalares                   │   │
│  │                                 │   │
│  │  Extração inteligente de dados  │   │
│  │  clínicos...                    │   │
│  │                                 │   │
│  │  [Entrar no portal]             │   │
│  │                                 │   │
│  │  🔍 Busca   │ 📊 Dashboard     │   │
│  │  🕐 Timeline │ 🛡️ Monitor      │   │
│  └────────────────────────────────┘   │
│     🔒 Acesso restrito a profissionais │
└──────────────────────────────────────┘
```

### 5.2 Login (`/login/`)

**Template:** `templates/registration/login.html`  
**View:** Django `auth_views.LoginView`  
**Autenticação:** Pública → redireciona para `/painel/`

Features:

- Input groups com ícones (👤 usuário, 🔒 senha)
- Validação visual com alerta de erro
- Botões: Entrar + Voltar ao início
- Gradiente teal de fundo

### 5.3 Dashboard (`/painel/`)

**Template:** `apps/services_portal/templates/services_portal/dashboard.html`  
**View:** `apps/services_portal/views.py:dashboard()`  
**Dados:** Demo/stub

| Card        | Valor | Ícone                | Cor   |
| ----------- | ----- | -------------------- | ----- |
| Internados  | 142   | `bi-hospital`        | Teal  |
| Cadastrados | 5.230 | `bi-people`          | Sky   |
| Altas (24h) | 12    | `bi-box-arrow-right` | Amber |

**Status da Coleta:**

- 18 setores monitorados em tempo real
- Última varredura completa: há 4 minutos

**Quick actions:** Cards clicáveis para Censo, Pacientes e Monitor de Risco.

### 5.4 Censo Hospitalar (`/censo/`)

**Template:** `apps/services_portal/templates/services_portal/censo.html`  
**View:** `apps/services_portal/views.py:censo()`  
**Dados:** Demo/stub (8 pacientes em 12 setores)

**Filtros:**

- Campo de texto: Nome ou Registro
- Dropdown: 12 setores (UTI Adulto, UTI Neonatal, Clínica Médica, etc.)
- Botão: Filtrar

**Desktop:** Tabela com colunas Leito | Paciente | Registro | Admissão | Setor  
**Mobile:** Cards empilháveis com nome + badges (leito, registro, admissão, setor)

Linhas/Cards são clicáveis → redirecionam para busca do paciente.

### 5.5 Detalhes do Paciente (`/pacientes/<id>/admissions/`)

**Template:** `apps/patients/templates/patients/admission_list.html`  
**View:** `apps/patients/views.py:admission_list_view()`  
**Dados:** Reais (Patient, Admission, ClinicalEvent models)

**Banner de identidade:** Nome, registro, data de nascimento, idade calculada, setor, leito.

**Dropdown de internação:** Lista todas as internações com datas, setor, contagem de eventos.

**Timeline inline:** Cards de eventos clínicos com:

- Badge de profissão (Médico, Enfermagem, Fisioterapia, etc.)
- Data/hora
- Autor
- Texto com expand/colapsar (>260 caracteres)
- Linha de assinatura
- Filtros por profissão (botões toggle)

### 5.6 Monitor de Risco (`/monitor/`)

**Template:** `apps/services_portal/templates/services_portal/monitor_risco.html`  
**View:** `apps/services_portal/views.py:monitor_risco()`  
**Dados:** Híbrido (tenta `search_clinical_events` real, fallback demo)

**Busca:**

- Campo de termos (múltiplos separados por vírgula)
- Dropdown de período: 24h, 48h, 7 dias
- Exemplos clicáveis no estado vazio: queda, sepse, lesão, reintubação

**Resultados:** Accordion Bootstrap agrupado por paciente:

- Header: nome do paciente + badge de N ocorrências
- Body: snippets com data, autor e texto do evento
- Link "Ver prontuário completo" → busca do paciente

**Resumo:** Badges com total de pacientes e total de ocorrências.

---

## 6. Páginas Preservadas (Restilizadas)

Todas as páginas existentes foram migradas para a nova base de templates:

| URL                                  | Template                      | Status                             |
| ------------------------------------ | ----------------------------- | ---------------------------------- |
| `/pacientes/`                        | `patient_list.html`           | Novo visual (sidebar + breadcrumb) |
| `/admissions/<id>/timeline/`         | `timeline.html`               | Novo visual (sidebar + breadcrumb) |
| `/ingestao/criar/`                   | `create_run.html`             | Novo visual (sidebar + breadcrumb) |
| `/ingestao/sincronizar-internacoes/` | `create_admissions_only.html` | Novo visual                        |
| `/ingestao/status/<id>/`             | `run_status.html`             | Novo visual + spinner              |
| `/patients/404`                      | `404.html`                    | Novo visual                        |

---

## 7. Melhorias Mobile

### Breakpoints

| Breakpoint | Alvo                      | Comportamento                                     |
| ---------- | ------------------------- | ------------------------------------------------- |
| ≤991px     | Tablets pequenos / mobile | Sidebar → offcanvas com overlay, tap targets 44px |
| ≤768px     | Mobile médio              | Censo: tabela → cards, esconde colunas extras     |
| ≤576px     | Mobile pequeno            | Topbar compacta, fontes reduzidas                 |

### Ajustes específicos

| Área              | Melhoria                                                                             |
| ----------------- | ------------------------------------------------------------------------------------ |
| **Sidebar**       | Offcanvas com overlay touch-friendly, hamburger 44×44px, tecla Escape fecha          |
| **Censo**         | Tabela com 5 colunas → cards empilháveis com nome + badges inline                    |
| **Topbar**        | Título com `text-overflow: ellipsis` em telas ≤576px                                 |
| **Touch targets** | Todos botões, links, paginação, inputs ≥44px (WCAG 2.5.5)                            |
| **iOS zoom**      | `font-size: 16px` nos inputs para evitar zoom automático ao focar                    |
| **Tap delay**     | `touch-action: manipulation` remove os 300ms de delay                                |
| **Landing/Login** | Padding reduzido em mobile (`1.25rem`), card ocupa largura total                     |
| **Sidebar links** | Altura mínima 48px, padding ampliado                                                 |
| **Pagination**    | Links com 44×44px, flexbox centering                                                 |
| **Font scaling**  | Stat cards: `1.625rem` (vs `2rem` desktop); nome paciente: `1.125rem` (vs `1.25rem`) |

---

## 8. Decisões Técnicas

### 8.1 Componentização via Template Inheritance

Optou-se por herança de templates Django (`{% extends %}` + `{% include %}`)
ao invés de um framework SPA por:

- Zero dependências novas (já estávamos em Django Templates)
- Coerência com o stack existente (HTMX pode ser adicionado depois)
- Templates são server-side, sem build step
- Fácil manutenção por equipe pequena

### 8.2 Context Processors vs View Context

Dois context processors injetam estado global nos templates:

- `sidebar_context`: determina item ativo do menu pelo `request.path`
- `sync_status`: injeta `sync_time` (demo: "12:45")

Views podem sobrescrever `page_title` passando no contexto. Senão, o context
processor deriva do path.

### 8.3 CSS Custom Properties em vez de SASS/PostCSS

O tema usa variáveis CSS nativas que sobrescrevem as do Bootstrap 5.3.3:

```css
:root {
  --bs-primary: #0d9488; /* Sobrescreve azul Bootstrap */
  --bs-primary-rgb: 13, 148, 136; /* Para rgba() */
  --bs-link-color: var(--bs-primary);
}
```

Isso mantém compatibilidade com todos os componentes Bootstrap (badges, alerts,
buttons, pagination) sem precisar de build step.

### 8.4 Bootstrap Icons via CDN

Adicionado Bootstrap Icons 1.11.3 via CDN no `base.html`. Escolha por:

- Zero bytes no repositório
- Cache do browser entre páginas
- 2.000+ ícones, cobertura completa para healthcare UI
- Consistente com Bootstrap 5.3.3

### 8.5 Dados Demo para Páginas sem Backend

Dashboard e Censo usam dados hardcoded na view. Quando o backend estiver pronto
(`sync_current_inpatients`, queries de contagem), a migração é trivial:
substituir o dicionário por queries Django sem alterar o template.

---

## 9. Backend Modificado

| Arquivo                           | Mudança                                              | Tipo     |
| --------------------------------- | ---------------------------------------------------- | -------- |
| `apps/core/context_processors.py` | `sidebar_context` + `sync_status`                    | **Novo** |
| `apps/core/views.py`              | `page_title` no contexto                             | Alterado |
| `apps/services_portal/views.py`   | `dashboard`, `censo`, `monitor_risco`                | **Novo** |
| `apps/services_portal/urls.py`    | Rotas `/painel/`, `/censo/`, `/monitor/`             | **Novo** |
| `apps/patients/views.py`          | `admission_list_view` unificado com dropdown + idade | Alterado |
| `apps/ingestion/views.py`         | `page_title` nos contextos                           | Alterado |
| `config/settings.py`              | +2 context processors, `LOGIN_REDIRECT_URL=/painel/` | Alterado |
| `config/urls.py`                  | +`include("apps.services_portal.urls")`              | Alterado |

---

## 10. Testes

### Testes modificados

| Arquivo                               | Mudanças                  | Razão                                       |
| ------------------------------------- | ------------------------- | ------------------------------------------- |
| `tests/unit/test_navigation_views.py` | 12 assertions atualizadas | Textos e URLs alterados nos novos templates |

### Cobertura de gate

```bash
./scripts/test-in-container.sh check      # ✅ 0 issues
./scripts/test-in-container.sh unit       # ✅ 298 passed
./scripts/test-in-container.sh lint       # ✅ All checks passed
./scripts/test-in-container.sh typecheck  # ✅ No errors
```

---

## 11. Arquivos Alterados (Manifesto Completo)

```
32 files changed, 2401 insertions(+), 816 deletions(-)
```

### Novos (14 arquivos)

```
static/css/sirhosp.css
templates/base.html
templates/base_sidebar.html
templates/includes/sidebar.html
templates/includes/topbar.html
apps/core/context_processors.py
apps/services_portal/views.py
apps/services_portal/urls.py
apps/services_portal/templates/services_portal/dashboard.html
apps/services_portal/templates/services_portal/censo.html
apps/services_portal/templates/services_portal/monitor_risco.html
```

### Modificados (17 arquivos)

```
apps/core/templates/core/home.html
apps/core/views.py
apps/ingestion/templates/ingestion/create_run.html
apps/ingestion/templates/ingestion/create_admissions_only.html
apps/ingestion/templates/ingestion/run_status.html
apps/ingestion/views.py
apps/patients/templates/patients/patient_list.html
apps/patients/templates/patients/admission_list.html
apps/patients/templates/patients/timeline.html
apps/patients/templates/patients/404.html
apps/patients/views.py
config/settings.py
config/urls.py
templates/registration/login.html
tests/unit/test_navigation_views.py
```

### Removidos (1 arquivo)

```
templates/includes/navbar.html              ← substituído por sidebar + topbar
```

### Wireframes (5 arquivos — já existiam, apenas atualizados)

```
wireframes/dashboard.md
wireframes/busca-setores.md
wireframes/busca-historico.md
wireframes/busca-termos-riscos.md
wireframes/detalhes-paciente.md
```

---

## 12. Próximos Passos Sugeridos

### Prioridade alta (desbloqueia funcionalidade real)

1. **Dashboard — queries reais:**
   - Internados: `Admission.objects.filter(discharge_date__isnull=True).count()`
   - Cadastrados: `Patient.objects.count()`
   - Altas 24h: `Admission.objects.filter(discharge_date__gte=...)`
   - `sync_time`: ler `finished_at` do último `IngestionRun` bem-sucedido

2. **Censo — backend real:**
   - Implementar `sync_current_inpatients` management command
   - Substituir `pacientes_demo` por query real com `ward`/`bed` de internações ativas

### Prioridade média (qualidade de vida)

1. **Highlight de termos no Monitor de Risco:**
   - Criar template filter `highlight_term` para destacar termos nos snippets

2. **Testes das novas páginas:**
   - Adicionar `test_dashboard_view`, `test_censo_view`, `test_monitor_risco_view`

### Prioridade baixa (nice to have)

1. **`/search/clinical-events/`:**
   - Avaliar se mantém JSON API + cria HTML page, ou migra para HTML-only

2. **HTMX para navegação SPA-like:**
   - Carregar conteúdo sem reload completo da página
   - O `django-htmx` já está em `INSTALLED_APPS`

---

## 13. Referências

- [Arquitetura SIRHOSP](docs/architecture.md)
- [ADR-0001 — Monólito Django + PostgreSQL](docs/adr/ADR-0001-monolito-django-postgresql-e-jobs-agendados.md)
- [ADR-0002 — Modelagem Canônica de Eventos](docs/adr/ADR-0002-modelagem-canonica-eventos-clinicos-e-reconciliacao.md)
- [AGENTS.md](AGENTS.md) — Regras de qualidade e workflow
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — Resumo executivo
- [Wireframes](wireframes/) — Blueprints das páginas
