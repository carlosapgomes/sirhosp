# Spec delta: daily-statistics-reporting (statistics-export-zip-per-sector)

## MODIFIED Requirements

### Requirement: Exportação XLSX reproduz a revisão selecionada

> **MODIFICADO por esta change (BREAKING):** o formato deixa de ser um
> workbook único com uma aba por setor e passa a ser um ZIP com um XLSX por
> setor, com filenames com data. Abaixo, os cenários originais seguem com a
> semântica atualizada para o ZIP.

O sistema SHALL exportar a revisão corrente da data selecionada como um ZIP
com um XLSX por agrupamento oficial e MUST preservar em cada arquivo as
mesmas categorias e ordenação apresentadas na página. O caminho de workbook
único é removido.

#### Scenario: Workbook possui folha por setor

- **WHEN** um usuário autorizado exporta um relatório
- **THEN** o ZIP contém um XLSX por agrupamento oficial exibido, na ordem
  da página
- **AND** cada XLSX identifica o nome completo do setor dentro do arquivo

#### Scenario: Workbook possui linhas sem setor atribuível

- **WHEN** a revisão selecionada contém evento sem origem nem destino setorial
  ou paciente do fechamento sem setor atribuível
- **THEN** o ZIP contém também o arquivo condicional do setor não
  identificado
- **AND** esse arquivo preserva essas linhas sem representá-las como
  agrupamento oficial

#### Scenario: Folha contém todas as tabelas

- **WHEN** um XLSX do ZIP é gerado
- **THEN** ele contém, nesta ordem, internações, admissões por transferência,
  óbitos, saídas por transferência, altas hospitalares, eventos com origem ou
  destino não identificado e pacientes do fechamento
- **AND** cada seção mostra sua quantidade
- **AND** seções vazias permanecem presentes

#### Scenario: Campos nominais e temporais são exportados

- **WHEN** uma linha de evento é exportada
- **THEN** ela inclui leito, nome, prontuário, especialidade, data/hora
  clínica, origem ou destino, tipo e detecção conforme disponíveis

#### Scenario: Nome de folha é incompatível com Excel

- **WHEN** nomes de setores excedem limites, contêm caracteres inválidos ou
  colidem depois da normalização
- **THEN** a única folha de cada XLSX usa nome válido
- **AND** o nome completo do setor permanece dentro do arquivo
- **AND** o nome do arquivo usa slug `snake_case` ASCII único (ver cenário
  de nome de arquivo)

#### Scenario: Nome de arquivo é normalizado com data

- **WHEN** títulos de setores contêm acentos, espaços, caracteres inválidos
  de arquivo ou colidem depois da normalização
- **THEN** o ZIP chama-se `estatisticas-diarias-{YYYY-MM-DD}-r{N}.zip`
- **AND** cada XLSX chama-se
  `estatisticas-diarias-{YYYY-MM-DD}-r{N}-{slug}.xlsx`
- **AND** `slug` é `snake_case` ASCII minúsculo determinístico, único com
  sufixo `_2`, `_3` e fallback `setor`

#### Scenario: Valor nominal parece fórmula

- **WHEN** um valor textual começa por um caractere interpretável como fórmula
- **THEN** cada XLSX o grava como texto seguro

### Requirement: Toda exportação servida produz auditoria

> **MODIFICADO por esta change:** o registro passa a incluir `file_count`
> (novo campo) mais o total de linhas, sem payload nominal e sem persistir
> arquivos.

O sistema MUST registrar cada ZIP gerado e servido, sem registrar dados
nominais no log e sem persistir os arquivos exportados.

#### Scenario: Exportação é servida com sucesso

- **WHEN** o sistema gera e serve o ZIP ao usuário
- **THEN** registra usuário, data/hora, data selecionada, revisão,
  `file_count` e `row_count` total da exportação
- **AND** os arquivos não são persistidos no servidor

#### Scenario: Geração falha antes da resposta

- **WHEN** a geração do ZIP falha antes de ele ser servido
- **THEN** o sistema não registra sucesso de download
- **AND** pode registrar falha operacional sem identidade clínica
