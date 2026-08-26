# CIPOO-S1 — Medição v5 por paciente identificado

## Handoff com contexto zero

Você está no repositório SIRHOSP. Leia integralmente antes de editar:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. `openspec/changes/count-identified-patients-for-official-occupancy/{proposal.md,design.md,tasks.md}`;
3. as quatro delta specs deste change;
4. este arquivo;
5. `apps/census/{models.py,occupancy.py,services.py}`;
6. migrations 0021–0023;
7. `tests/unit/test_occupancy_measurement.py` e testes de processamento clínico;
8. artefatos do change ativo `make-occupancy-quality-actionable` para entender
   v4, sem editá-los.

Estado de entrada esperado: RC10/v4 já publicado; SIRHOSP suporta v1–v4,
medições imutáveis, resumo diário e catálogo temporal. V4 conta posições por
leito. Este slice adiciona v5 por paciente, mas não adiciona JSON v5 nem UI.
Testes podem criar catálogo v5 sintético diretamente no banco.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Este slice será implementado por um modelo rápido e com tendência a concluir
cedo. Siga literalmente. Se qualquer item falhar, responda `INCOMPLETE`, não
marque tasks e não faça commit/push.

1. Registre `BASE_REF=$(git rev-parse HEAD)`, `git status --short` e matriz
   `Requisito → arquivo(s) → teste(s)` no relatório antes de editar.
2. O projeto exige gates em container. Rode baseline oficial
   `./scripts/test-in-container.sh unit`; host-only não substitui gate. Registre
   exit code, `passed`, `failed` e `errors`. Baseline com falha bloqueia.
3. Escreva testes primeiro. Rode a suíte unitária e prove RED real pelo motivo
   funcional esperado, não por import/sintaxe/migration ausente acidental.
4. Implemente GREEN mínimo. Não toque catálogo JSON, template, view, ADR,
   release ou produção.
5. Refatore somente o código tocado: nomes claros, funções puras coesas, DRY,
   YAGNI, sem branch por código hardcoded além do seletor de catálogo.
6. Rode inspeções obrigatórias, unit GREEN, integração e todos os gates oficiais.
7. Compare baseline/final: final com exit 0, zero failures/errors e
   `passed_final >= passed_baseline`.
8. Gere relatório verificável. Somente então marque tarefas 1.1–1.6, commit/push
   e pare.

## Objetivo vertical

Materializar end-to-end uma medição sintética `occupancy-v5`, seus grupos,
reconciliação privada e resumo diário usando pacientes identificados
 deduplicados por grupo. O valor observável é uma medição imutável e elegível
que conta pacientes sem leito e pessoas distintas no mesmo leito.

## Requisitos funcionais

### R1 — Identidade válida

- prontuário: trim, não vazio, somente dígitos, string e zeros preservados;
- nome: trim/uppercase/espaços colapsados, não vazio e não marcador operacional;
- marcador operacional cobre vaga/desocupado/vazio, limpeza/manutenção, reserva
  e isolamento;
- identidade parcial ou record não numérico não conta e incrementa agregado
  seguro de identificação incompleta.

### R2 — Deduplicação por grupo

- mesma record string no mesmo grupo conta uma vez, independentemente de nome,
  leito ou código-fonte;
- Cardio com dois códigos deduplica uma vez no grupo compartilhado;
- dois records no mesmo leito contam dois;
- paciente sem leito conta;
- mesmo record em grupos diferentes conta uma vez em cada e incrementa contador
  agregado cross-group;
- variantes de nome contam uma pessoa e geram contador agregado.

### R3 — Partição 3A

Deduplicar record antes da partição. Se o conjunto de faixas confiáveis tiver
uma faixa, ela vence mesmo com linhas unknown. Se estiver vazio ou contiver as
duas faixas, usar fallback: qualquer nome normalizado começando literalmente
com `RN` vai para Infantil; demais vão para Adulto. `R.N.` não é RN. Persistir
somente faixa permitida e contadores agregados de RN/non-RN/conflito.

