# SLICE-CES-S3: Endpoint autenticado de exportação XLSX

## Handoff para executor LLM com contexto zero

Você está recebendo este arquivo como fonte principal de instrução. Antes de
codificar, leia obrigatoriamente nesta ordem:

1. `/projects/dev/sirhosp/AGENTS.md`
2. `/projects/dev/sirhosp/PROJECT_CONTEXT.md`
3. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/proposal.md`
4. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/design.md`
5. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/tasks.md`
6. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/specs/censo-current-list-export/spec.md`
7. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/slice-prompts/SLICE-CES-S2.md`

Implemente **somente** o Slice CES-S3 e pare. Pressuponha que CES-S1 e CES-S2
já foram implementados. Se o helper comum do CES-S2 não existir, pare e reporte
bloqueio.

Não leia nem exponha `.env`. Não imprima dados reais de pacientes. Use apenas
fixtures sintéticas/anônimas nos testes.

---

## Objetivo

Criar endpoint autenticado que exporta para XLSX o resultado atual do censo,
reutilizando o helper comum criado no CES-S2. Este slice implementa o backend de
download, mas não adiciona botão na tela; o botão será o CES-S4.

---

## Escopo máximo de arquivos

Você pode alterar no máximo 4 arquivos:

| Arquivo | Ação esperada |
| --- | --- |
| `apps/services_portal/views.py` | View de exportação e geração XLSX |
| `apps/services_portal/urls.py` | Rota dedicada de exportação |
| `tests/unit/test_services_portal_censo.py` | Testes do endpoint XLSX |
| `openspec/changes/enhance-censo-specialty-display-and-export/tasks.md` | Marcar CES-S3 ao final |

Se precisar alterar template, modelo ou migration, pare e reporte bloqueio.

---

## Requisitos funcionais

1. A exportação deve exigir autenticação via `login_required`.
2. A rota recomendada é:

   ```text
   /censo/exportar/
   ```

   usando nome de rota claro, por exemplo
   `services_portal:censo_export_xlsx`.
3. O endpoint deve aceitar os mesmos query parameters de `/censo/`:
   - `q`;
   - `unidade`;
   - `especialidade`;
   - `ordenar`.
4. O workbook deve conter as colunas mínimas:
   - `Registro`;
   - `Nome`;
   - `Setor / Unidade`;
   - `Leito`;
   - `Especialidade`;
   - `Data Internação`;
   - `Tempo Internação`;
   - `Capturado em`.
5. A coluna `Especialidade` deve usar o nome completo, com fallback seguro.
6. A resposta deve usar content type XLSX e `Content-Disposition` com `.xlsx`.
7. A geração deve ser em memória, sem arquivo temporário em disco.

---

## Metodologia TDD

### RED 1 — autenticação

Adicione teste em `tests/unit/test_services_portal_censo.py` validando que
cliente anônimo ao acessar a rota de exportação recebe redirect para login.

### RED 2 — resposta XLSX válida

Adicione teste com `admin_client` que:

1. cria snapshot ocupado sintético;
2. acessa a rota de exportação;
3. valida status `200`;
4. valida content type XLSX;
5. valida `Content-Disposition` contendo `.xlsx`;
6. abre `response.content` com `openpyxl.load_workbook(BytesIO(...))`.

### RED 3 — colunas e nomes completos

No mesmo teste ou em teste separado, valide cabeçalhos e uma linha de dados com
especialidade resolvida pelo catálogo `Specialty`.

### RED 4 — filtros respeitados

Crie dois pacientes sintéticos e exporte com query params, por exemplo:

```text
?especialidade=NEF&q=ALFA
```

Valide que o workbook contém apenas o paciente esperado.

### RED 5 — estado vazio válido

Valide que exportar sem snapshot retorna workbook válido com cabeçalhos e sem
linhas de pacientes.

Rode os testes antes da implementação e registre a falha esperada no relatório.

---

## Diretrizes de implementação

- Reutilize o helper comum do CES-S2. Não replique query/filtro manualmente no
  endpoint.
- Use `openpyxl.Workbook` e `io.BytesIO`.
- Não use `pandas` nem dependências novas.
- Estilização básica de cabeçalho é aceitável, mas não necessária. Priorize
  simplicidade e testes.
- Nome de arquivo recomendado:

```text
censo-hospitalar-YYYYMMDD-HHMM.xlsx
```

Use `captured_at` quando disponível; se não houver snapshot, use data/hora
local atual.
- Não logue nomes de pacientes, prontuários ou conteúdo do workbook.
- Não adicione botão no template neste slice.

---

## Critérios de aceitação

- Endpoint de exportação existe e exige autenticação.
- XLSX retornado é válido e abre com `openpyxl`.
- Workbook contém cabeçalhos mínimos e dados sintéticos esperados.
- Filtros e ordenação são os mesmos da página `/censo/`.
- Exportação usa nomes completos de especialidade.
- Nenhum arquivo temporário é criado em disco.

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

Crie `/tmp/sirhosp-slice-CES-S3-report.md` contendo:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- evidência RED e GREEN dos testes;
- trechos antes/depois por arquivo alterado;
- comandos executados e resultados;
- riscos, pendências e próximo passo sugerido.

Não inclua dados reais, credenciais ou conteúdo sensível no relatório.
