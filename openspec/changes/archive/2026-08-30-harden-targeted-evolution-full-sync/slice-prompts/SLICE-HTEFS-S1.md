# HTEFS-S1 — Ativação resiliente da ação Evolução

## Handoff para implementador LLM com contexto zero

Leia integralmente, nesta ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. este change: `proposal.md`, `design.md` (D2),
   `specs/persistent-session-ingestion-worker/spec.md` e `tasks.md`;
3. `apps/ingestion/extractors/legacy_navigation.py`: deadlines
   (`_deadline_s`, `_bound_ms`, `_timeout_kwargs`),
   `_raise_required_action_error`, seletores `SEL_DATE_START`/
   `SEL_DATE_END`, `click_evolucao` e `fill_evolution_dates`;
4. `tests/unit/test_legacy_navigation.py`, sobretudo fakes de locator,
   timeouts e testes de `click_evolucao`;
5. `automation/source_system/medical_evolution/path2.py` somente para comparar
   a ação conhecida; não o altere.

Estado comprovado: em produção, o botão estava visível, mas
`locator.click()` expirou no pipeline de actionability após cerca de 30 s. No
mesmo estado, `element.click()` controlado abriu o fluxo e a extração terminou.
O slice deve preservar o clique normal como primeira opção, limitar seu custo e
só considerar sucesso quando os dois inputs obrigatórios do modal estiverem
visíveis.

## Protocolo obrigatório para DeepSeek4-Flash

Se qualquer item abaixo não for comprovado, declare `Status: INCOMPLETE`, não
marque `tasks.md`, não faça commit/push e pare com evidência do bloqueio.

1. Antes de editar, execute `BASE_REF=$(git rev-parse HEAD)` e
   `git status --short`. Árvore suja inesperada é bloqueio.
2. Monte no relatório a matriz `requisito → arquivo → teste`.
3. Rode baseline oficial `./scripts/test-in-container.sh unit`; registre
   comando, exit code e resumo exato. Baseline falho é bloqueio.
4. Escreva testes primeiro. Rode o subconjunto alvo e prove pelo menos um RED
   por asserção de comportamento, nunca por import/sintaxe/fixture quebrada.
5. Faça GREEN mínimo. Depois REFACTOR somente local, aplicando clean code, DRY e
   YAGNI; não antecipe S2–S5.
6. Rode e interprete todas as inspeções obrigatórias.
7. Rode `check`, `unit`, `lint`, `typecheck`, `quality-gate` e markdown lint.
   Todo comando deve ter exit 0; unit final sem failures/errors e com
   `passed >= baseline`.
8. Produza relatório verificável com snippets antes/depois por arquivo,
   evidências RED/GREEN, gates e handoff de rerun para terceiro LLM.

## Objetivo end-to-end

Dado um detalhe de internação com botão `Evolução` visível, o helper tenta um
clique Playwright normal com orçamento curto. Se a actionability falhar e o
modal ainda não estiver aberto, usa clique DOM no mesmo elemento já validado.
As duas rotas convergem para uma única pós-condição: inputs inicial e final
visíveis dentro do deadline compartilhado. Sem pós-condição, propaga erro
tipado/sanitizado e nenhuma etapa posterior pode executar.

## Requisitos funcionais

- **R1 — Primário preservado e curto:** aguardar botão visível e tentar
  `locator.first.click()` primeiro. A tentativa de clique não pode consumir o
  `_DEFAULT_ACTION_TIMEOUT_MS` completo; use constante pequena e nomeada
  (máximo 5 s), sempre limitada pelo deadline recebido.
- **R2 — Fallback estrito:** somente após falha do clique normal e somente se a
  pós-condição ainda não estiver satisfeita, executar
  `locator.first.evaluate("(element) => element.click()")` ou forma
  semanticamente idêntica no mesmo locator. Não usar `force=True`, seletor
  global, `timeout=0`, nova page ou JavaScript que procure outro elemento.
- **R3 — Modal já aberto:** se o clique normal lança timeout mas ambos os inputs
  já estão visíveis, considerar a ação concluída e não clicar novamente.
- **R4 — Pós-condição única:** antes do retorno, ambos `SEL_DATE_START` e
  `SEL_DATE_END` devem estar visíveis. Uma função privada pequena pode
  centralizar a verificação. Um input só não basta.
- **R5 — Deadline e taxonomia:** todos os waits/clicks usam o mesmo deadline;
  nunca passar zero ao Playwright. Timeout final vira
  `NavigationTimeoutError`; não-timeout vira `NavigationError`, ambos com
  mensagem constante sem selector/URL/datas/identidade/raw exception.
- **R6 — Regressão:** iframe ausente e botão ausente continuam falhando; clique
  normal bem-sucedido não usa fallback.

## TDD obrigatório

### RED mínimo

Acrescente testes sintéticos que falhem antes do GREEN e provem:

1. clique normal abre modal: `click()` chamado uma vez, `evaluate()` zero, dois
   inputs verificados;
2. clique normal lança timeout de actionability: fallback DOM chamado uma vez,
   depois os dois inputs ficam visíveis e o helper retorna;
3. clique normal lança timeout, porém modal já está aberto: fallback zero;
4. fallback executa, mas um ou ambos inputs não aparecem: erro tipado, constante
   e sanitizado;
