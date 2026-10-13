# SCAF-S1 — Collapsibles estatísticos reconhecíveis e coerentes

## Identity

- Change: `improve-statistics-collapse-affordance`.
- Slice: `SCAF-S1`.
- Tasks: [tasks.md, seção 1](../tasks.md#1-scaf-s1--affordance-e-estado-dos-collapsibles).
- Estado: contrato proposto para revisão; esta criação não inicia execução.

## Objective

Tornar setores e categorias de `/statistics/` reconhecíveis como expansíveis,
com chevrons coerentes com o estado e categorias visualmente delimitadas sem
poluição visual.

## Read first

Referências a partir da raiz do repositório:

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/config.yaml`.
- `openspec/changes/improve-statistics-collapse-affordance/proposal.md`.
- `openspec/changes/improve-statistics-collapse-affordance/design.md`, D1–D4.
- `openspec/changes/improve-statistics-collapse-affordance/specs/daily-statistics-reporting/spec.md`.
- `openspec/changes/improve-statistics-collapse-affordance/tasks.md`.
- `openspec/specs/daily-statistics-reporting/spec.md`, contratos de collapsibles,
  autorização e navegação nominal que devem permanecer.
- `apps/statistics_reports/templates/statistics_reports/daily_report.html`.
- `static/css/sirhosp.css` e `templates/base.html`.
- `templates/base_sidebar.html`, `templates/includes/sidebar.html` e
  `templates/includes/topbar_sync.html`, somente para preservar a superfície
  externa e delimitar os requests da verification.
- `apps/statistics_reports/presentation.py`, formato da projeção, títulos e
  listas da seção condicional sem setor identificado.
- `tests/integration/test_daily_statistics_page.py`, fixtures e
  `TestCollapseAccessibility`; seus imports apontam para fixtures de
  `tests/integration/test_daily_statistics_materialization.py`.
- `scripts/test-in-container.sh`, comandos realmente suportados.
- `docs/dev-verification.md`, somente se considerar verification implantada,
  que não está autorizada por este contrato.

## Requirements -> Planned evidence

| ID | Requisito observável | Evidência planejada |
| --- | --- | --- |
| R1 | Todos os controles estatísticos, inclusive os da seção sem setor identificado, mostram chevron decorativo antes do título, à direita quando fechados e para baixo quando abertos; o ícone acompanha o próprio estado acessível e volta ao recolher. | RED/GREEN de renderização e browser com ciclos completos de setor e categoria; abrir pai com filho fechado não pode girar ícone do filho. |
| R2 | Categorias têm fundo/borda neutros sem hover, diferenciação neutra aberta, contador à direita e menor destaque que o setor; não acrescentam cores por natureza ou rótulos repetidos. | Estilos computados sem hover/foco, screenshots desktop/mobile e inspeção do diff. |
| R3 | Botões conservam nome e estado acessíveis, foco visível, Enter/Espaço, linha inteira interativa e altura mínima de 44 pixels CSS. | Testes do markup e browser por teclado e clique na área livre dos controles dos dois níveis. |
| R4 | Título longo quebra alinhado após o ícone a 375 pixels sem sobrepor ou comprimir ícone/badge nem introduzir overflow horizontal nos cabeçalhos. | Geometria computada e screenshot do viewport mobile. |
| R5 | Permanecem títulos, métricas, badges zero/não zero, mensagens vazias, links, ordenação, permissões e expansão independente; controles fora da página não mudam. | Suíte existente da página, integração oficial, ciclos independentes no browser e inspeção de seletores/diff. |

Esses requisitos detalham o bloco modificado de collapsibles no delta; não
alteram os demais contratos de `daily-statistics-reporting`.

## Expected blast radius

- `apps/statistics_reports/templates/statistics_reports/daily_report.html`:
  indicadores, classes locais e layout dos controles.
- `static/css/sirhosp.css`: estilos delimitados à página estatística.
- `tests/integration/test_daily_statistics_page.py`: regressão usando as
  fixtures existentes.
- Novo `scripts/verify_statistics_collapses.py`: cenário específico descrito
  em D4, com dados em memória e assets reais.

Superfícies sensíveis fora de escopo: projeção de produção, views, models,
materialização, exportação, permissões, seletores de data, jobs, templates de
outras páginas, tema global, gates globais e suíte do portal implantado.
Arquivos adicionais só quando necessários, com justificativa no relatório;
expansão material exige bloqueio, conforme `AGENTS.md`.

## Failing-before plan

Antes de modificar template/CSS:

1. Acrescentar testes de regressão em `TestCollapseAccessibility` que examinem
   cada botão estatístico renderizado, inclusive categorias vazias e seção
   sem agrupamento, preservando seus nomes e alvos.
2. Registrar RED: o código atual não renderiza indicador decorativo nas
   categorias internas. Não exigir nomes exatos de novas classes como
   substituto desse comportamento.
3. Construir o cenário de D4 e executá-lo sobre o template/CSS ainda atuais.
   Registrar os checks que falham: categorias sem chevron e chevron setorial
   que não muda de orientação após abrir. Falta de browser/assets é bloqueio
   de infraestrutura, não evidência de RED do produto.

Os testes determinísticos usam TDD. Rotação, foco e geometria exigem browser;
esta reprodução executável é a failing-before evidence apropriada, sem
simular CSS por assertions de strings.

## Implementation constraints

Seguir `AGENTS.md`, preservar convenções e implementar a menor mudança correta;
não criar abstração especulativa nem refactoring adjacente.

- Implementar D1–D3 usando o estado do próprio botão atualizado pelo Bootstrap,
  sem segundo controlador JavaScript.
- Não adicionar `data-bs-parent`, reset de filhos ou autoexpansão.
- Aplicar o padrão às listas realmente fornecidas pela projeção, não assumir
  quatro listas na seção condicional sem setor identificado.
- Não renomear o título longo nem alterar badges/sinalização de qualidade.
- O cenário D4 renderiza o template real; não consulta banco, acessa sistemas
  clínicos ou utiliza PHI/PII real. Screenshots e resultados ficam fora do Git.
- Não instalar novas dependências nem acionar verification implantada.

## Validation

### Focused validation

A fronteira afetada exige integração oficial:

```bash
./scripts/test-in-container.sh integration
```

Conferir RED/GREEN dos novos testes da página e preservar os já existentes,
inclusive orçamento de queries e links. O wrapper não recebe argumentos
extras de pytest; não inventar comandos focados que ele não suporta.

Comandos auxiliares do cenário, que não substituem os gates oficiais:

```bash
uv run python scripts/verify_statistics_collapses.py --help
uv run ruff check scripts/verify_statistics_collapses.py
```

### Project-required gates

Seguir `AGENTS.md`, seções 4, 8, 11 e 12. O gate final completo pertence ao
controller, com integração separada obrigatória para esta change. Markdown
alterado deve passar pelo lint oficial. Não executar o workflow de apply
como segundo controller.

### Runtime / verification evidence

Instalação do browser já previsto no projeto, somente se necessária:

```bash
uv run playwright install chromium
```

Antes e depois das alterações de produção, sem reutilizar diretório de saída:

```bash
uv run python scripts/verify_statistics_collapses.py \
  --output-dir /tmp/sirhosp-statistics-collapse-before
uv run python scripts/verify_statistics_collapses.py \
  --output-dir /tmp/sirhosp-statistics-collapse-after
```

Executar o contrato de D4 nos dois viewports. Registrar resultados estruturados,
assets carregados, matriz de checks e screenshots sintéticas. Aferir estados
após terminar a abertura/recolhimento, movendo o ponteiro e retirando o foco
para comparar fundos em estado neutro. Se houver transição, conferir também
`prefers-reduced-motion`.

Registrar a limitação: este cenário prova apresentação e interação do template
real, não o portal implantado; integração prova a fronteira Django.

## Acceptance criteria

- [ ] R1: todos os controles dos dois níveis, inclusive seção sem setor,
  passaram pelo ciclo direita → baixo → direita, com ARIA/conteúdo coerentes
  e ícone decorativo; expandir o pai não gira ícones de filhos fechados.
- [ ] R2: screenshots e checks sem hover/foco demonstram fundo/borda neutros,
  fundo aberto distinto e hierarquia; contadores permanecem à direita, sem
  nova paleta por categoria ou textos repetidos.
- [ ] R3: foco é visível, Enter/Espaço e clique fora do texto funcionam nos
  dois níveis; todos os controles verificados têm altura mínima de 44 pixels.
- [ ] R4: a categoria longa quebra corretamente em mobile; ícone e badge
  permanecem íntegros, sem sobreposição nem overflow dos cabeçalhos.
- [ ] R5: regressões da página e integração oficial passam; setores/categorias
  não fecham irmãos, pai recolhido/reaberto preserva filho aberto e estado
  inicial é recolhido; seletores não atingem controles externos.
- [ ] RED e failing-before em browser foram registrados antes do ajuste de
  produção; os mesmos contratos passam após a implementação.
- [ ] Verification retornou 0 com browser/assets reais e todos os checks;
  relatório inclui resultados e screenshots, não um sucesso por skip.

Aceite pelo controller também depende dos critérios globais em `AGENTS.md`,
inclusive revisão independente sem P0/P1 e relatório obrigatório.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` com evidência se houver contradição entre
spec/design/código, nova decisão de produto/arquitetura, expansão material,
compatibilidade ou persistência não previstas, novo risco clínico ou de
segurança/privacidade/integridade, ou impossibilidade de cumprir o contrato.
Isso inclui infraestrutura que impeça verification confiável; não trocar
browser/assets por mocks nem declarar o slice pronto com runtime omitido.

## Evidence report

Produzir `/tmp/sirhosp-slice-SCAF-S1-report.md`, no formato de `AGENTS.md`,
seção 13, com `READY_FOR_REVIEW` ou `BLOCKED_NEEDS_DECISION`, R1–R5 → evidências,
arquivos alterados, RED/GREEN, comandos e exit status, verification e seus
limites, scope deviations, levers, riscos e decisões pendentes. Referenciar
artefatos before/after sem copiar o Git diff ou incluir dados sensíveis.

## Worker handoff

```text
Implement only this slice after implementation is explicitly authorized.
Treat the slice and referenced OpenSpec artifacts as the implementation contract.
Reconstruct fresh context from the listed files and follow AGENTS.md.
Produce failing-before evidence, implement the smallest correct change, run
focused validation and synthetic browser verification, and write the report.
Do not update tasks.md, commit, push, merge, archive, or start another slice.
If a new decision is required, return BLOCKED_NEEDS_DECISION with evidence.
Otherwise finish with READY_FOR_REVIEW and
REPORT_PATH=/tmp/sirhosp-slice-SCAF-S1-report.md.
```
