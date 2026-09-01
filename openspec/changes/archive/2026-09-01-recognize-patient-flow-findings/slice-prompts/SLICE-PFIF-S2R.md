# PFIF-S2R — Correção da navegação clássica

## Handoff para implementador LLM com contexto zero

Leia integralmente, nesta ordem, antes de editar:

1. `AGENTS.md`, `PROJECT_CONTEXT.md` e todo o change
   `openspec/changes/recognize-patient-flow-findings/`;
2. a nota de governança no topo de `SLICE-PFIF-S2.md`, `tasks.md` e as decisões
   D2, D4 e D8 de `design.md`;
3. `/tmp/sirhosp-slice-PFIF-S1-report.md`, o commit S1 `9ce082b` e o fluxo
   correto `click_atendimentos → wait_for_encounters_table →
   read_encounter_dates` em `legacy_navigation.py`/`real_handle_bridge.py`;
4. `/tmp/sirhosp-slice-PFIF-S2-report.md` somente como evidência histórica
   reprovada, o commit defeituoso `829afd5` e a avaliação independente descrita
   neste prompt;
5. `_capture_encounter_sidecar`, `wait_encounters_table`,
   `read_encounter_dates` e o early return admissions-only em
   `automation/source_system/medical_evolution/path2.py`;
6. `_process_admissions_only`, `_capture_admissions` e
   `_run_encounter_fallback` no worker clássico;
7. `tests/unit/test_current_vs_persistent_encounter_parity.py`, identificando os
   testes que mockam `read_encounter_dates` e o extractor inteiro;
8. `apps/ingestion/extractors/playwright_extractor.py` somente para confirmar que
   subprocess único, cache e sidecar já estão corretos e não devem ser editados.

### Defeito confirmado

No commit `829afd5`, `_capture_encounter_sidecar()` chama
`read_encounter_dates(page)` enquanto `frame_pol` ainda mostra `Internações`.
Não há `get_by_text("Atendimentos", exact=True)`, espera visível ou clique. Em
produção, a espera pela tabela errada pode consumir 60 segundos e terminar como
erro de captura; o fallback recente nunca é alcançado.

Além disso, `_process_admissions_only()` passa
`include_encounter_sidecar=True` antes de verificar `run.batch_id`. Assim, um
standalone vazio também tenta consultar Atendimentos, contrariando o contrato de
preservação do caminho histórico.

Os testes não detectaram isso porque o teste de path2 mockou
`read_encounter_dates` inteiro, o extractor foi substituído por subprocess fake
e a matriz de paridade mockou o source. R2 do extractor e a decisão posterior
do worker estão corretos; não os reimplemente.

Objetivo exato: fechar o objetivo vertical de S2 com navegação realista na mesma
página/sessão e elegibilidade batch-bound comprovadas por teste stateful. Não
implemente classificador, UI, health, métricas ou qualquer parte de S3–S5.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Este é um slice corretivo após falso positivo de testes. Siga literalmente. Se
qualquer item falhar, escreva `Status: INCOMPLETE`, não marque nenhuma task, não
faça commit/push e responda com bloqueio e evidência.

1. Registre `BASE_REF=$(git rev-parse HEAD)`, confirme que ele contém
   `829afd5`, registre `git status --short` limpo e escreva matriz
   `Requisito → arquivo(s) → teste(s)` no relatório.
2. Rode baseline oficial `./scripts/test-in-container.sh unit`; qualquer
   failure/error ou exit não zero bloqueia antes de editar.
3. Faça RED real primeiro. O teste positivo deve exercitar
   `_capture_encounter_sidecar → wait_encounters_table → read_encounter_dates`
   sem mockar essas três funções e falhar rapidamente porque o clique não
   existe. Falha de import/fixture não conta.
4. GREEN mínimo: corrigir apenas os dois defeitos confirmados nos arquivos
   permitidos.
5. REFACTOR local: clean code, DRY, YAGNI, nomes claros e erro sanitizado. Não
   refatore o extractor ou fluxos de evolução.
6. Rode inspeções e todos os gates oficiais deste arquivo.
7. Unit final deve ter exit zero, zero failures/errors e
   `passed_final >= passed_baseline`; integration e quality gate devem ter exit
   zero.
