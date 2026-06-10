## Context

A view `censo` em `apps/services_portal/views.py` monta a página `/censo/` a
partir do `CensusSnapshot` mais recente, filtrando apenas leitos ocupados. A
página já suporta busca por nome/prontuário, filtro por setor, filtro por
especialidade e ordenação.

O modelo `Specialty` já existe em `apps/census/models.py` com `code` e `name`.
A view atual já resolve código e nome completo para cada paciente, mas o
template ainda renderiza o código como texto principal e usa o nome completo
apenas como tooltip. O dropdown de especialidade também é populado diretamente
com valores distintos de `CensusSnapshot.especialidade`, por isso mostra apenas
códigos quando o snapshot armazena códigos.

A exportação Excel deve refletir o mesmo resultado visto na tela. Para preservar
DRY e reduzir risco de divergência, a implementação deve compartilhar a mesma
montagem de queryset, filtros, enriquecimento e ordenação entre HTML e XLSX.

## Goals / Non-Goals

**Goals:**

- Mostrar nomes completos de especialidades no filtro e na listagem de `/censo/`.
- Manter filtros existentes compatíveis com os valores gravados em
  `CensusSnapshot.especialidade`.
- Exportar para XLSX o resultado atual da página, respeitando busca, filtros e
  ordenação.
- Reutilizar a dependência `openpyxl`, já presente no projeto.
- Manter a mudança pequena, server-side e compatível com a simplicidade
  operacional da fase 1.

**Non-Goals:**

- Alterar scraping, parser ou persistência do censo.
- Criar nova tabela, migration ou modelo de dados.
- Introduzir Celery, Redis, filas ou processamento assíncrono para exportação.
- Implementar auditoria de download neste change.
- Modificar a página `/censo-oficial/`, exceto se um slice futuro decidir
  explicitamente padronizar comportamento.
- Criar exportação PDF, CSV ou API REST.

## Decisions

### 1. Usar `Specialty` como catálogo de exibição

A página deve continuar filtrando pelo valor armazenado no snapshot, mas deve
exibir o nome completo quando houver correspondência em `Specialty`.

Alternativas consideradas:

- **Gravar o nome completo em `CensusSnapshot`**: rejeitado porque mudaria o
  contrato de ingestão e exigiria migração ou reprocessamento sem necessidade.
- **Mostrar código e nome em todos os lugares**: possível, mas pior para a
  leitura rápida. O código pode permanecer em `title` ou texto secundário se o
  executor julgar útil.

### 2. Representar opções de especialidade como objetos de contexto

Em vez de `especialidade_options` ser uma lista de strings, ela deve passar a
ser uma lista de dicionários simples:

```python
{
    "value": "NEF",
    "label": "NEFROLOGIA",
    "code": "NEF",
}
```

O `value` mantém a compatibilidade com o filtro; o `label` melhora a UX. Para
valores sem cadastro, `label` deve ser igual ao valor original.

### 3. Extrair helper comum para resultado do censo

A implementação deve evitar duplicar a lógica de filtros entre a view HTML e a
exportação. O helper recomendado é privado ao módulo, por exemplo:

```python
_build_censo_context(request: HttpRequest) -> dict[str, Any]
```

Ele deve encapsular:

- snapshot mais recente;
- query base de leitos ocupados;
- aplicação dos filtros `q`, `unidade`, `especialidade`;
- resolução de paciente/admissão;
- resolução de especialidade;
- ordenação;
- opções de dropdown;
- contagem e timestamp.

O nome exato pode variar, desde que o código permaneça coeso, testável e sem
duplicação relevante.

### 4. Preferir rota dedicada para exportação XLSX

A exportação deve ser uma view autenticada separada, como
`censo_export_xlsx`, com rota dedicada, por exemplo:

```text
/censo/exportar/
```

A rota recebe os mesmos query parameters da página HTML. Isso mantém a view
HTML simples e deixa o comportamento de download explícito.

Alternativa aceitável se o executor justificar no relatório: usar
`/censo/?export=xlsx`. Se essa alternativa for escolhida, a implementação ainda
deve compartilhar a lógica de resultado e cobrir o comportamento em testes.

### 5. Gerar XLSX em memória com `openpyxl`

A exportação deve gerar workbook em memória usando `BytesIO`, sem escrever
arquivos temporários em disco. Colunas mínimas:

- Registro;
- Nome;
- Setor / Unidade;
- Leito;
- Especialidade;
- Data Internação;
- Tempo Internação;
- Capturado em.

O arquivo deve retornar content type de XLSX e `Content-Disposition` com nome
estável contendo data/hora do snapshot quando disponível.

## Risks / Trade-offs

- **Valor de `CensusSnapshot.especialidade` pode ser código ou nome completo**
  → manter helper de resolução bidirecional código ↔ nome, preservando fallback.
- **Exportação pode divergir da tela** → extrair helper comum antes do XLSX.
- **Planilha contém dados pessoais de pacientes** → manter `login_required`, não
  logar conteúdo exportado e usar apenas dados sintéticos nos testes.
- **Arquivo grande em memória** → volume esperado do censo é baixo; geração
  síncrona em memória é adequada para a fase 1.
- **Mudança no formato de `especialidade_options` quebra template** → realizar
  em slice próprio com testes de regressão para dropdown e filtro.
