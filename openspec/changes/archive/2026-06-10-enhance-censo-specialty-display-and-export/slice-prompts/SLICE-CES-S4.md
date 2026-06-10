# SLICE-CES-S4: Botão de exportação na página `/censo/`

## Handoff para executor LLM com contexto zero

Você está recebendo este arquivo como fonte principal de instrução. Antes de
codificar, leia obrigatoriamente nesta ordem:

1. `/projects/dev/sirhosp/AGENTS.md`
2. `/projects/dev/sirhosp/PROJECT_CONTEXT.md`
3. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/proposal.md`
4. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/design.md`
5. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/tasks.md`
6. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/specs/censo-current-list-export/spec.md`
7. `/projects/dev/sirhosp/openspec/changes/enhance-censo-specialty-display-and-export/slice-prompts/SLICE-CES-S3.md`

Implemente **somente** o Slice CES-S4 e pare. Pressuponha que CES-S3 já criou a
rota de exportação. Se a rota não existir, pare e reporte bloqueio.

Não leia nem exponha `.env`. Não imprima dados reais de pacientes. Use apenas
fixtures sintéticas/anônimas nos testes.

---

## Objetivo

Adicionar à página `/censo/` um botão visível `Exportar Excel` que chama o
endpoint XLSX do CES-S3 preservando os filtros e ordenação atuais.

Este slice deve ser somente integração de UI. Não altere a geração do workbook,
exceto se encontrar bug bloqueante no endpoint; nesse caso, pare e reporte.

---

## Escopo máximo de arquivos

Você pode alterar no máximo 3 arquivos:

| Arquivo | Ação esperada |
| --- | --- |
| `apps/services_portal/templates/services_portal/censo.html` | Botão/link de exportação |
| `tests/unit/test_services_portal_censo.py` | Teste do link preservando filtros |
| `openspec/changes/enhance-censo-specialty-display-and-export/tasks.md` | Marcar CES-S4 ao final |

Se precisar alterar view, URL, modelo ou migration, pare e reporte bloqueio.

---

## Requisitos funcionais

1. A página `/censo/` deve exibir botão ou link com texto `Exportar Excel`.
2. O link deve apontar para a rota de exportação implementada no CES-S3.
3. O link deve preservar a querystring atual, incluindo:
   - `q`;
   - `unidade`;
   - `especialidade`;
   - `ordenar`.
4. O botão deve ficar próximo ao título ou aos filtros, sem prejudicar o layout
   atual.
5. O botão não deve aparecer como submissão do formulário de filtros se isso
   dificultar preservar a intenção de download. Um link `<a>` é suficiente.

---

## Metodologia TDD

### RED 1 — link de exportação existe

Adicione teste que acessa `/censo/` com `admin_client` e valida que o HTML
contém `Exportar Excel` e a URL da rota de exportação.

### RED 2 — querystring preservada

Adicione teste acessando:

```text
/censo/?q=ALFA&unidade=UTI+A&especialidade=NEF&ordenar=tempo_desc
```

Valide que o link de exportação contém esses parâmetros. Use parse de HTML ou
asserts simples com URL encoded esperado. Evite acoplar o teste a classes CSS.

Rode os testes antes da implementação e registre a falha esperada no relatório.

---

## Diretrizes de implementação

- Preferência: criar link fora do `<form method="get">` para não confundir
  filtro e download.
- Use a rota nomeada do CES-S3 com `{% url %}`.
- Para preservar querystring, opção simples e aceitável:

```django
<a href="{% url 'services_portal:censo_export_xlsx' %}?{{ request.GET.urlencode }}">
  Exportar Excel
</a>
```

- Se `request` não estiver disponível no template, ajuste minimamente a view
  somente se estiver dentro do escopo acordado. Caso contrário, reporte
  bloqueio. Em Django, o context processor de request costuma estar disponível,
  mas confirme pelos testes.
- Não altere regras de filtro nem montagem do contexto.
- Não implemente melhorias cosméticas extensas.

---

## Critérios de aceitação

- Botão `Exportar Excel` aparece em `/censo/` para usuário autenticado.
- Link aponta para endpoint XLSX existente.
- Querystring atual é preservada no link.
- Nenhum comportamento backend de exportação foi refeito neste slice.
- Testes novos e existentes passam.

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

Crie `/tmp/sirhosp-slice-CES-S4-report.md` contendo:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- evidência RED e GREEN dos testes;
- trechos antes/depois por arquivo alterado;
- comandos executados e resultados;
- riscos, pendências e próximo passo sugerido.

Não inclua dados reais, credenciais ou conteúdo sensível no relatório.
