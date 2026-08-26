# MOQA-S1 — Conflitos tipados e elegibilidade occupancy-v4

## Handoff para implementador com contexto zero

Você está no SIRHOSP, monólito Django 5/Python 3.12/PostgreSQL. Este é o
primeiro de três slices do change `make-occupancy-quality-actionable`.

Leia integralmente, nesta ordem, antes de editar:

1. `AGENTS.md`;
2. `PROJECT_CONTEXT.md`;
3. `openspec/changes/make-occupancy-quality-actionable/proposal.md`;
4. `openspec/changes/make-occupancy-quality-actionable/design.md`;
5. `openspec/changes/make-occupancy-quality-actionable/tasks.md`;
6. os quatro delta specs deste change;
7. este arquivo;
8. `docs/adr/ADR-0005-duas-realidades-capacidade-oficial-e-posicoes-legado.md`;
9. o change anterior `separate-official-and-physical-bed-realities`, no caminho
   ativo ou em `openspec/changes/archive/`, especialmente design e specs;
10. `apps/census/models.py`, migrations `0018` a `0021`;
11. `apps/census/occupancy.py` integralmente;
12. `apps/census/services.py` somente no fluxo `process_census_snapshot`;
13. `tests/unit/test_occupancy_measurement.py`;
14. testes de ocupação em `tests/unit/test_process_census_snapshot.py`.

Estado esperado:

- v1/v2 contam linhas e permanecem históricos;
- v3 normaliza por origem+leito, consolida duplicata exata e exclui toda posição
  com assinatura divergente;
- qualquer `position_partial` v3 exclui a medição das médias diárias;
- reconciliação v3 schema 1 é allowlisted e privada;
- disponibilidade e excedente v3 são somados por grupo sem compensação;
- o gate de 40 setores ocorre antes da materialização e não pertence a este
  slice;
- o catálogo JSON v4, aliases e `/beds` pertencem a S2/S3.

Objetivo: entregar, com catálogo sintético persistido diretamente no teste, uma
medição `occupancy-v4` end-to-end até o resumo diário. V4 classifica conflitos
por impacto, conta conflito apenas de ocupante uma vez, omite status/idade
ambíguos, persiste reconciliação schema 2 privada e mantém toda medição v4
materializada elegível com contador de ressalvas.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Este slice será implementado por um modelo rápido e com tendência a concluir
cedo. Siga literalmente. Se qualquer item falhar, o slice está **INCOMPLETO**:
não marque `tasks.md`, não faça commit/push e responda com bloqueio e evidência.

1. Registre no relatório matriz `Requisito → arquivo(s) → teste(s)/inspeção`.
2. Registre `BASE_REF=$(git rev-parse HEAD)` e `git status --short`; árvore
   rastreada não limpa bloqueia o início.
3. Antes de editar, execute `./scripts/test-in-container.sh unit`, registre exit
   code, `passed`, zero `failed` e zero `errors`. Falha bloqueia.
4. Escreva testes primeiro e prove RED funcional real; import, sintaxe, fixture
   ou migration quebrada não contam.
5. Implemente GREEN mínimo somente nos arquivos permitidos.
6. Faça REFACTOR controlado com clean code, DRY, YAGNI, funções coesas e nomes
   claros; não reescreva v1–v3.
7. Execute todos os checks `rg` e interprete cada resultado.
8. Execute gates oficiais em container; host-only é apenas diagnóstico.
9. Compare unit final com baseline: exit 0, zero failures/errors e
   `passed_final >= passed_baseline`.
10. Relatório deve apresentar evidência verificável, não opinião.

## Objetivo vertical

Dado um run sintético aceito e um catálogo persistido que declara v4:

- materializar exatamente uma medição;
- tipar duplicata, conflito de ocupante, status, idade e identidade ausente;
- fechar duas pontes agregadas sem PHI;
- persistir qualidade `clean` ou `warning`;
- calcular valores oficiais conservadores;
- incluir a medição no resumo diário mesmo com warning;
- manter v3 estritamente inelegível quando parcial;
- preservar fluxo clínico e idempotência.

## Requisitos funcionais

### R1 — Algoritmo v4 explícito

- adicionar constante/estratégia `occupancy-v4`;
- despachar somente pelo algoritmo persistido no catálogo aplicável;
- catálogo sintético direto é suficiente neste slice;
- não alterar parser, comando ou JSON de catálogo.