### R4 — Política e aritmética

- standard: pacientes únicos, taxa sem cap, saldo/excesso independentes;
- unrated: pacientes agregados visíveis, numerador/capacidade/taxa/saldo/excesso
  oficiais nulos;
- unmapped e pending separados;
- estados operacionais não entram nem reduzem capacidade;
- soma hospitalar fecha por grupos sem compensação.

### R5 — Reconciliação e privacidade

Novo schema allowlisted fecha `valid_identity_rows` em duplicações intragrupo e
atribuições standard/unrated/pending/unmapped. Incluir somente contagens de
identificação incompleta, cross-group, nomes variantes, fallbacks, sem leito e
estados operacionais. Proibir recursivamente nome, record, bed, idade, chave ou
assinatura. Falha de fechamento aborta transação com erro sanitizado.

### R6 — Qualidade, resumo e história

- migration aditiva permite `quality_warning` em v4 ou v5;
- toda medição v5 criada é daily-eligible;
- warning cobre motivos definidos no design, sem usar contadores históricos de
  exclusão;
- paciente sem leito conta e não torna a medição parcial;
- resumo equal-weight e idempotente;
- v1–v4 e summaries existentes não mudam nem recebem backfill.

### R7 — Fluxo clínico

Warning v5 e ausência de leito não bloqueiam batch closure, paciente clínico ou
filas. Nenhuma chamada externa/LLM real em testes.

## Arquivos esperados e limite

Máximo de **5 arquivos rastreados**:

1. `apps/census/occupancy.py`;
2. `apps/census/models.py`;
3. nova migration `apps/census/migrations/0024_*.py`;
4. `tests/unit/test_occupancy_measurement.py`;
5. opcionalmente um teste clínico existente, somente se indispensável a R7.

Não editar `services.py` se a lógica puder permanecer coesa e privada ao motor
v5 sem ciclo de import. Não criar módulo novo por conveniência. Se precisar
exceder cinco ou tocar arquivo fora da lista, pare e reporte bloqueio antes de
editar. `tasks.md`, prompt e relatório temporário não contam no limite.

## TDD obrigatório

### RED

Adicionar testes sintéticos, no mínimo:

1. record numérico com zero à esquerda;
2. record alfanumérico, nome vazio e marcador operacional não contam;
3. paciente sem leito conta;
4. dois records no mesmo leito contam dois;
5. mesmo record/mesmo grupo/múltiplos códigos conta um;
6. mesmo record em grupos diferentes conta em ambos + warning;
7. nomes variantes contam um;
8. 3A reliable child/adult, reliable+unknown, unknown RN, unknown non-RN,
   reliable conflict RN/non-RN e `R.N.`;
9. CO/unrated, balance/excess e percentual >100%;
10. reconciliação fecha e scanner recursivo não encontra PHI;
11. summary v5 clean/warned elegível e idempotente;
12. v4 e fluxo clínico permanecem.

Execute `./scripts/test-in-container.sh unit` e registre ao menos um failure
assertivo esperado antes da implementação.

### GREEN

Adicionar `ALGORITHM_VERSION_V5`, dispatch explícito e implementação mínima.
Reutilizar estruturas aritméticas seguras sem mudar branches v1–v4. Criar
migration sem `RunPython`, sem default destrutivo e sem backfill.

### REFACTOR

Extrair somente funções puras necessárias para normalização, agrupamento e
reconciliação. Evitar mega-função, booleanos ambíguos, duplicação de cálculo e
nomes `legacy`. Não generalizar infraestrutura futura.

## Checks de inspeção obrigatórios

Execute e interprete no relatório:

```bash
rg -n "ALGORITHM_VERSION_V5|occupancy-v5|quality_warning" \
  apps/census/occupancy.py apps/census/models.py apps/census/migrations/0024_*.py
rg -n "RunPython|record|prontuario|nome|patient_name|leito|bed" \
  apps/census/migrations/0024_*.py
rg -n "occupancy-v5|RN|cross.group|name.variant|incomplete.identity|without.bed" \
  tests/unit/test_occupancy_measurement.py
rg -n "Celery|Redis|backfill" apps/census/occupancy.py \
  apps/census/migrations/0024_*.py
```

