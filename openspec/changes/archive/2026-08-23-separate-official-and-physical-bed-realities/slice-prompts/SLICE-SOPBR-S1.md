# SOPBR-S1 — Normalização física e materialização occupancy-v3

## Handoff para implementador com contexto zero

Você está no repositório SIRHOSP, um monólito Django 5/Python 3.12 com
PostgreSQL. Este é o primeiro de três slices do change
`separate-official-and-physical-bed-realities`.

Leia integralmente, nesta ordem, antes de editar:

1. `AGENTS.md`;
2. `PROJECT_CONTEXT.md`;
3. `openspec/changes/separate-official-and-physical-bed-realities/proposal.md`;
4. `openspec/changes/separate-official-and-physical-bed-realities/design.md`;
5. `openspec/changes/separate-official-and-physical-bed-realities/tasks.md`;
6. os cinco delta specs em
   `openspec/changes/separate-official-and-physical-bed-realities/specs/`;
7. este arquivo;
8. `apps/census/models.py` e migrations `0014` a `0020`;
9. `apps/census/occupancy.py`;
10. `tests/unit/test_occupancy_measurement.py`;
11. os testes de ocupação em `tests/unit/test_process_census_snapshot.py`.

Estado atual esperado:

- `occupancy-v1` conta linhas para catálogos sem partição etária;
- `occupancy-v2` conta linhas e divide a 3A pela faixa etária persistida;
- v2 não deduplica prontuário por decisão explícita;
- medições, grupos e resumos históricos são imutáveis;
- `age_partial` exclui uma medição v2 das médias diárias;
- o catálogo ainda não possui seleção explícita de v3;
- snapshots brutos contêm detalhe nominal e não podem ser copiados para a
  história agregada;
- o fluxo clínico processa snapshots brutos e deve continuar independente da
  qualidade de posição usada na ocupação.

Objetivo deste slice: entregar de ponta a ponta uma medição v3 criada a partir
de um catálogo sintético já persistido com algoritmo explícito. Ela deve
normalizar posições, persistir reconciliação privada, disponibilidade e
parcialidade, atualizar corretamente o resumo diário e não bloquear o fluxo
clínico. A publicação por JSON e a UI pertencem aos slices seguintes.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Este slice será implementado por um modelo rápido e com tendência a concluir
cedo demais. Siga este protocolo literalmente. Se qualquer item falhar, o slice
está **INCOMPLETO**: não marque `tasks.md`, não faça commit/push e responda com
bloqueio e evidência.

1. **Plano antes de editar:** registre no relatório uma matriz
   `Requisito → arquivo(s) → teste(s)/inspeção`.
2. **Estado limpo:** registre `BASE_REF=$(git rev-parse HEAD)` e
   `git status --short`. Se houver mudança versionada não explicada, pare.
3. **Baseline oficial antes de editar:** execute
   `./scripts/test-in-container.sh unit`, registre exit code, contagem de
   `passed`, zero `failed` e zero `errors`. Falha de baseline bloqueia o slice.
4. **RED real:** escreva primeiro os testes sintéticos deste slice. Execute o
   conjunto unitário oficial e prove que pelo menos um teste novo falha pelo
   motivo funcional esperado, não por import, fixture ou migration quebrada.
5. **GREEN mínimo:** implemente somente o necessário para tornar os testes
   verdes. Não antecipe catálogo JSON, comando, view, template ou ADR.
6. **REFACTOR controlado:** aplique clean code, nomes claros, coesão, DRY e
   YAGNI. Não faça refactor amplo de ocupação v1/v2.
7. **Inspeção obrigatória:** execute todos os `rg` e checks descritos abaixo e
   interprete os resultados no relatório.
8. **Gates oficiais:** execute exatamente os gates em container descritos neste
   arquivo. Comandos host-only são apenas diagnósticos suplementares.
9. **Comparação final:** o pytest unitário final deve ter exit code 0, zero
   failures/errors e `passed_final >= passed_baseline`.
10. **Evidência, não opinião:** relatório deve conter comandos, exit codes,
    resumos, snippets antes/depois por arquivo e handoff verificável.

## Objetivo vertical

Dado um run de censo sintético completo e um catálogo persistido que declara
`occupancy-v3`, materializar uma medição imutável que:

- converte linhas em posições físicas inequívocas;
- conta duplicata exata uma vez;
- mantém prontuário igual em leitos distintos;
- exclui conflitos e posição ocupada sem leito do numerador;
- marca parcialidade física;
- persiste reconciliação agregada sem PHI;
- calcula disponibilidade e excedente por grupo e por hospital;
- exclui medição parcial das médias diárias;
- deixa o fluxo clínico continuar.

## Requisitos funcionais do slice

### R1 — Seleção explícita e compatível do algoritmo