8. Gere relatório reproduzível e commit corretivo, mas **não marque 2.x nem
   2R.x**. Somente planner/verificador pode marcar tasks após revisão
   independente do commit.

## Objetivo vertical

Uma captura clássica sintética, batch-bound e vazia permanece em `Internações`
até `_capture_encounter_sidecar` clicar o item exato `Atendimentos`; somente
depois a tabela se torna acessível, as datas são parseadas/ordenadas e o sidecar
é gravado no mesmo job. Standalone, lista não vazia e full-sync não fazem esse
clique nem solicitam sidecar.

## Requisitos funcionais

### R1 — Navegação explícita antes da leitura

Em `_capture_encounter_sidecar`, depois dos guards de admissions-only, opção
explícita e lista vazia:

1. obter `page.get_by_text("Atendimentos", exact=True)`;
2. aguardar `visible` com timeout bounded compatível com o arquivo;
3. clicar;
4. somente então chamar `read_encounter_dates(page)` e gravar o sidecar.

A ordem é obrigatória. Usar a mesma `page`, sessão, browser e subprocess. Não
abrir URL, login, browser ou subprocess adicional. Não importar o app Django em
`path2.py` apenas para reutilizar o helper de S1.

### R2 — Falha de clique rápida e sanitizada

Ausência/timeout/falha no menu deve produzir mensagem constante, sem texto do
locator, seletor dinâmico, URL, HTML, registro, profissional, cookie ou
credencial. Preservar o tratamento de subprocess/worker existente. Não expor o
`repr` da exceção Playwright.

### R3 — Sidecar somente para batch-bound

Em `_process_admissions_only`, solicitar o sidecar somente quando
`run.batch_id is not None`. O guard deve existir antes de iniciar o subprocess,
não apenas no `except EmptyAdmissionsSnapshotError` posterior.

Matriz obrigatória:

| Fluxo | Solicita sidecar | Navega para Atendimentos |
| --- | --- | --- |
| `admissions_only` batch-bound vazio | sim | uma vez |
| `admissions_only` batch-bound não vazio | opção pode existir | não |
| `admissions_only` standalone vazio/não vazio | não | não |
| `full_sync` | não | não |

Standalone vazio preserva o resultado anterior ao S2; não deve falhar por
captura de Atendimentos.

### R4 — Teste stateful prova transição de página

Criar/ajustar fake page/frame/locator com estado inicial `internacoes`:

- rows do seletor de Atendimentos não ficam attached antes do clique;
- `get_by_text` registra texto e `exact`;
- `wait_for` registra `visible`;
- `click` muda o estado para `atendimentos`;
- depois da mudança, o parser real recebe rows sintéticas com quatro células,
  descarta inválidas, ordena datas e grava sidecar;
- a sequência de eventos é verificável.

O teste positivo não pode mockar `_capture_encounter_sidecar`,
`wait_encounters_table` nem `read_encounter_dates`. Controle o relógio fake ou o
timeout para que o RED termine em segundos, nunca espere 60 segundos reais.

### R5 — Regressões negativas e compatibilidade

Provar que:

- admissions não vazias não obtêm/clicam `Atendimentos`;
- opção ausente não obtém/clica `Atendimentos`;
- worker standalone passa `include_encounter_sidecar=False`;
- worker batch-bound passa `True`;
- full-sync preserva default `False`;
- admissions JSON continua lista e sidecar continua mínimo;
- extractor mantém um subprocesso e não é alterado;
- recent/boundary/stale/none e counters/stages/follow-ups continuam conforme
  testes S2 existentes.

### R6 — Privacidade e escopo corretivo

Fixtures são sintéticas. Sentinelas de registro, nome, profissional, URL, HTML,
cookie e senha devem estar ausentes de mensagem/output ao simular clique falho.
Não acessar browser, rede, legado ou produção. Não alterar S1, extractor,
models, migrations, status, dependências ou interfaces.

## Arquivos esperados e limite

Máximo de **3 arquivos de código/teste**, sem contar o relatório temporário:

1. `automation/source_system/medical_evolution/path2.py`;
2. `apps/ingestion/management/commands/process_ingestion_runs.py`;
3. `tests/unit/test_current_vs_persistent_encounter_parity.py`.