Esperado: v5/constraint presentes; migration sem `RunPython`, identidade ou
backfill; testes cobrem contratos; nenhuma infraestrutura nova.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate count-identified-patients-for-official-occupancy --strict
```

Se qualquer Markdown do change for alterado, rode também
`./scripts/markdown-lint.sh`.

## Critérios binários de sucesso

- [ ] R1–R7 cobertos por testes RED/GREEN.
- [ ] Paciente sem leito conta; leito não é chave.
- [ ] Deduplicação é por group+record, não global.
- [ ] Fallback 3A segue precedência e prefixo literal.
- [ ] Reconciliation fecha sem PHI.
- [ ] Migration é aditiva e sem backfill.
- [ ] V1–v4 e fluxo clínico passam regressão.
- [ ] Todos os gates têm exit 0.
- [ ] Final passed >= baseline e zero failures/errors.
- [ ] Máximo de cinco arquivos, sem antecipar S2/S3.

### Condições automáticas de INCOMPLETO

- baseline não executado/registrado ou com falha;
- teste planejado ausente, sem RED real ou RED por erro acidental;
- record convertido para inteiro ou nome/record persistido;
- deduplicação por leito, nome ou hospital inteiro;
- paciente sem leito omitido;
- 3A unknown permanece fora ou cria grupo total;
- v4 alterado/recalculado;
- migration com backfill/RunPython;
- qualquer teste/gate falho, final menor que baseline;
- arquivo extra sem autorização;
- relatório ausente ou task marcada antes dos gates.

## Gates de autoavaliação

Responder com evidência no relatório:

1. Qual teste prova que o leito não influencia o numerador?
2. Qual teste distingue dedupe intragrupo de record em grupos diferentes?
3. Qual tabela de casos prova a precedência 3A?
4. Quais chaves exatas estão allowlisted na reconciliação?
5. Como foi provado que nenhum identificador persiste ou aparece em erro?
6. Qual teste preserva v4 e qual preserva fluxo clínico?
7. Por que cada arquivo alterado é necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CIPOO-S1-report.md` contendo:

- `Status: COMPLETE|INCOMPLETE`;
- BASE_REF e estado inicial;
- matriz requisito→arquivo→teste;
- RED: comando, exit, testes e motivo esperado;
- GREEN/refactor: comandos e resultados;
- snippets antes/depois por arquivo;
- migration/constraint e privacidade;
- inspeções `rg` com interpretação;
- baseline versus final (`passed`, `failed`, `errors`, exit code);
- todos os gates e comandos exatos para rerun;
- arquivos alterados e justificativa;
- riscos/limitações;
- respostas aos gates;
- `Handoff para verificador` com checklist R1–R7.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the complete OpenSpec change
count-identified-patients-for-official-occupancy, active MOQA artifacts, and
SLICE-CIPOO-S1.md. Implement ONLY S1. Follow the DeepSeek4-Flash protocol:
record clean BASE_REF, run the official containerized unit baseline before
editing, write a real RED, implement minimal GREEN, refactor only touched code
with clean code/DRY/YAGNI, run required rg inspections and every official gate,
and compare baseline vs final with zero failures/errors and final passed >=
baseline. Add occupancy-v5 measurement/daily semantics only; do not add catalog
JSON, UI, ADR, release or production operations. Touch at most five expected
files. Never persist/log PHI, backfill, alter v1-v4 or use live LLM/network.
Create /tmp/sirhosp-slice-CIPOO-S1-report.md with RED/GREEN evidence,
before/after snippets, gates, rerun commands and verifier handoff. If any item
fails, report INCOMPLETE and do not update tasks or commit. If all pass, mark
only S1 tasks, commit, push, reply REPORT_PATH=..., then STOP.
```
