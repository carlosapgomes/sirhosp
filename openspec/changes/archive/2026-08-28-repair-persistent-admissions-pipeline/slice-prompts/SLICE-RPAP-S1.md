# RPAP-S1 — Preservar o snapshot real do iframe

## Handoff com contexto zero

Você está no repositório SIRHOSP. Leia integralmente antes de editar:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. `openspec/changes/repair-persistent-admissions-pipeline/{proposal.md,design.md,tasks.md}`;
3. `specs/persistent-session-ingestion-worker/spec.md` deste change;
4. este arquivo;
5. `apps/ingestion/extractors/real_handle_bridge.py`;
6. `apps/ingestion/extractors/playwright_session_handle.py`;
7. `apps/ingestion/extractors/persistent_extraction_adapter.py`;
8. `tests/unit/test_real_handle_bridge.py`.

Estado esperado: `navigate_to_admissions()` já lê a tabela em `frame_pol` com
`_read_and_build_snapshot(page)`, mas só entrega o payload se o wrapped handle
possuir o método fake-only `set_html()`. O handle real não possui. O fallback
marca `_last_url`; `get_page_html()` relê o HTML superior e gera `[]` porque o
iframe não integra `page.content()`.

Este slice corrige somente o transporte e ciclo de vida do snapshot. A regra de
falha para batch vazio pertence a S2.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Este slice será implementado por modelo rápido com tendência a concluir cedo.
Siga literalmente. Se qualquer item falhar, responda `INCOMPLETE`, não marque
`tasks.md`, não faça commit/push e pare com evidência.

1. Registre `BASE_REF=$(git rev-parse HEAD)`, `git status --short` e uma matriz
   `Requisito → arquivo(s) → teste(s)` no relatório antes de editar. Árvore suja
   ou alteração alheia bloqueia; não descarte trabalho de terceiros.
2. Rode baseline oficial `./scripts/test-in-container.sh unit`. Registre exit
   code e resumo com `passed`, `failed` e `errors`. Qualquer falha/error bloqueia.
3. Escreva testes primeiro e rode novamente a suíte unitária. Pelo menos um
   teste novo deve falhar por o snapshot lido do iframe ser perdido sem
   `set_html()`, nunca por import, sintaxe ou fixture quebrada.
4. Implemente GREEN mínimo somente nos arquivos permitidos. Não antecipe S2,
   recovery, health check ou demografia.
5. Refatore apenas o trecho tocado com clean code, nomes explícitos, função
   coesa, DRY e YAGNI. Não crie abstração genérica ou estado persistente.
6. Rode as inspeções obrigatórias e todos os gates oficiais.
7. O unit final deve ter exit 0, zero failures/errors e
   `passed_final >= passed_baseline`.
8. Gere relatório verificável. Só então marque 1.1–1.6, commit, push e pare.

## Objetivo vertical

Provar end-to-end, com um handle realista sem `set_html()`, que a lista
normalizada lida do iframe chega ao container consumido pelo adapter e que
nenhum job posterior pode receber o snapshot anterior.

## Requisitos funcionais

### R1 — Handoff exato do snapshot

Após `_read_and_build_snapshot(page)`, o bridge deve guardar o payload sintético
ou dados equivalentes em memória própria. `get_page_html()` deve devolver o
snapshot exato, inclusive caracteres Unicode, sem reler a tabela pelo HTML
superior.

### R2 — Estado estritamente por job

Limpar o snapshot antes de nova navegação e após cleanup, restart, bootstrap,
shutdown ou falha de navegação. A limpeza deve ocorrer mesmo quando a operação
delegada falha, quando aplicável, sem mascarar erro tipado existente.

### R3 — Não alterar o browser real

Não adicionar `set_html()` ao `PlaywrightSessionHandle`, não chamar
`page.set_content()`, não injetar DOM, não abrir browser/contexto, não executar
subprocesso e não gravar arquivo clínico.

### R4 — Preservar contratos existentes

Manter contador/popup necessários ao controller, timeout tipado, navegação
`frame_pol`, cleanup, restart/rebootstrap, evolução action-first e saídas
sanitizadas. Não mudar empty semantics neste slice.

## Arquivos esperados e limite

Máximo de **2 arquivos de código/teste rastreados**:

1. `apps/ingestion/extractors/real_handle_bridge.py`;
2. `tests/unit/test_real_handle_bridge.py`.

`tasks.md` não conta no limite. Não editar adapter, handle concreto, errors,
workers, models, migrations, Compose ou docs. Se precisar de terceiro arquivo,
pare como `INCOMPLETE/BLOCKED` antes de editar.

## TDD obrigatório

### RED

Adicionar testes sintéticos que provem, no mínimo:

1. wrapped handle sem atributo `set_html`;
2. `_read_and_build_snapshot` retorna uma internação sintética;
3. wrapped `get_page_html()` retorna apenas HTML superior sem tabela;
4. `bridge.get_page_html()` contém exatamente o payload capturado, não `[]`;
5. cleanup seguido de `get_page_html()` não devolve snapshot antigo;
6. falha/nova navegação e restart não reutilizam payload anterior;
7. timeout tipado continua propagando.

Rode `./scripts/test-in-container.sh unit` e registre o failure assertivo antes
da implementação.

