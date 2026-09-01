# PFIF-S4 — Rótulos em `/beds` e admissões

## Handoff para implementador LLM com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md` e todo o change;
2. relatórios COMPLETE de PFIF-S1–S3, diff S3 e API pública do classificador;
3. `apps/census/views.py::bed_status_view` e
   `apps/census/occupancy.py` somente para mapear os shapes v1–v5;
4. todos os blocos de paciente em
   `apps/census/templates/census/bed_status.html`;
5. `apps/patients/views.py::admission_list_view` e
   `apps/patients/templates/patients/admission_list.html`;
6. template tags existentes e testes de `/beds`, admission page, autorização,
   v5 query budget e conflitos.

Pré-condição: S3 entrega um mapa bulk único e `/censo` já está verde. Este slice
somente consome esse serviço nas duas superfícies restantes. Não altere regras,
códigos, prioridade, source extraction, health ou metrics.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Se qualquer item falhar: INCOMPLETE, sem tasks/commit/push.

1. BASE_REF/árvore limpa, S1–S3 verificados e matriz requisito→arquivo→teste.
2. Baselines oficiais unit e integration com exit/resumo; falha bloqueia.
3. RED primeiro para `/beds` v5/histórico, admissões com/sem Admission, manual
   review, auth e query budget.
4. GREEN mínimo em no máximo seis arquivos.
5. REFACTOR local clean/DRY/YAGNI; helper de template só faz lookup/render, sem
   ORM ou regra clínica.
6. Inspeções e todos os gates.
7. Unit/integration finais exit zero, zero failures/errors e passed >= baseline.
8. Relatório completo e handoff para terceiro verificador.

## Objetivo vertical

O mesmo finding já visto em `/censo` aparece, com semântica idêntica, em toda
linha aplicável de paciente em `/beds` e no banner/conteúdo da página de
admissões. Medição oficial, conflitos, autorização e número de queries não
mudam.

## Requisitos funcionais

### R1 — Mapa bulk em `/beds`

`bed_status_view` deve coletar os patient ids/registros presentes na fotografia
mais recente e chamar o serviço S3 uma vez. Passar mapa ao template sem alterar
`build_units_presentation`, measurement ou reconciliation persistida, salvo se
inspeção provar impossível; nesse caso pare e reporte, não edite occupancy.py
fora da lista.

### R2 — Cobertura dos shapes de paciente

Renderizar badge nos patient items v5 e nas apresentações históricas/physical
que possuem patient id/registro. Cobrir posições normais, sem leito e listas de
qualidade aplicáveis. Em alternativas de conflito, o badge pertence ao paciente
mas não escolhe alternativa autoritativa nem altera contagem.

### R3 — Admission page com e sem Admission

`admission_list_view` chama o classificador para um único paciente pelo mesmo
contrato bulk. A página mostra finding mesmo quando `admissions` está vazio e
também junto da Admission selecionada. `requires_manual_review` recebe warning
textual explícito; suspected residual nunca diz alta confirmada.

### R4 — Helper de template mínimo

Se lookup dinâmico for necessário, criar filter/tag em `apps/core/templatetags`
que somente obtém chave de mapping e/ou renderiza classes allowlisted. Proibido
importar models, acessar ORM, calcular idade/48h/setor ou duplicar labels.

### R5 — Autorização e contratos oficiais preservados

`login_required`, links, expansão, collapse, conflitos e terminologia v1–v5
permanecem. Findings não entram em OccupancyMeasurement, daily summary,
physical reconciliation, logs ou export. Nenhum novo endpoint.

### R6 — Query budget

O número de queries adicionais é constante para catálogos/pacientes de tamanhos
diferentes. Reutilizar mapa na template inteira; nenhuma query em loops.

### R7 — Regressão cruzada

Teste prova mesmo `code/label/review` em `/censo`, `/beds` e admission page para
a mesma fixture sintética, sem acoplar HTML exato além dos badges necessários.

## Arquivos esperados e limite

Máximo de **6 arquivos**, além de `tasks.md`:

1. `apps/core/templatetags/patient_flow.py` (novo, se necessário);
2. `apps/census/views.py`;
3. `apps/census/templates/census/bed_status.html`;
4. `apps/patients/views.py`;
5. `apps/patients/templates/patients/admission_list.html`;
6. `tests/integration/test_patient_flow_findings_surfaces.py` (novo).

Se o filter não for necessário, não crie. Não editar `occupancy.py`, models,
migrations, classificador S3, services portal, extraction, metrics, health, URLs
ou docs. Se o shape exigir `occupancy.py`, pare e reporte bloqueio com inspeção;
o planner decidirá emenda de escopo.

## TDD obrigatório

### RED

