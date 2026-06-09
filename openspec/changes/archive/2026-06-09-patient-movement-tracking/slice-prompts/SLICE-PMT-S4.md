# SLICE-PMT-S4: Página Setores > Ocupação

## Handoff para executor LLM (contexto zero)

Você está recebendo este arquivo como única fonte de instrução. Antes de
codificar, leia **obrigatoriamente** nesta ordem:

1. `/projects/dev/sirhosp/AGENTS.md` — stack, comandos, política de testes
2. `/projects/dev/sirhosp/PROJECT_CONTEXT.md` — visão geral do sistema
3. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/proposal.md`
4. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/design.md`
5. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/tasks.md`
6. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/specs/sector-occupation-page/spec.md`
7. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/specs/sidebar-sectors-menu/spec.md`

**Implemente SOMENTE o Slice PMT-S4 e PARE.**

**Pré-requisito:** Slices PMT-S1 a PMT-S3 concluídos.

---

## Objetivo

Criar a página **Setores > Ocupação** (`/setores/ocupacao/`) com:
- Filtro por setor e período
- Cards de resumo (total pacientes, ainda no setor, saíram, permanência média)
- Tabela de pacientes com entrada, dias e destino
- Item "Setores" no sidebar com submenu Ocupação/Indicadores

---

## Escopo máximo de arquivos

Você pode alterar **no máximo 5 arquivos**:

| Arquivo | Ação |
| --- | --- |
| `apps/services_portal/views.py` | Adicionar view `sector_occupation` |
| `apps/services_portal/urls.py` | Adicionar rota `/setores/ocupacao/` |
| `apps/services_portal/templates/services_portal/sector_occupation.html` | NOVO — template |
| `apps/services_portal/templates/base_sidebar.html` | Adicionar menu Setores |
| `tests/unit/test_services_portal_sectors.py` | NOVO — testes |

Se precisar alterar qualquer outro arquivo, **pare e reporte bloqueio**.

---

## Especificação

### 1. View `sector_occupation`

Arquivo: `apps/services_portal/views.py`

```python
@login_required
def sector_occupation(request: HttpRequest) -> HttpResponse:
```

**Parâmetros GET:**
- `setor` — nome do setor (string). Default: primeiro setor do último snapshot.
- `dias` — período em dias (7, 30, 90). Default: 7.

**Lógica:**

1. Buscar período: `cutoff = timezone.now() - timedelta(days=dias)`
2. Lista de setores para o dropdown: valores distintos de `sector` em
   `PatientMovement.objects.values_list('sector', flat=True).distinct().order_by('sector')`.
   Se não houver, use setores do último `CensusSnapshot`.
3. Filtrar `PatientMovement` pelo `sector` selecionado e
   `first_seen_at__gte=cutoff`.
4. Calcular cards de resumo:
   - **total:** `count()` da queryset
   - **still_in:** `filter(discharge_type='').count()`
   - **left:** `exclude(discharge_type='').count()`
   - **avg_stay:** média de `(last_seen_at - first_seen_at)` em dias (use
     `Avg` com `ExpressionWrapper` e `F`, ou calcule em Python se <1000
     registros)
5. Montar tabela: cada movimento → nome do paciente (via `select_related`),
   data de entrada (`movement_date`), dias no setor, destino (próximo setor
   ou `discharge_type`). Ordenar por `movement_date` DESC.

**Contexto do template:**

```python
context = {
    "page_title": "Setores — Ocupação",
    "sectors": sectors_list,
    "selected_sector": sector,
    "period_days": dias,
    "period_options": [7, 30, 90],
    "summary": {
        "total": int,
        "still_in": int,
        "left": int,
        "avg_stay_days": float or None,
    },
    "patients": [
        {
            "name": str,
            "prontuario": str,
            "entry_date": date,
            "days": int,
            "destination": str,  # próximo setor, tipo de alta, ou "(no setor)"
        },
        ...
    ],
    "active_tab": "setores",
}
```

### 2. Template `sector_occupation.html`

Siga o mesmo padrão visual de `ingestion_metrics.html` e dos templates do
portal (breadcrumb, cards `sirhosp-stat-card`, tabela Bootstrap).

Estrutura:

```text
┌─ Breadcrumb: Dashboard > Setores > Ocupação
├─ Título + descrição
├─ Filtros: [dropdown setor] [dropdown período 7/30/90] [btn Filtrar]
├─ Cards de resumo (4 colunas):
│   ├─ Pacientes que passaram
│   ├─ Ainda no setor
│   ├─ Já saíram
│   └─ Permanência média
├─ Tabela: Nome | Prontuário | Entrada | Dias | Destino
└─ Estado vazio se nenhum paciente no período
```

### 3. Sidebar: menu Setores

Arquivo: `apps/services_portal/templates/base_sidebar.html`

Adicione um item expansível "Setores" abaixo de "Censo". Use o mesmo padrão
de dropdown/accordion já existente no sidebar. Exemplo de estrutura HTML:

```html
<li class="nav-item">
  <a class="nav-link d-flex align-items-center gap-2" data-bs-toggle="collapse"
     href="#sidebar-setores" role="button">
    <i class="bi bi-geo-alt"></i> Setores
    <i class="bi bi-chevron-down ms-auto small"></i>
  </a>
  <div class="collapse" id="sidebar-setores">
    <ul class="nav flex-column ms-3">
      <li class="nav-item">
        <a class="nav-link small {% if request.path == '/setores/ocupacao/' %}active{% endif %}"
           href="{% url 'services_portal:sector_occupation' %}">
          Ocupação
        </a>
      </li>
      <li class="nav-item">
        <a class="nav-link small"
           href="{% url 'services_portal:sector_indicators' %}">
          Indicadores
        </a>
      </li>
    </ul>
  </div>
