## Why

A página `/censo/` já permite busca e filtros úteis para operação diária, mas
exibe especialidades principalmente por códigos curtos, dificultando a leitura
por usuários não técnicos. Além disso, a equipe precisa exportar exatamente o
resultado filtrado atual para planilha Excel sem copiar manualmente dados da
tela.

## What Changes

- Exibir o nome completo da especialidade no dropdown de filtro da página
  `/censo/`, mantendo o valor técnico do filtro estável.
- Exibir o nome completo da especialidade na coluna `Especialidade` da tabela e
  nos cards mobile da página `/censo/`.
- Preservar fallback seguro para códigos sem cadastro correspondente em
  `Specialty`.
- Extrair a montagem do resultado filtrado do censo para helper reutilizável,
  evitando duplicação entre renderização HTML e exportação.
- Adicionar exportação XLSX autenticada do resultado atual da página `/censo/`,
  respeitando busca, filtros e ordenação ativos.

## Capabilities

### New Capabilities

- `censo-current-list-export`: contrato da listagem atual do censo hospitalar,
  incluindo exibição legível de especialidades e exportação XLSX do resultado
  filtrado.

### Modified Capabilities

- Nenhuma capability existente será modificada; não há spec atual dedicada à
  página `/censo/` em `openspec/specs/`.

## Impact

- Código afetado principalmente em `apps/services_portal/views.py`,
  `apps/services_portal/templates/services_portal/censo.html` e
  `tests/unit/test_services_portal_censo.py`.
- Pode adicionar uma rota dedicada de exportação em
  `apps/services_portal/urls.py`, caso a implementação escolha separar HTML e
  XLSX.
- Reutiliza `openpyxl`, dependência já presente no projeto; não introduz novas
  dependências.
- A exportação contém dados de pacientes sintéticos em testes e dados reais em
  produção, portanto deve continuar restrita a usuários autenticados e não deve
  registrar conteúdo clínico/pessoal em logs.
