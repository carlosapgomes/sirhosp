# SLICE-CES-S1: Nomes completos de especialidades na UI

## Handoff para executor LLM com contexto zero

Você está recebendo este arquivo como fonte principal de instrução. Antes de
codificar, leia obrigatoriamente nesta ordem:

1. `/projects/dev/sirhosp/AGENTS.md`
2. `/projects/dev/sirhosp/PROJECT_CONTEXT.md`
3. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/proposal.md`
4. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/design.md`
5. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/tasks.md`
6. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/specs/censo-current-list-export/spec.md`

Implemente **somente** o Slice CES-S1 e pare. Não implemente exportação XLSX
neste slice.

Não leia nem exponha `.env`. Não imprima dados reais de pacientes. Use apenas
fixtures sintéticas/anônimas nos testes.

---

## Objetivo

Melhorar a página `/censo/` para que usuários vejam o nome completo das
especialidades no dropdown, na tabela desktop e nos cards mobile, preservando o
filtro pelo valor gravado em `CensusSnapshot.especialidade`.

Estado atual relevante:

- View: `apps/services_portal/views.py`, função `censo`.
- Template: `apps/services_portal/templates/services_portal/censo.html`.
- Testes: `tests/unit/test_services_portal_censo.py`.
- Catálogo: `apps.census.models.Specialty` com campos `code` e `name`.

A view já possui lógica de resolução código ↔ nome para pacientes, mas o
template renderiza `p.especialidade` como texto principal e usa
`p.especialidade_nome` apenas em `title`.

---

## Escopo máximo de arquivos

Você pode alterar no máximo 4 arquivos:

| Arquivo | Ação esperada |
| --- | --- |
| `apps/services_portal/views.py` | Montar opções de especialidade com label completo |
| `apps/services_portal/templates/services_portal/censo.html` | Renderizar labels completos |
| `tests/unit/test_services_portal_censo.py` | Testes RED/GREEN da UI |
| `openspec/changes/enhance-censo-specialty-display-and-export/tasks.md` | Marcar CES-S1 ao final |

Se precisar alterar qualquer outro arquivo, pare e reporte bloqueio no relatório.

---

## Requisitos funcionais

1. O dropdown `Especialidade` deve exibir o nome completo quando existir
   `Specialty` correspondente.
2. O `value` da opção deve continuar sendo o valor usado para filtrar o snapshot
   atual, normalmente o código como `NEF`.
3. A coluna `Especialidade` da tabela desktop deve mostrar o nome completo.
4. O card mobile deve mostrar o nome completo.
5. Se o snapshot contiver valor sem cadastro em `Specialty`, a página deve
   exibir o valor original sem erro.
6. O filtro por especialidade deve continuar funcionando.

---

## Metodologia TDD

### RED 1 — dropdown com nome completo

Em `tests/unit/test_services_portal_censo.py`, adicione teste que:

1. cria `Specialty.objects.create(code="NEF", name="NEFROLOGIA")`;
2. cria `CensusSnapshot` ocupado com `especialidade="NEF"`;
3. acessa `reverse("services_portal:censo")` com `admin_client`;
4. verifica que `NEFROLOGIA` aparece no HTML do dropdown;
5. verifica que o option preserva `value="NEF"`.

### RED 2 — tabela e card mostram nome completo

Crie teste com `Specialty(code="CIV", name="CIRURGIA VASCULAR")` e paciente
ocupado. Valide que `CIRURGIA VASCULAR` aparece como texto principal da página.
Se necessário, use asserts simples de HTML para evitar acoplar a classes CSS.

### RED 3 — filtro continua por código

Crie dois snapshots ocupados, um `NEF` e um `CIV`, ambos com catálogo. Acesse:

```text
/censo/?especialidade=NEF
```

Valide que só o paciente de `NEF` aparece e que o dropdown mantém a opção
selecionada.

### RED 4 — fallback seguro

Crie snapshot com `especialidade="XYZ"` sem `Specialty`. Valide que `XYZ`
aparece e a página retorna `200`.

Rode o teste antes da implementação e registre no relatório que ele falhou pelo
motivo esperado.

---

## Diretrizes de implementação

- Prefira helper pequeno e privado para resolver labels, mas não faça uma grande
  refatoração neste slice. O helper comum do resultado do censo será o CES-S2.
- Evite duplicar queries desnecessárias para `Specialty`; carregue o catálogo em
  dicionários uma vez por request.
- Para `especialidade_options`, use estrutura explícita:

```python
{
    "value": raw_value,
    "label": full_name_or_raw_value,
    "code": code_or_raw_value,
}
```

- No template, troque o loop de strings por loop de dicionários:

```django
<option value="{{ opt.value }}" {% if especialidade_filter == opt.value %}selected{% endif %}>{{ opt.label }}</option>
```

- Para pacientes, renderize `p.especialidade_nome` como texto principal quando
  existir. Mantenha fallback para `p.especialidade`.
- Não altere comportamento de `/censo-oficial/`.
- Não introduza dependências.

---

## Critérios de aceitação

- Dropdown mostra nomes completos de especialidade quando cadastrados.
- Tabela desktop mostra nomes completos na coluna `Especialidade`.
- Cards mobile mostram nomes completos.
- Filtro por especialidade continua funcionando com valores existentes.
- Valores desconhecidos de especialidade usam fallback seguro.
- Nenhum comportamento de exportação XLSX foi implementado neste slice.

---

## Gates de autoavaliação

Execute, no mínimo:

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
```

Se o tempo estiver curto, priorize o teste unitário específico e reporte gates
não executados com justificativa. O caminho oficial continua sendo container.

---

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-CES-S1-report.md` contendo:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- evidência RED e GREEN dos testes;
- trechos antes/depois por arquivo alterado;
- comandos executados e resultados;
- riscos, pendências e próximo passo sugerido.

Não inclua dados reais, credenciais ou conteúdo sensível no relatório.