</li>
```

**Nota:** O link para Indicadores pode apontar para uma URL que ainda não
existe — ela será criada no PMT-S5. Use `#` como fallback temporário se
preferir, ou crie a rota dummy.

### 4. URL

Arquivo: `apps/services_portal/urls.py`

```python
path("setores/ocupacao/", views.sector_occupation, name="sector_occupation"),
```

---

## Metodologia TDD

### 1. RED — Escreva testes que falham

Arquivo: `tests/unit/test_services_portal_sectors.py`

| Teste | O que verifica |
| --- | --- |
| `test_occupation_page_requires_auth` | Anônimo → redirect para login. |
| `test_occupation_page_renders_authenticated` | Autenticado → HTTP 200. |
| `test_occupation_filters_by_sector` | Query com `?setor=UTI` filtra `PatientMovement` por sector. |
| `test_occupation_default_period_7_days` | Sem `?dias=`, usa período de 7 dias. |
| `test_occupation_respects_period_param` | `?dias=30` usa cutoff de 30 dias. |
| `test_occupation_summary_cards` | Contexto contém `summary.total`, `still_in`, `left`, `avg_stay_days`. |
| `test_occupation_patient_table_ordered` | Pacientes ordenados por data de entrada DESC. |
| `test_occupation_empty_state` | Setor sem movimentos no período → template mostra mensagem. |

### 2. GREEN — Implemente o mínimo

- Adicione a view, URL, template e sidebar.
- Use `select_related('patient')` para evitar N+1 queries na tabela.
- Mantenha o template consistente com o estilo visual existente.

### 3. REFACTOR

- Extraia queries repetidas para métodos no model ou manager se fizer sentido.
- Verifique que os nomes de URL seguem o padrão `services_portal:view_name`.

---

## Gates de validação

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

---

## Relatório obrigatório

Gere `/tmp/sirhosp-slice-PMT-S4-report.md`:

```markdown
# Relatório SLICE-PMT-S4

## 1. Resumo

## 2. Checklist de aceite
- [ ] Testes RED escritos e falharam
- [ ] View sector_occupation implementada
- [ ] Rota /setores/ocupacao/ funcionando
- [ ] Template renderiza filtros, cards e tabela
- [ ] Sidebar com menu Setores
- [ ] Estado vazio tratado
- [ ] Todos os testes passam
- [ ] Lint sem erros

## 3. Arquivos alterados

## 4. Fragmentos antes/depois

## 5. Comandos executados e resultados

## 6. Riscos e pendências
- Link de Indicadores no sidebar aponta para view ainda não implementada
- Cálculo de avg_stay pode ser pesado com muitos registros

## 7. Próximo passo sugerido
SLICE-PMT-S5: página Setores > Indicadores
```

---

## Stop Rule

- **Não** implemente a página de Indicadores.
- **Não** altere views, modelos ou serviços fora do escopo.
- Ao terminar, **pare** e aguarde revisão humana.
