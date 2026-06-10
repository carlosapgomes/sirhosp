# SLICE-CES-S2: Helper comum do resultado do censo

## Handoff para executor LLM com contexto zero

Você está recebendo este arquivo como fonte principal de instrução. Antes de
codificar, leia obrigatoriamente nesta ordem:

1. `/projects/dev/sirhosp/AGENTS.md`
2. `/projects/dev/sirhosp/PROJECT_CONTEXT.md`
3. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/proposal.md`
4. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/design.md`
5. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/tasks.md`
6. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/specs/censo-current-list-export/spec.md`
7. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/slice-prompts/SLICE-CES-S1.md`

Implemente **somente** o Slice CES-S2 e pare. Pressuponha que CES-S1 já foi
implementado. Se CES-S1 não estiver implementado, pare e reporte bloqueio.

Não leia nem exponha `.env`. Não imprima dados reais de pacientes. Use apenas
fixtures sintéticas/anônimas nos testes.

---

## Objetivo

Extrair a montagem do resultado de `/censo/` para um helper privado e
reutilizável, preparando a exportação XLSX sem duplicar filtros, ordenação e
enriquecimento de dados.

Este slice deve ser uma refatoração com testes de caracterização: o
comportamento HTML existente deve permanecer equivalente.

---

## Escopo máximo de arquivos

Você pode alterar no máximo 3 arquivos:

| Arquivo | Ação esperada |
| --- | --- |
| `apps/services_portal/views.py` | Extrair helper privado e usar na view `censo` |
| `tests/unit/test_services_portal_censo.py` | Testes de caracterização |
| `openspec/changes/enhance-censo-specialty-display-and-export/tasks.md` | Marcar CES-S2 ao final |

Se precisar alterar template, URL, modelo ou migration, pare e reporte bloqueio.

---

## Requisitos funcionais

1. A view `censo` deve continuar retornando a mesma página e o mesmo contexto
   observável pelos testes.
2. A lógica comum deve ficar disponível em helper privado do módulo, para uso
   posterior pelo endpoint XLSX.
3. O helper deve aplicar os mesmos parâmetros de request usados hoje:
   - `q`;
   - `unidade`;
   - `especialidade`;
   - `ordenar`.
4. O helper deve retornar `pacientes`, `total`, `captured_at`, filtros ativos e
   opções de dropdown.
5. Não deve haver alteração intencional de UI neste slice.

---

## Metodologia TDD

### RED 1 — filtros combinados

Adicione teste de caracterização que cria pacientes sintéticos em setores e
especialidades diferentes, acessa `/censo/` com combinação de `q`, `unidade` e
`especialidade`, e valida que somente o paciente esperado aparece.

### RED 2 — ordenação por especialidade ou tempo

Adicione teste simples para garantir que `ordenar=especialidade` ou
`ordenar=tempo_desc` mantém ordenação esperada. Use `response.context` se for
mais estável que comparar posições no HTML.

### RED 3 — estado vazio preservado

Adicione teste que acessa `/censo/` sem snapshots e valida que o contexto contém
`pacientes=[]`, `total=0` e `captured_at is None`.

Rode os testes antes da refatoração e registre no relatório. Se algum teste
passar antes por já estar coberto, registre como teste de caracterização, não
como falha esperada.

---

## Diretrizes de implementação

- Crie helper privado em `apps/services_portal/views.py`. Nome sugerido:

```python
def _build_censo_context(request: HttpRequest) -> dict[str, Any]:
    ...
```

- A view `censo` deve ficar fina:

```python
@login_required
def censo(request: HttpRequest) -> HttpResponse:
    context = _build_censo_context(request)
    return render(request, "services_portal/censo.html", context)
```

- O helper deve centralizar a lógica atual, incluindo:
  - busca do `latest` via `Max("captured_at")`;
  - query base de `CensusSnapshot` ocupado;
  - aplicação de filtros;
  - lookup de `Patient`;
  - lookup de `Admission` ativa;
  - cálculo de tempo de internação;
  - resolução de especialidade;
  - ordenação;
  - montagem de opções de unidade e especialidade.
- Não crie abstrações genéricas demais. O helper deve atender apenas ao censo.
- Não altere nomes de chaves de contexto consumidas pelo template.
- Não implemente exportação XLSX neste slice.

---

## Critérios de aceitação

- `censo` usa helper comum e permanece simples.
- Testes existentes de `/censo/` continuam passando.
- Novos testes de caracterização cobrem filtros combinados, ordenação e estado
  vazio.
- Nenhuma rota ou template foi alterado.
- O helper poderá ser reutilizado pelo Slice CES-S3 sem duplicação relevante.

---

## Gates de autoavaliação

Execute, no mínimo:

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
```

Se algum gate não for executado, registre justificativa objetiva no relatório.

---

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-CES-S2-report.md` contendo:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- evidência dos testes antes/depois da refatoração;
- trechos antes/depois por arquivo alterado;
- comandos executados e resultados;
- riscos, pendências e próximo passo sugerido.

Não inclua dados reais, credenciais ou conteúdo sensível no relatório.