### R2 — Deduplicação antes da tipagem

Para cada chave origem+leito:

- agrupar assinaturas equivalentes e contar extras exatas;
- avaliar somente assinaturas únicas para classificar conflito;
- prontuário não participa da chave física;
- mesmo prontuário em leitos diferentes continua duas posições;
- nenhum snapshot é editado.

### R3 — Precedência de conflitos

Aplicar em ordem testada:

1. status divergente → `status_conflict`, sem estado vencedor;
2. status ocupado em código particionado com seletores divergentes/unknown →
   `age_conflict`, sem grupo etário vencedor;
3. todas ocupadas com mesmo seletor efetivo e ocupante divergente →
   `occupant_conflict`, uma posição ocupada contada;
4. uma assinatura após deduplicação → posição inequívoca.

Em código não particionado, drift etário não deve omitir ocupação. Conflito entre
estados não ocupados não afeta numerador, mas continua warning.

### R4 — Linha sem identidade

- leito vazio não forma posição;
- ocupado sem leito fica fora do numerador por não poder ser deduplicado;
- não ocupado sem leito permanece diagnóstico;
- ambos podem tornar a qualidade warning conforme design, sem bloquear resumo.

### R5 — Reconciliação schema 2

Criar allowlist explícita e versionada. Provar:

```text
raw occupied rows =
  duplicate occupied extras
+ occupant-conflict occupied extras
+ status-conflict occupied rows
+ age-conflict occupied rows
+ unidentified occupied rows
+ unknown partition positions
+ counted occupied positions

counted occupied positions =
  official numerator
+ occupied unrated
+ occupied unmapped
+ occupied linked-pending
```

Cada linha/categoria entra uma vez. Separar posições e linhas afetadas. Não
persistir nome, prontuário, leito, idade exata, chave ou assinatura.

### R6 — Qualidade v4 aditiva

Adicionar ao modelo um campo nullable explícito de qualidade v4, com constraint
compatível e histórico nulo. `warning` deve cobrir conflitos, ocupado sem
posição, unknown/age conflict e ocupado unmapped. Uma medição limpa deve ser
identificável sem inspecionar PHI.

### R7 — Elegibilidade diária v4

Adicionar contador diário de warnings:

- toda medição v4 materializada é elegível;
- dia só com warnings ainda calcula médias/min/max/excedente;
- warning count não incrementa `age_excluded` nem `position_excluded`;
- v2/v3 preservam exatamente exclusões anteriores;
- grupos diários v4 incluem medições com warning;
- nenhuma rotina de backfill.

### R8 — Cálculo oficial preservado

- `occupant_conflict` conta uma posição no grupo calculável ou na categoria
  não calculável aplicável;
- status/idade ambíguos e ocupado sem leito ficam fora;
- disponibilidade/excedente continuam por grupo sem compensação;
- percentual continua `ROUND_HALF_UP` e pode superar 100%.

### R9 — Imutabilidade, privacidade e idempotência

- segunda materialização retorna objeto existente sem refresh;
- campos v1–v3 novos ficam nulos/default histórico seguro;
- nenhuma query de backfill, `RunPython` ou edição de migration anterior;
- logs/exceções não incluem chave física ou alternativa conflitante.

### R10 — Fluxo clínico e cobertura preservados

Adicionar regressão v4 no fluxo existente comprovando que warning não impede
batch/enqueue. Não alterar limiar 40, extração, serviços ou ingestão. Se teste
exigir mudança produtiva fora de ocupação, pare e reporte bloqueio antes de
editar.

## Arquivos esperados e limite rígido

Máximo: **5 arquivos de implementação/teste**, incluindo migration:

1. `apps/census/models.py`;
2. `apps/census/occupancy.py`;
3. `apps/census/migrations/0022_*.py`;
4. `tests/unit/test_occupancy_measurement.py`;
5. `tests/unit/test_process_census_snapshot.py`.

Use o próximo número real se a branch divergir e explique. Se precisar de sexto
arquivo, pare como **INCOMPLETO/BLOQUEADO**; não expanda silenciosamente.

## Fora de escopo

Não alterar:

- `apps/census/capacity_catalog.py` ou comando de ativação;
- qualquer JSON de catálogo;
- views, template, CSS ou URLs;
- ADRs/documentação de release;
- `apps/census/services.py`, apps de ingestão/pacientes ou Playwright;
- migrations existentes, snapshots ou dados históricos.

Não adicionar dependência, Celery, Redis, scheduler ou serviço.

## TDD obrigatório

### RED

Criar primeiro testes sintéticos para, no mínimo:

1. duplicata exata consolidada antes de conflito;
2. duas assinaturas ocupadas com ocupantes diferentes contam uma posição;
3. alternativas ocupada/vaga produzem status conflict e zero ocupação;
4. 3A com faixas divergentes produz age conflict e nenhuma partição;
5. drift etário não particionado conta ocupação;
6. mesmo prontuário em leitos distintos conta duas posições;
7. ocupado sem leito não conta e gera warning;
8. reconciliação schema 2 fecha nas duas pontes;
9. recursão de privacidade rejeita marcadores sintéticos;
10. unrated, unmapped e pending ficam separados;
11. dia v4 só com warning permanece elegível e estatístico;
12. v3 parcial continua excluído e sem novo contador;
13. disponibilidade/excedente sem compensação;
14. idempotência;
15. fluxo clínico continua.

Execute:

```bash
./scripts/test-in-container.sh unit
```

Registre ao menos um teste novo falhando pelo comportamento v4 ausente.

### GREEN

Implemente o mínimo coeso e rode novamente o unitário oficial até zero falhas.

### REFACTOR

Depois do GREEN:

- mantenha normalização linear no número de linhas;
- use dataclasses/enums pequenos, sem abstração genérica prematura;
- centralize precedência e allowlist;
- compartilhe cálculo v3/v4 somente onde semântica for realmente igual;
- evite booleanos ambíguos e comentários de conversa;
- preserve funções históricas cobertas por regressão.

## Checks de inspeção obrigatórios

```bash
rg -n "occupancy-v1|occupancy-v2|occupancy-v3|occupancy-v4" \
  apps/census/occupancy.py apps/census/models.py
rg -n "quality.*warning|position_excluded|age_excluded|daily.*eligible" \
  apps/census/models.py apps/census/occupancy.py
rg -n "schema_version|occupant_conflict|status_conflict|age_conflict|unrated|unmapped" \
  apps/census/occupancy.py tests/unit/test_occupancy_measurement.py
rg -n "prontuario|patient_name|record|leito|bed" \
  apps/census/models.py apps/census/occupancy.py
rg -n "RunPython|RemoveField|DeleteModel" apps/census/migrations/0022_*.py
rg -n "MINIMUM_CENSUS_SECTORS|= 40" apps/census/services.py
rg -n "Celery|Redis|apply_async|\.delay\(" apps/census
```

Interprete no relatório:

- PHI pode existir apenas em estruturas efêmeras já necessárias; prove que não
  alcança model/JSON/log;
- v3 deve continuar presente e strict;
- migration deve ser aditiva e sem backfill;
- o valor 40 deve permanecer intocado;
- buscas proibidas sem resultado devem ser registradas como esperado.

Drift de migration:

```bash
./scripts/test-in-container.sh check
```

Não aceite warning host-only como substituto.

## Gates oficiais