`tasks.md` já foi ajustado pela governança e **não deve ser marcado ou editado
pelo implementador**. Não editar `playwright_extractor.py`, arquivos S1,
OpenSpec, models, migrations, views, templates, health, métricas, docs,
dependências ou testes não listados. Se um quarto arquivo parecer necessário,
pare e reporte bloqueio; não exceda silenciosamente.

## TDD obrigatório

### RED

Antes de código de produção, adicionar:

1. teste stateful end-to-end da função path2 descrito em R4;
2. teste que exige chamada exata e sequência
   `get_by_text → wait visible → click → frame/rows → sidecar`;
3. teste de clique falho com sentinelas e mensagem sanitizada;
4. testes batch-bound versus standalone inspecionando o valor real de
   `include_encounter_sidecar` enviado a `_capture_admissions`;
5. guardas não vazio/opção ausente/full-sync.

Rode o subconjunto no container. Registre pelo menos uma falha funcional por
navegação ausente e uma por standalone recebendo `True`. O RED deve concluir
rapidamente e não pode mockar a unidade crítica.

### GREEN

Adicionar o clique bounded/sanitizado antes da leitura e tornar o flag do worker
condicional a `run.batch_id`. Nada além de R1–R6.

### REFACTOR

Se criar helper local, ele deve encapsular somente o clique e mensagem constante.
Evite duplicar parser/recency. Não reorganize o arquivo `path2.py`, CLI,
subprocess, cache, lifecycle ou worker além das linhas necessárias.

## Checks de inspeção obrigatórios antes de concluir

```bash
rg -n 'get_by_text\("Atendimentos"|exact=True|read_encounter_dates|_capture_encounter_sidecar' \
  automation/source_system/medical_evolution/path2.py
rg -n 'include_encounter_sidecar|run\.batch_id|_process_admissions_only|_process_full_sync' \
  apps/ingestion/management/commands/process_ingestion_runs.py
rg -n 'stateful|internacoes|atendimentos|get_by_text|event|include_encounter_sidecar' \
  tests/unit/test_current_vs_persistent_encounter_parity.py
rg -n 'patch\.object\([^\n]*read_encounter_dates|patch\.object\([^\n]*wait_encounters_table' \
  tests/unit/test_current_vs_persistent_encounter_parity.py
rg -n 'patient_record|professional|profissional|cookie|password|html|https?://' \
  tests/unit/test_current_vs_persistent_encounter_parity.py
git diff --name-only

git diff --check
git diff --stat
```

Também execute uma inspeção de ordem, ajustando o script somente se os nomes
finais permanecerem equivalentes:

```bash
python - <<'PY'
from pathlib import Path
text = Path("automation/source_system/medical_evolution/path2.py").read_text()
start = text.index("def _capture_encounter_sidecar")
end = text.index("\ndef ", start + 5)
block = text[start:end]
assert block.index('get_by_text("Atendimentos"') < block.index(
    "read_encounter_dates(page)"
)
print("click-before-read: OK")
PY
```

Interprete no relatório:

- o clique exato ocorre antes da leitura;
- o teste stateful positivo não está entre ocorrências que mockam funções
  críticas; mocks antigos podem permanecer apenas em testes negativos isolados;
- flag batch-bound é decidido antes do subprocess;
- full-sync e standalone não solicitam sidecar;
- `git diff --name-only` contém somente os três arquivos permitidos;
- sentinelas aparecem apenas como dados sintéticos com asserção de ausência.