### GREEN

Adicionar o menor estado transitório privado e centralizar sua limpeza. Remover
a dependência de `hasattr(..., "set_html")` no caminho real. Reusar o formato de
container existente; não redesenhar o adapter.

### REFACTOR

Evitar dois construtores divergentes do mesmo container, nomes vagos como
`data/cache`, limpeza espalhada sem helper ou comentários históricos extensos.
Não generalizar cache para demografia/evolução sem necessidade comprovada.

## Checks de inspeção obrigatórios

Execute e interprete no relatório:

```bash
rg -n "set_html|set_content|_admission.*snapshot|admission-snapshot-data" \
  apps/ingestion/extractors/real_handle_bridge.py
rg -n "def get_page_html|def navigate_to_admissions|def open_tab|def restart_browser|def bootstrap|def shutdown|def close_last_non_root_tab" \
  apps/ingestion/extractors/real_handle_bridge.py
rg -n "subprocess|sync_playwright|new_page|browser\.launch" \
  apps/ingestion/extractors/real_handle_bridge.py
rg -n "without.*set_html|stale|restart|cleanup|top.level|iframe" \
  tests/unit/test_real_handle_bridge.py
```

Esperado: caminho corrigido não depende de `set_html`/`set_content`; todas as
fronteiras limpam estado; ocorrências legadas de subprocess/browser em outras
funções, se existirem, são apenas inspecionadas e não ampliadas; testes provam o
handle sem método fake-only.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate repair-persistent-admissions-pipeline --strict
./scripts/markdown-lint.sh
```

## Critérios binários de sucesso

- [ ] R1–R4 têm testes RED/GREEN.
- [ ] Handle sem `set_html()` recebe snapshot não vazio correto.
- [ ] HTML superior sem iframe não é usado para reconstruir admissões.
- [ ] Cleanup, falha, nova navegação, restart, bootstrap e shutdown limpam estado.
- [ ] Nenhum DOM real, subprocesso, browser ou arquivo novo é criado.
- [ ] Timeout e contratos de sessão permanecem.
- [ ] Apenas dois arquivos esperados foram alterados, além de `tasks.md`.
- [ ] Todos os gates têm exit 0 e unit final não regrediu.

### Condições automáticas de INCOMPLETO

- baseline ausente, falho ou sem resumo/exit code;
- RED ausente, passa antes do código ou falha por erro acidental;
- implementação adiciona `set_html()` ao handle ou `set_content()`;
- payload é reconstruído de `page.content()` superior;
- estado sobrevive a qualquer fronteira obrigatória;
- teste usa portal real, dados reais, `.env`, HTML/PDF/screenshot real;
- contrato de timeout/cleanup/restart é removido;
- arquivo extra é tocado sem parar previamente;
- qualquer gate falha ou final passed fica abaixo do baseline;
- relatório não existe no caminho exigido;
- task é marcada ou commit/push ocorre com pendência.

## Gates de autoavaliação

Responder com evidência no relatório:

1. Qual teste prova ausência de `set_html()` no handle?
2. Qual assert prova que `[]` não veio do HTML superior?
3. Em quais fronteiras o estado transitório é limpo?
4. Qual teste prova que o segundo paciente não recebe o primeiro snapshot?
5. Como timeout e cleanup antigos foram preservados?
6. Por que cada arquivo alterado é indispensável?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-RPAP-S1-report.md` contendo:

- `Status: COMPLETE|INCOMPLETE`;
- BASE_REF, árvore inicial e matriz requisito→arquivo→teste;
- RED: comando, exit code, teste, assertion e motivo esperado;
- GREEN/REFACTOR: comandos e resultados;
- snippets antes/depois por arquivo alterado;
- inspeções `rg` com interpretação;
- baseline versus final (`passed`, `failed`, `errors`, exit code);
- todos os gates e comandos exatos para rerun;
- arquivos alterados, justificativa, riscos e limitações;
- respostas aos gates de autoavaliação;
- `Handoff para verificador` com checklist R1–R4 e pontos de diff a revisar.

Não incluir identificadores clínicos, `.env`, URLs, cookies, HTML/PDF real ou
credenciais.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the complete OpenSpec change
repair-persistent-admissions-pipeline, and SLICE-RPAP-S1.md. Assume zero prior
context. Implement ONLY RPAP-S1. Follow the DeepSeek4-Flash protocol literally:
record a clean BASE_REF and official container unit baseline, write a real RED
for a wrapped handle without set_html and top-level HTML without iframe data,
implement minimal GREEN, refactor only touched code with clean code/DRY/YAGNI,
run required rg inspections and every official gate, and compare baseline vs
final with exit 0, zero failures/errors and final passed >= baseline. Touch only
real_handle_bridge.py and test_real_handle_bridge.py; do not implement empty
fail-closed, demographics, recovery, health, models or migrations. Never access
or emit real patient data, .env, credentials, HTML/PDF or screenshots. Create
/tmp/sirhosp-slice-RPAP-S1-report.md with RED/GREEN evidence, before/after
snippets, gates, rerun commands, self-evaluation and Handoff para verificador.
If any item fails, report INCOMPLETE and do not update tasks or commit. If all
pass, mark only S1 tasks, commit, push, reply REPORT_PATH=..., then STOP.
```
