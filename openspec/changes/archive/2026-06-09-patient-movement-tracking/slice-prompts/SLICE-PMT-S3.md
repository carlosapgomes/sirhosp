# SLICE-PMT-S3: Trajetória nos detalhes da internação

## Handoff para executor LLM (contexto zero)

Você está recebendo este arquivo como única fonte de instrução. Antes de
codificar, leia **obrigatoriamente** nesta ordem:

1. `/projects/dev/sirhosp/AGENTS.md` — stack, comandos, política de testes
2. `/projects/dev/sirhosp/PROJECT_CONTEXT.md` — visão geral do sistema
3. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/proposal.md`
4. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/design.md`
5. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/tasks.md`
6. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/specs/patient-trajectory-view/spec.md`

**Implemente SOMENTE o Slice PMT-S3 e PARE.**

**Pré-requisito:** Os Slices PMT-S1 (modelo) e PMT-S2 (serviço) já devem
estar concluídos, com `PatientMovement` populado no banco.

---

## Objetivo

Adicionar uma timeline visual da trajetória do paciente na página de detalhes
da internação (`admission_list.html`), exibindo os setores por onde passou e
quantos dias ficou em cada um.

---

## Escopo máximo de arquivos

Você pode alterar **no máximo 3 arquivos**:

| Arquivo | Ação |
| --- | --- |
| `apps/patients/views.py` | Adicionar `movements` ao contexto da view existente |
| `apps/patients/templates/patients/_patient_trajectory.html` | NOVO — partial com timeline |
| `apps/patients/templates/patients/admission_list.html` | Incluir a partial |

Se precisar alterar qualquer outro arquivo, **pare e reporte bloqueio**.

---

## Especificação

### 1. Partial `_patient_trajectory.html`

Crie o arquivo `apps/patients/templates/patients/_patient_trajectory.html`.
Use Bootstrap 5 (já disponível no projeto) e HTMX se necessário (também já
disponível). **Não introduza novos frameworks CSS/JS.**

A partial espera uma variável de contexto `trajectory` — uma lista de dicts
com a estrutura:

```python
trajectory = [
    {
        "sector": "PS PED",
        "entry_date": date(2026, 5, 20),
        "days": 1,
        "origin": "",                  # vazio = primeiro setor
        "discharge_type": "",
        "is_active": False,            # não é o setor atual
    },
    {
        "sector": "ENF PED",
        "entry_date": date(2026, 5, 21),
        "days": 6,
        "origin": "PS PED",
        "discharge_type": "",
        "is_active": True,             # setor atual
    },
]
```

O template deve renderizar:

**Quando há trajetória:**
- **Linha do tempo horizontal:** cada setor como um card com:
  - Nome do setor em destaque
  - Data de entrada (`DD/MM`)
  - Dias no setor
  - Origem (ex: "Veio de PS PED"), se não for o primeiro
  - Indicador visual de seta entre setores
  - Badge "(atual)" para o setor corrente, ou badge com tipo de alta se
    `discharge_type` não vazio
- **Tabela resumo** abaixo da timeline com colunas: Setor, Entrada, Dias,
  Destino/Status

**Quando não há trajetória (`trajectory` vazia ou `None`):**
- Card com ícone e mensagem: "Trajetória ainda não disponível. Os dados de
  movimentação começam a ser registrados a partir da primeira coleta após a
  ativação desta funcionalidade."

### 2. View (`admission_list_view` em `apps/patients/views.py`)

Adicione ao contexto da view existente a variável `trajectory`. A lógica deve:

1. Se `selected_admission` existe, buscar `PatientMovement` do paciente
   ordenados por `sequence`.
2. Converter para a lista de dicts descrita acima, calculando `days` como a
   diferença em dias entre `movement_date` deste movimento e do próximo (ou
   até hoje para o último, se `discharge_type` vazio).
3. Se não houver movimentos, `trajectory = []`.

**Cálculo de dias:**