Adicionar contexto opcional de algoritmo em `CapacityCatalogVersion`.

- catálogo com valor explícito `occupancy-v3` despacha v3;
- catálogo histórico sem valor continua com despacho estrutural v1/v2;
- não usar data, hash, nome do arquivo ou configuração global para despachar;
- não editar catálogos ou medições existentes.

### R2 — Identidade conservadora de posição

A chave em memória usa código-fonte normalizado ou nome do setor como fallback,
mais leito normalizado. Leito vazio não forma posição confirmada.

- não usar prontuário como chave física;
- não persistir a chave;
- normalização deve ser determinística e pequena, sem biblioteca nova.

### R3 — Duplicata exata

Para uma mesma chave física:

- assinatura ocupada equivalente considera status, prontuário, nome e faixa;
- assinatura não ocupada equivalente considera status;
- linhas extras equivalentes são duplicatas;
- uma posição contribui uma vez para contagem física e oficial;
- snapshots permanecem intactos.

### R4 — Conflito e identidade ausente

- assinaturas divergentes na mesma chave produzem uma posição `conflict`;
- nenhuma linha conflitante contribui para numerador oficial;
- não escolher paciente ou status vencedor;
- linha ocupada sem leito fica fora do numerador;
- conflito ou linha ocupada sem identidade torna `position_partial=true`;
- linhas não ocupadas sem leito permanecem diagnóstico bruto sem inventar
  posição.

### R5 — Escopo transversal e compatibilidade 3A

A normalização vale para todos os códigos. Depois dela, v3 aplica os seletores
etários já existentes à posição ocupada inequívoca da 3A.

- idade desconhecida mantém `age_partial` e `unknown_age_count`;
- prontuário igual em leitos distintos continua contando duas vezes;
- não inferir mãe-criança;
- CO/unrated e unmapped continuam fora da taxa.

### R6 — Reconciliação agregada e privada

Persistir JSON fechado e versionado com inteiros suficientes para fechar:

- linhas ocupadas brutas;
- posições por status;
- duplicatas extras e duplicatas ocupadas;
- conflitos e linhas ocupadas conflitantes;
- linhas sem identidade e linhas ocupadas sem identidade;
- idade desconhecida da 3A;
- posições ocupadas inequívocas fora de grupos calculáveis;
- numerador oficial final.

A implementação pode escolher nomes claros para as chaves, mas deve ter
allowlist explícita e teste aritmético. É proibido persistir nome, prontuário,
leito, chave física, assinatura, idade exata ou texto clínico.

### R7 — Disponibilidade e excedente sem compensação

Para cada grupo calculável v3:

```text
available = max(capacity - occupied, 0)
exceeded = max(occupied - capacity, 0)
```

No hospital, somar disponibilidades e excedentes dos grupos separadamente. Não
usar `max(total_capacity - total_occupied, 0)` como disponibilidade hospitalar.
Campos v1/v2 novos permanecem nulos, sem reinterpretação.

### R8 — Resumo diário

Uma medição v3 é elegível somente quando `age_partial=false` e
`position_partial=false`.

- preservar total e elegíveis;
- preservar contador de motivo físico separado do motivo etário;
- motivos podem se sobrepor;
- se nenhuma medição for elegível, estatísticas oficiais ficam nulas;
- nenhuma rotina de backfill deve ser criada ou executada.

### R9 — Fluxo clínico preservado

Adicionar regressão comprovando que um run completo com conflito materializa
medição parcial e continua criando/processando o fluxo clínico esperado. Não
alterar `services.py`, management command ou app de ingestão salvo bloqueio
real reportado antes de editar.

### R10 — Imutabilidade e idempotência

Segunda materialização do mesmo run retorna a medição existente sem recalcular
reconciliação, grupos ou resumo. V1/v2 devem manter testes e valores atuais.

## Arquivos esperados e limite

Limite rígido: **até 5 arquivos de implementação/teste alterados**, contando a
nova migration como um arquivo.

Arquivos esperados:

1. `apps/census/models.py`;
2. `apps/census/occupancy.py`;
3. `apps/census/migrations/0021_*.py`;
4. `tests/unit/test_occupancy_measurement.py`;
5. `tests/unit/test_process_census_snapshot.py`.

Se o número real da migration divergir por mudança legítima de branch, use o
próximo número gerado por Django e explique. Se precisar de sexto arquivo, pare
e reporte **INCOMPLETO/BLOQUEADO** com a necessidade; não expanda silenciosamente.

## Fora de escopo e arquivos proibidos

Não alterar neste slice:

- `apps/census/capacity_catalog.py`;
- `apps/census/management/commands/activate_sector_capacity_catalog.py`;
- qualquer JSON em `apps/census/data/`;
- `apps/census/views.py`;
- `apps/census/templates/census/bed_status.html`;
- ADRs ou documentação de release;
- snapshots históricos ou migrations existentes;
- autenticação, permissões, pacientes, movimentos ou automação Playwright.

Não adicionar dependências. Não criar Celery, Redis, scheduler ou serviço.

## TDD obrigatório

### RED

Antes de código produtivo, adicionar testes com dados totalmente sintéticos
para, no mínimo:

1. duas linhas exatas do mesmo leito contam uma posição e uma duplicata extra;
2. mesmo prontuário em dois leitos conta duas posições;
3. mesmo leito com prontuários divergentes vira conflito e parcial;
4. mesmo leito com status divergentes vira conflito e parcial;
5. ocupado sem leito fica fora do numerador e torna parcial;
6. duplicata fora da 3A prova escopo transversal;
7. 3A v3 preserva partição por faixa após normalização;
8. JSON fecha aritmeticamente e não contém marcadores sensíveis sintéticos;
9. disponibilidade hospitalar soma saldos positivos sem compensar excedente;
10. medição parcial não entra no resumo diário;
11. idempotência e regressões v1/v2;
12. fluxo clínico continua diante de conflito.

Execute e registre:

```bash
./scripts/test-in-container.sh unit
```

Pelo menos um teste novo deve falhar por ausência do comportamento v3. Cole no
relatório nome do teste, assertion esperada/obtida, exit code e resumo.

### GREEN

Implemente a menor solução coesa. Execute novamente:

```bash
./scripts/test-in-container.sh unit
```

Todos os testes devem passar.

### REFACTOR

Somente depois do GREEN:

- extraia função pura pequena para normalização;
- evite ramificações v3 espalhadas quando uma estratégia local basta;
- mantenha PHI somente no objeto efêmero necessário à comparação;
- use allowlist constante para JSON;
- preserve funções v1/v2 sem duplicar cálculo comum;
- remova código morto e comentários de slice obsoletos apenas dentro dos
  arquivos tocados;
- não generalize para cenários não especificados.

## Checks de inspeção obrigatórios

Execute e interprete no relatório:

```bash
rg -n "occupancy-v1|occupancy-v2|occupancy-v3|position_partial|available" \
  apps/census/models.py apps/census/occupancy.py
rg -n "prontuario|nome|leito|exact_age|patient_name|record_number" \
  apps/census/models.py apps/census/occupancy.py
rg -n "RunPython|RemoveField|DeleteModel|AlterField" \
  apps/census/migrations/0021_*.py
rg -n "occupancy-v3|duplicate|conflict|position_partial|available" \
  tests/unit/test_occupancy_measurement.py \
  tests/unit/test_process_census_snapshot.py
rg -n "Celery|Redis|apply_async|\.delay\(" apps/census
```

Interpretação obrigatória:

- ocorrências de PHI em `_ObservedRow` ou helpers de apresentação preexistentes
  podem ser necessárias, mas nenhuma pode entrar em model/JSON agregado;
- migration deve ser aditiva e sem backfill;
- v1/v2 precisam continuar presentes e testados;
- não pode existir data hardcoded para selecionar v3;
- ausência de resultado em busca proibida deve ser registrada como esperada.

Rode também o diagnóstico de drift de migration:

```bash
uv run python manage.py makemigrations census --check --dry-run
```

O comando deve terminar com exit code 0 e `No changes detected`. Aviso host-only
de resolução de `db`, se ocorrer, é diagnóstico conhecido e não substitui os
gates em container.

## Gates oficiais de conclusão