1. v5 patient item mostra informational finding sem alterar official metrics;
2. patient sem leito mostra finding;
3. apresentação histórica/physical mostra finding;
4. conflito mostra finding sem rótulo autoritativo novo;
5. `/beds` none não cria placeholder;
6. admission page sem Admission mostra recent/newborn;
7. admission selecionada mostra recent/residual e manual review;
8. residual não contém afirmação de alta confirmada;
9. anonymous continua 302/login nas duas páginas;
10. same fixture tem mesmo label nas três superfícies;
11. query count `/beds` pequeno/grande dentro de allowance fixo;
12. nenhuma gravação de measurement/finding.

Pelo menos um RED por superfície.

Além do RED, inclua um teste de caracterização (passa desde o início; não
conta como RED): RN 0–4 dias no censo com Admission encerrada
(`discharge_date` preenchida) mantém o finding `newborn_waiting_registration`
— fixa em nível DB a leitura "sem internação ativa" do design.md D5 sem
alterar o classificador.

### GREEN

Consumir o mapa S3 minimamente; templates só apresentam.

### REFACTOR

Remover markup duplicado com include apenas se reduzir arquivos/complexidade e
couber no limite. Não reestruturar template de 1.000 linhas, occupancy ou patient
view além do necessário.

## Checks de inspeção obrigatórios

```bash
rg -n "patient_flow|finding|requires_manual_review" \
  apps/census/views.py apps/census/templates/census/bed_status.html \
  apps/patients/views.py apps/patients/templates/patients/admission_list.html \
  apps/core/templatetags/patient_flow.py
rg -n "objects\.|from apps\..*models|date_of_birth|timedelta|48" \
  apps/core/templatetags/patient_flow.py \
  apps/census/templates/census/bed_status.html \
  apps/patients/templates/patients/admission_list.html
rg -n "login_required" apps/census/views.py apps/patients/views.py
rg -n "measurement|occupancy|official|conflict|não autoritativo|sem leito" \
  tests/integration/test_patient_flow_findings_surfaces.py
rg -n "alta confirmada|alta hospitalar confirmada" \
  apps/census/templates/census/bed_status.html \
  apps/patients/templates/patients/admission_list.html
git diff --check
git diff --stat
```

Se filter opcional não existir, registre comando ajustado sem mascarar erro.
Interprete: nenhum ORM/regra em template tag; auth presente; occupancy.py fora
do diff; badge não altera autoridade/aritmética.

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

## Critérios binários de sucesso

- [ ] S1–S3 verificados e classificador inalterado.
- [ ] R1–R7 RED/GREEN.
- [ ] V5, histórico, sem leito e caso de qualidade cobertos.
- [ ] Admission page funciona com/sem Admission.
- [ ] Manual review explícito sem alta confirmada.
- [ ] Mesma semântica nas três páginas.
- [ ] Auth/occupancy/conflicts/query budget preservados.
- [ ] Máximo seis arquivos + tasks; occupancy.py não tocado.
- [ ] Gates/baselines finais verdes.

### Condições automáticas de INCOMPLETO

S3 não verificado/alterado; baseline/RED/gate ausente; apenas uma superfície
implementada; shape v5/histórico ignorado; template/tag consulta ORM ou
classifica; occupancy.py/model/migration/status muda; conflict vira autoritativo;
texto confirma alta; auth relaxa; N+1/query regression; arquivo extra; teste
removido/enfraquecido; relatório/tasks incorretos.

## Gates de autoavaliação

1. Quais testes cobrem cada shape de paciente em `/beds`?
2. Como o mapa único é reutilizado sem query em loop?
3. Qual teste prova finding quando não há Admission?
4. Como conflito/official metrics permanecem invariantes?
5. Qual prova de autorização foi executada?
6. O helper opcional contém somente lookup? Mostre inspeção.
7. Por que cada arquivo alterado foi necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-PFIF-S4-report.md` com Status, BASE_REF, provas S1–S3,
matriz, baselines, RED/GREEN, snippets antes/depois por arquivo, shapes cobertos,
query counts, inspeções, finais versus baselines, gates, arquivos/justificativa,
riscos, respostas e `Handoff para verificador` R1–R7/reruns. Sem PHI.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full recognize-patient-flow-findings change, verified PFIF-S1..S3 reports and SLICE-PFIF-S4.md. Implement ONLY PFIF-S4. Follow the DeepSeek4-Flash protocol: clean official baselines, real RED for both pages and /beds shapes, minimal GREEN, local clean-code/DRY/YAGNI refactor, query proof, inspections and all official gates. Reuse S3 classifier unchanged to render identical findings on /beds and patient admissions, including no-admission/manual-review cases, while preserving auth, exact occupancy and conflict authority. Touch at most six listed files plus tasks; do not edit occupancy.py unless you stop and report a blocker. Create /tmp/sirhosp-slice-PFIF-S4-report.md with per-file before/after and verifier handoff. Missing/failing means INCOMPLETE without tasks/commit. If complete mark only 4.1–4.5, commit, push, reply REPORT_PATH=..., then STOP.
```