Execute todos:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate make-occupancy-quality-actionable --strict
./scripts/markdown-lint.sh
```

Registre exit code e resumo. Quality gate não substitui integração explícita.

## Critérios de sucesso binários

- [ ] Baseline oficial verde e registrado antes da edição.
- [ ] RED funcional real comprovado.
- [ ] V4 despachado somente por catálogo persistido.
- [ ] Duplicata, occupant/status/age conflict têm semânticas distintas.
- [ ] Occupant conflict conta uma posição sem autoridade nominal.
- [ ] Status/age conflict e ocupado sem leito não contam.
- [ ] Duas pontes schema 2 fecham e não contêm PHI.
- [ ] Toda medição v4 entra no resumo; warning é contado separadamente.
- [ ] V1–v3 e seus resumos permanecem idênticos.
- [ ] Disponibilidade/excedente permanecem não compensados.
- [ ] Fluxo clínico e gate 40 permanecem intactos.
- [ ] Idempotência e ausência de backfill comprovadas.
- [ ] Migration aditiva e sem drift.
- [ ] Todos os gates e inspeções verdes.
- [ ] Máximo de cinco arquivos respeitado.
- [ ] Relatório completo criado.

## Gates de autoavaliação

Responder no relatório:

1. Qual precedência evita contar status ambíguo como occupant conflict?
2. Como duplicatas dentro de múltiplas alternativas entram uma vez na ponte?
3. Por que drift etário fora de setor particionado não omite ocupação?
4. Mostre numericamente as duas equações sintéticas.
5. Quais categorias geram warning v4?
6. Como `_is_daily_eligible` distingue v3 de v4?
7. Qual teste prova que contadores de exclusão v3 não foram reutilizados?
8. Como PHI fica restrita à memória?
9. Qual teste preserva fluxo clínico e gate 40?
10. Houve arquivo extra ou alteração antecipada de S2/S3?

### Condições automáticas de INCOMPLETO

Marque incompleto se qualquer condição ocorrer:

- baseline ausente, falho ou posterior à edição;
- teste planejado ausente ou RED não funcional;
- qualquer gate, integração, lint, typecheck ou markdown lint falhar;
- final com exit != 0, failure/error ou menos passed que baseline;
- conflito de ocupante não contar uma posição, ou escolher paciente vencedor;
- status/idade ambígua receber valor vencedor;
- ponte não fechar para mistura de duplicata+conflito;
- PHI persistida/impressa em log, erro ou relatório;
- v3 tornar-se elegível retroativamente;
- warning v4 incrementar contador histórico de exclusão;
- gate 40, services, catálogo ou UI alterados;
- migration destrutiva/backfill/edição histórica;
- mais de cinco arquivos tocados;
- `tasks.md` marcado antes das evidências;
- relatório ausente ou sem snippets por arquivo.

## Relatório obrigatório

Criar exatamente:

```text
/tmp/sirhosp-slice-MOQA-S1-report.md
```

Incluir:

1. `Status: COMPLETE|INCOMPLETE`;
2. resumo e `BASE_REF`/status inicial;
3. matriz R1–R10 → arquivos → testes/inspeções;
4. baseline com comando, exit, passed/failed/errors;
5. RED real com assertion esperada/obtida;
6. GREEN e REFACTOR;
7. arquivos e justificativas;
8. snippets antes/depois de cada arquivo;
9. migration e prova sem backfill;
10. duas equações sintéticas;
11. checks `rg` interpretados;
12. todos os gates com exit/resumo;
13. comparação baseline/final;
14. respostas de autoavaliação;
15. riscos/limitações;
16. comandos exatos para rerun;
17. `Handoff para verificador` com checklist R1–R10.

Somente após tudo passar, marque 1.1–1.6, commit/push e responda
`REPORT_PATH=/tmp/sirhosp-slice-MOQA-S1-report.md`. Então pare.

## Prompt pronto para implementador LLM

```text
Read AGENTS.md, PROJECT_CONTEXT.md and every artifact under
openspec/changes/make-occupancy-quality-actionable, especially
slice-prompts/SLICE-MOQA-S1.md. Assume zero prior context.

Implement ONLY MOQA-S1. Follow the DeepSeek4-Flash protocol literally: clean
state, BASE_REF, official container unit baseline before edits, real RED,
minimal GREEN, controlled REFACTOR, mandatory inspections, all official gates,
integration and baseline-vs-final evidence. Apply clean code, DRY and YAGNI.
Touch at most the five allowed files. Do not implement catalog parsing/JSON,
aliases, UI, ADR, release or activation. Preserve v1-v3, the primary 40-sector
gate, exact-run, privacy, history and clinical processing.

If any test/check/gate is missing or failing, final pytest has failure/error,
passed_final < passed_baseline, privacy is uncertain, a conflict receives an
arbitrary winner, history is reinterpreted, migration is not additive or file
limit is exceeded, report INCOMPLETE; do not mark tasks or commit/push.

Create /tmp/sirhosp-slice-MOQA-S1-report.md with RED/GREEN evidence,
before/after snippets for every changed file, migration inspection, complete
gates, rerun commands, self-evaluation and Handoff para verificador. Mark only
tasks 1.1-1.6 after all criteria pass. Commit, push, reply with REPORT_PATH and
STOP.
```