Execute todos, sem omitir:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate separate-official-and-physical-bed-realities --strict
```

Se alterar qualquer Markdown além de `tasks.md`, execute também:

```bash
./scripts/markdown-lint.sh
```

Registre exit code e resumo de cada comando. O `quality-gate` não substitui a
integração explícita.

## Critérios de sucesso binários

- [ ] Baseline unitário oficial registrado antes da edição e totalmente verde.
- [ ] RED real registrado com falha funcional esperada.
- [ ] GREEN unitário com zero failures/errors.
- [ ] Catálogo sintético explícito despacha v3; legados preservam v1/v2.
- [ ] Duplicata exata conta uma posição em qualquer setor.
- [ ] Prontuário igual em leitos distintos não é deduplicado.
- [ ] Conflito e ocupado sem identidade tornam a medição parcial.
- [ ] JSON agregado fecha e não contém identificadores.
- [ ] Disponibilidade e excedente são somados por grupo, sem compensação.
- [ ] Resumo diário exclui parcialidade física e preserva motivos.
- [ ] Fluxo clínico não é bloqueado.
- [ ] Idempotência e história v1/v2 permanecem verdes.
- [ ] Migration é aditiva e não há model drift.
- [ ] Todos os gates oficiais e inspeções passaram.
- [ ] Limite de cinco arquivos foi respeitado.
- [ ] Relatório temporário completo foi criado.

## Gates de autoavaliação

Responda objetivamente no relatório:

1. Qual é a chave física e por que prontuário não faz parte dela?
2. Quais campos distinguem duplicata de conflito?
3. Uma duplicata fora da 3A foi comprovada por qual teste?
4. Como a ponte do numerador fecha? Mostre equação sintética.
5. Alguma chave/valor identificável pode alcançar o JSON persistido?
6. Como disponibilidade hospitalar difere de capacidade menos ocupação global?
7. O que acontece quando parcialidade etária e física coexistem?
8. Qual teste prova que o fluxo clínico continua?
9. Como catálogos históricos sem campo explícito preservam v1/v2?
10. Houve alteração fora dos cinco arquivos? Se sim, o slice é incompleto.

### Condições automáticas de INCOMPLETO

Marque como incompleto se ocorrer qualquer uma destas situações:

- baseline oficial não executado antes da edição ou com falha;
- teste planejado ausente, passando antes da implementação ou não executado;
- RED causado somente por erro de import, sintaxe, fixture ou migration;
- qualquer gate oficial, integração, lint ou typecheck falhar;
- pytest final com exit code diferente de 0, failures ou errors;
- `passed_final < passed_baseline`;
- migration destrutiva, backfill ou edição de migration anterior;
- v1/v2 recalculado, reescrito ou sem regressão;
- prontuário usado como chave de deduplicação entre leitos;
- conflito resolvido escolhendo arbitrariamente uma linha;
- identificador persistido ou impresso em alerta/log/relatório;
- disponibilidade global calculada por compensação entre setores;
- fluxo clínico bloqueado por parcialidade de ocupação;
- arquivo de S2/S3 alterado ou mais de cinco arquivos tocados;
- `tasks.md` marcado antes de todas as evidências;
- relatório temporário ausente ou sem snippets por arquivo.

## Relatório obrigatório

Crie exatamente:

```text
/tmp/sirhosp-slice-SOPBR-S1-report.md
```

O relatório não pode conter dados reais e deve incluir:

1. `Status: COMPLETE` ou `Status: INCOMPLETE`;
2. resumo do slice;
3. `BASE_REF` e estado inicial;
4. matriz `R1..R10 → arquivos → testes/inspeções`;
5. baseline: comando, exit code, passed/failed/errors;
6. RED: comando, teste, falha esperada e exit code;
7. GREEN: comando e resumo;
8. arquivos alterados e justificativa;
9. snippets antes/depois por arquivo alterado;
10. migration e prova de ausência de backfill;
11. equação sintética de reconciliação;
12. checks `rg` com interpretação;
13. todos os gates com exit codes;
14. comparação baseline versus final;
15. respostas aos gates de autoavaliação;
16. riscos, limitações e pendências;
17. comandos exatos para rerun;
18. seção `Handoff para verificador` com checklist R1..R10.

Somente após tudo passar, marque tarefas 1.1 a 1.6, faça commit claro, push e
responda com `REPORT_PATH=/tmp/sirhosp-slice-SOPBR-S1-report.md`. Então pare.

## Prompt pronto para o implementador LLM

```text
Read AGENTS.md, PROJECT_CONTEXT.md and every artifact under
openspec/changes/separate-official-and-physical-bed-realities first, especially
slice-prompts/SLICE-SOPBR-S1.md. Start with zero assumed context.

Implement ONLY SOPBR-S1. Follow the DeepSeek4-Flash protocol literally: clean
state, BASE_REF, official containerized unit baseline before editing, real TDD
RED, minimal GREEN, controlled REFACTOR, mandatory rg inspections, all official
container gates, integration and baseline-vs-final evidence. Apply clean code,
DRY and YAGNI. Touch at most the five allowed files. Do not implement catalog
JSON/activation, views, template, ADR or future slices. Preserve v1/v2,
immutability, privacy, exact-run semantics and clinical processing.

If any required test/check/gate is missing or failing, pytest final has any
failure/error, passed_final is below baseline, privacy is uncertain, migration
is not additive, or file limit is exceeded, report INCOMPLETE, do not mark
tasks.md and do not commit/push.

Create /tmp/sirhosp-slice-SOPBR-S1-report.md with RED/GREEN evidence,
before/after snippets for every changed file, migration inspection, complete
quality-gate results, rerun commands, self-evaluation and Handoff para
verificador. Mark tasks 1.1-1.6 only after every criterion passes. Commit, push,
reply REPORT_PATH=/tmp/sirhosp-slice-SOPBR-S1-report.md and STOP.
```
