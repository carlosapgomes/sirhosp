# Proposal

## Why

A equipe do hospital relatou dificuldade para reconhecer as categorias internas
de `/statistics/` como controles expansíveis; a mudança de cor no hover não
comunica a ação antes da interação. Tornar a ação e seu estado reconhecíveis nos
dois níveis facilita a consulta do relatório pela gestão, qualidade e demais
usuários autorizados, sem acrescentar ruído visual ou alterar dados clínicos.

## What Changes

- Exibir chevron antes do título de cada categoria interna, seguindo o padrão
  já usado no cabeçalho do setor.
- Fazer o chevron de setores e categorias apontar à direita quando fechado e
  para baixo quando aberto, retornando à direita ao recolher.
- Dar às categorias internas fundo neutro e borda discretos, visíveis sem
  hover, com pequena diferenciação neutra do estado aberto.
- Preservar linha inteira clicável, navegação por teclado e estado acessível,
  mantendo o contador à direita e a hierarquia entre setor e categorias.
- Acomodar títulos longos em telas estreitas sem sobrepor texto, ícone ou
  contador; manter foco visível e área confortável de interação.

### Non-goals

- Não mudar categorias, títulos, métricas, contagens, ordenação, links nominais
  ou mensagens de listas vazias.
- Não abrir categorias automaticamente, impor comportamento de accordion
  exclusivo nem adicionar ações de expandir/recolher tudo.
- Não adicionar cores semânticas por categoria, tooltips, instruções repetidas
  ou texto `Expandir/Recolher` em cada controle.
- Não modificar autorização, exportação, materialização, regras clínicas,
  persistência, scraping, jobs ou outras páginas.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `daily-statistics-reporting`: fortalecer o requisito existente de
  collapsibles acessíveis e badges com indicadores visuais de ação e estado
  nos cabeçalhos de setores e categorias internas.

## Impact

- Apresentação: `apps/statistics_reports/templates/statistics_reports/daily_report.html`
  e estilos delimitados à página em `static/css/sirhosp.css`.
- Regressão: ampliar os testes existentes em
  `tests/integration/test_daily_statistics_page.py`.
- Verification: cenário executável pequeno de browser com o template e os
  assets reais, usando exclusivamente projeção sintética em memória, sem
  acessar banco ou portal implantado.
- Sem novas dependências, endpoints, migrações ou mudança de compatibilidade;
  reutilizar Bootstrap 5.3.3, Bootstrap Icons e Playwright já presentes.

### Risks

- Estilos globais poderiam atingir outros collapsibles: delimitar seletores à
  superfície estatística e verificar o isolamento.
- Um ícone estático ou controlado separadamente pode divergir da abertura:
  derivar a orientação do estado acessível atualizado pelo Bootstrap.
- Títulos longos podem comprimir contadores em mobile: verificar quebra de
  texto e geometria em viewport estreito.
- Testes do HTML não demonstram rotação, foco ou layout: exigir evidência em
  browser, sem utilizar dados reais nem acionar a suíte do portal implantado.