5. falha não-timeout do fallback/postcondition não vaza sentinelas semânticas
   colocadas no erro fake (registro, URL, cookie, selector);
6. nenhum timeout passado a fake Playwright é zero e o clique primário recebe
   no máximo 5000 ms quando há orçamento suficiente;
7. regressão de iframe/botão ausente.

Não simule acesso real e não use `sleep` real. Use clock/fakes determinísticos já
adotados na suíte.

### GREEN

Implementar somente R1–R6 em `click_evolucao` e helpers privados estritamente
necessários.

### REFACTOR

- uma pós-condição, sem duplicar dois waits em branches;
- constantes nomeadas para orçamento/mensagem;
- catches estreitos e reuso dos helpers de deadline/taxonomia;
- nenhuma mudança em `fill_evolution_dates`, bridge, adapter ou worker.

## Arquivos permitidos

Limite de **2 arquivos de implementação/teste**, além de `tasks.md`:

1. `apps/ingestion/extractors/legacy_navigation.py`;
2. `tests/unit/test_legacy_navigation.py`.

Proibido: models, migrations, bridge, adapter, workers, specs/design, scripts de
automação, dependências. Arquivo extra exige parar e reportar bloqueio; não
exceda o limite por conveniência.

## Inspeções obrigatórias

```bash
rg -n "def click_evolucao|SEL_DATE_START|SEL_DATE_END|evaluate|force=True" \
  apps/ingestion/extractors/legacy_navigation.py
rg -n "timeout=0|_DEFAULT_ACTION_TIMEOUT_MS" \
  apps/ingestion/extractors/legacy_navigation.py
rg -n "click_evolucao" tests/unit/test_legacy_navigation.py
git diff --check
git diff -- apps/ingestion/extractors/legacy_navigation.py \
  tests/unit/test_legacy_navigation.py
```

Interprete no relatório: primário antes do fallback; ausência de `force=True` e
`timeout=0` no fluxo; pós-condição exige os dois inputs; nenhum arquivo fora do
escopo.

## Critérios binários de aceite

- [ ] R1–R6 têm teste RED e passam no GREEN.
- [ ] Clique normal continua primeira estratégia e custa no máximo 5 s.
- [ ] Fallback DOM só ocorre quando necessário e usa o mesmo botão.
- [ ] Modal já aberto impede clique duplo.
- [ ] Dois inputs visíveis são condição obrigatória de retorno.
- [ ] Erros mantêm tipo e mensagem sanitizados; sentinelas ausentes.
- [ ] Nenhum wait/click recebe timeout zero.
- [ ] Exatamente os 2 arquivos permitidos, além de `tasks.md`.
- [ ] Todos os gates têm exit 0 e unit final não regride.

### Condições automáticas de INCOMPLETO

Baseline/RED ausente; RED por import; fallback executado antes do normal; uso de
`force=True`; retorno sem os dois inputs; timeout desabilitado; erro bruto ou
sentinela exposta; teste real do legado; arquivo extra; mudança de contrato de
outro helper; gate falho; relatório ausente/incompleto; task marcada sem toda a
evidência.

## Gates de autoavaliação

Responda no relatório:

1. Qual teste prova a ordem normal → DOM?
2. Qual teste prova que modal já aberto evita clique duplo?
3. Onde o orçamento curto é limitado pelo deadline global?
4. Qual teste distingue timeout de falha não-timeout e prova sanitização?
5. Por que cada linha de produção alterada pertence somente a S1?

## Comandos mínimos de validação

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
```

Registre também o comando exato do subconjunto RED/GREEN conforme a suíte
existente.

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-HTEFS-S1-report.md` com:

- `Status`, `BASE_REF` e estado inicial/final do git;
- matriz requisito→arquivo→teste;
- baseline e final (comandos, exit codes, passed/failed/errors);
- RED e GREEN com saída/falha esperada;
- snippets **antes/depois de cada arquivo alterado** (`tasks.md` incluído; para
  arquivo novo, antes = ausente);
- inspeções interpretadas; critérios e gates respondidos;
- riscos/pendências;
- `Handoff para verificador` com arquivos, comandos exatos de rerun e checklist
  R1–R6.

Se completo, marque somente 1.x em `tasks.md`, rode markdown lint novamente,
faça commit claro, push e pare. Não inicie S2.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md and the entire harden-targeted-evolution-full-sync change, especially design D2 and slice-prompts/SLICE-HTEFS-S1.md. Implement ONLY HTEFS-S1 with the exact DeepSeek4-Flash protocol. Start from clean BASE_REF and official unit baseline; produce real RED tests in test_legacy_navigation for normal click, short actionability timeout followed by same-element DOM click, already-open modal without double click, mandatory two-input postcondition, bounded nonzero deadlines and sanitized typed failures. Then minimal GREEN and local DRY/YAGNI refactor only in legacy_navigation.py. Touch only the 2 allowed files plus tasks.md. Run mandatory rg inspections and all official gates including quality-gate and markdown lint. Create /tmp/sirhosp-slice-HTEFS-S1-report.md with baseline/RED/GREEN, before/after snippets for every changed file, exit codes and verifier rerun handoff. Any missing evidence or failure means INCOMPLETE with no task mark/commit. If complete mark only tasks 1.x, commit, push and STOP; do not start S2.
```