Busca textual isolada não substitui o teste stateful.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate recognize-patient-flow-findings --strict
./scripts/markdown-lint.sh
```

Execução host-only é somente diagnóstico e não substitui os gates oficiais.
Nenhum gate pode acessar o legado.

## Critérios binários de sucesso

- [ ] R1–R6 cobertos por RED/GREEN sintético.
- [ ] Clique exato, visible e ordem click-before-read comprovados.
- [ ] Teste stateful executa parser/wait/capture reais e termina rapidamente.
- [ ] Batch-bound solicita sidecar; standalone/full-sync não solicitam.
- [ ] Não vazio e opção ausente não clicam Atendimentos.
- [ ] Um browser/login/subprocess por job e extractor inalterado.
- [ ] JSON/lista, sidecar, recency e decisão S2 permanecem compatíveis.
- [ ] Erros e outputs não vazam sentinelas.
- [ ] Somente três arquivos permitidos no diff.
- [ ] Gates exit zero e unit final não regride contagem.
- [ ] Tasks permanecem desmarcadas aguardando terceiro verificador.

### Condições automáticas de INCOMPLETO

Marque incompleto se baseline, RED funcional, inspeção ou gate não tiver
evidência; RED esperar próximo de 60 segundos; teste positivo mockar
`_capture_encounter_sidecar`, `wait_encounters_table` ou
`read_encounter_dates`; clique estiver ausente/depois da leitura/sem `exact`;
standalone ou full-sync solicitar sidecar; não vazio clicar Atendimentos;
segundo browser/login/subprocess surgir; raw exception/PHI/segredo aparecer;
extractor/S1/OpenSpec/model/migration/dependência/arquivo extra for alterado;
teste existente for removido ou enfraquecido; tasks forem marcadas pelo
implementador; relatório não existir; unit final tiver exit não zero,
failures/errors ou menos passed que baseline.

## Gates de autoavaliação

1. Qual sequência de eventos prova que a página começou em `Internações`?
2. O teste positivo executa as três funções críticas reais? Mostre as linhas.
3. Como o RED terminou rápido sem depender de 60 segundos reais?
4. Qual teste prova `exact=True`, visible e click-before-read?
5. Onde o flag é decidido antes do subprocess para batch versus standalone?
6. Qual teste prova full-sync sem sidecar?
7. Qual evidência mantém subprocess/cache/extractor intactos?
8. Como erro de clique remove sentinelas e raw exception?
9. Por que cada um dos três arquivos alterados foi indispensável?
10. As tasks continuam desmarcadas para revisão independente?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-PFIF-S2R-report.md` com:

- `Status: COMPLETE|INCOMPLETE`;
- BASE_REF e prova de descendência/conteúdo de `829afd5`;
- resumo da reprovação S2 sem copiar dado sensível;
- matriz requisito→arquivo→teste;
- baseline unit com exit, passed, failed e errors;
- RED com comandos, duração, falhas funcionais e motivo esperado;
- GREEN/REFACTOR com comandos e resultados;
- snippets antes/depois de cada arquivo alterado;
- sequência completa do fake stateful e sidecar resultante sintético;
- matriz batch/standalone/full-sync e valores do flag;
- inspeções `rg`/ordem/diff e interpretação;
- unit baseline versus final, com zero failures/errors e exit zero;
- todos os gates, OpenSpec strict e markdown lint;
- confirmação de extractor/S1/tasks inalterados;
- arquivos alterados e justificativa;
- riscos, limitações e respostas aos gates de autoavaliação;
- comandos exatos para rerun;
- `Handoff para verificador` com checklist R1–R6 e instrução explícita para
  reprovar se o teste positivo mockar a unidade crítica.

Não sobrescrever o relatório S2 original. Não incluir dados reais/sensíveis.
Somente escrever `Status: COMPLETE` se todos os critérios técnicos forem
comprovados; ainda assim, tasks permanecem desmarcadas até aprovação externa.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full recognize-patient-flow-findings change, PFIF-S1 evidence, the rejected PFIF-S2 report/evaluation, commit 829afd5 and SLICE-PFIF-S2R.md. Implement ONLY PFIF-S2R. Follow its DeepSeek4-Flash protocol: clean official unit baseline, requirement matrix, fast real RED using a stateful page that starts on Internações, minimal GREEN, local clean-code/DRY/YAGNI refactor, mandatory inspections and every official container gate. Fix exactly two defects: path2 must exact-click visible Atendimentos before the real wait/parser/read, and the classic worker must request the sidecar only for batch-bound admissions_only. The positive test may not mock _capture_encounter_sidecar, wait_encounters_table or read_encounter_dates. Preserve one subprocess/browser/login, standalone/full-sync behavior, sidecar/list compatibility, S1 and the extractor. Touch only path2.py, process_ingestion_runs.py and test_current_vs_persistent_encounter_parity.py. Never access browser/network/legacy/production. Create /tmp/sirhosp-slice-PFIF-S2R-report.md without overwriting S2 evidence. Do NOT edit or mark tasks.md; third-party approval is mandatory. If any item is missing/failing, report INCOMPLETE and do not commit. If technically complete, commit and push the three-file correction, reply REPORT_PATH=..., then STOP for independent verification before S3.
```