```python
from datetime import date

movements = list(
    PatientMovement.objects.filter(
        patient=selected_admission.patient,
    ).order_by("sequence")
)

trajectory = []
for i, m in enumerate(movements):
    if i + 1 < len(movements):
        days = (movements[i + 1].movement_date - m.movement_date).days
    else:
        if m.discharge_type:
            days = (m.movement_date - m.movement_date).days  # 0 — último dia
        else:
            days = (date.today() - m.movement_date).days

    trajectory.append({
        "sector": m.sector,
        "entry_date": m.movement_date,
        "days": max(days, 0),
        "origin": m.origin,
        "discharge_type": m.discharge_type,
        "is_active": (i == len(movements) - 1 and not m.discharge_type),
    })
```

### 3. Inclusão no template principal

No template `admission_list.html`, após o bloco de informações da admissão
(antes ou depois dos eventos clínicos), inclua:

```django
{% include "patients/_patient_trajectory.html" with trajectory=trajectory %}
```

**Dica:** Posicione a trajetória entre o banner do paciente/seletor de
admissão e a tabela de eventos clínicos. Use um `<hr>` ou margem para separar
visualmente.

---

## Metodologia TDD

### 1. RED — Escreva testes que falham

**Onde:** Estenda `tests/unit/test_services_portal_sectors.py` se ele existir,
ou crie `tests/unit/test_patient_trajectory.py`.

| Teste | O que verifica |
| --- | --- |
| `test_admission_view_includes_trajectory_when_movements_exist` | Cria `Patient` + `Admission` + 2 `PatientMovement`. Acessa a view. Contexto contém `trajectory` com 2 itens. |
| `test_admission_view_empty_trajectory_when_no_movements` | Sem `PatientMovement` no banco. `trajectory` é lista vazia. |
| `test_trajectory_calculates_days_correctly` | Dois movimentos com 3 dias de diferença. `days` do primeiro = 3. Último ativo: `days` = (today - movement_date). |
| `test_trajectory_shows_origin_for_non_first` | Segundo movimento tem `origin="PS"`. Dict contém `origin="PS"`. Primeiro tem `origin=""`. |
| `test_trajectory_active_flag` | Último movimento sem `discharge_type` → `is_active=True`. Penúltimo → `is_active=False`. |
| `test_trajectory_discharge_closes_trajectory` | Último movimento com `discharge_type="A"` → `is_active=False`, `discharge_type="A"`. |
| `test_template_renders_trajectory_html` | Verifica que o HTML contém o nome do setor do primeiro movimento. |
| `test_template_empty_state_html` | Sem movimentos, HTML contém mensagem "ainda não disponível". |

### 2. GREEN — Implemente o mínimo

- Adicione a lógica de `trajectory` na view existente.
- Crie a partial `_patient_trajectory.html`.
- Inclua a partial no template principal com `{% include %}`.
- **Mantenha o template simples.** Não adicione JavaScript, animações ou
  features não especificadas.

### 3. REFACTOR

- Extraia o cálculo de trajetória para uma função auxiliar em
  `apps/patients/services.py` se achar necessário (mas é opcional — mantenha
  YAGNI se a função só for usada na view).
- Verifique que o HTML usa classes Bootstrap existentes no projeto.
- Confirme que não há HTML quebrado quando `trajectory` é vazio.

---

## Gates de validação

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

---

## Relatório obrigatório

Gere `/tmp/sirhosp-slice-PMT-S3-report.md`:

```markdown
# Relatório SLICE-PMT-S3

## 1. Resumo

## 2. Checklist de aceite
- [ ] Testes RED escritos e falharam
- [ ] View retorna trajectory no contexto
- [ ] Partial _patient_trajectory.html criada
- [ ] Template principal inclui a partial
- [ ] Cálculo de dias por setor correto
- [ ] Estado vazio tratado
- [ ] Todos os testes passam
- [ ] Lint sem erros

## 3. Arquivos alterados

## 4. Fragmentos antes/depois
(Para views.py, novo template, include no template)

## 5. Comandos executados e resultados

## 6. Riscos e pendências
- A trajetória só mostra dados a partir da primeira coleta pós-ativação
- O cálculo de dias usa date.today() para o setor ativo

## 7. Próximo passo sugerido
SLICE-PMT-S4: página Setores > Ocupação
```

---

## Stop Rule

- **Não** crie views, URLs ou templates para as páginas de Setores.
- **Não** altere o sidebar.
- Ao terminar, **pare** e aguarde revisão humana.
