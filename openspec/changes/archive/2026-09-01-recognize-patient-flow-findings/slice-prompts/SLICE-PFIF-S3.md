# PFIF-S3 — Classificador bulk e rótulos em `/censo`

## Handoff para implementador LLM com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md` e todo o change;
2. relatório COMPLETE de PFIF-S1, avaliação que reprovou S2, relatório COMPLETE
   e aprovado de PFIF-S2R e commits correspondentes verificados;
3. contrato de snapshot, enums e stage details entregues por S1/S2 e corrigidos
   pelo gate S2R;
4. `apps/patients/models.py`, `apps/census/models.py`,
   `apps/clinical_docs/models.py` e `apps/ingestion/models.py`;
5. `_build_censo_context`/`censo` em `apps/services_portal/views.py`;
6. `apps/services_portal/templates/services_portal/censo.html`, layouts desktop
   e mobile;
7. testes de `/censo`, autenticação, filtros, export e query count.

Pré-condição: S2R foi aprovado por terceiro LLM e os dois workers produzem
outcome equivalente com navegação clássica comprovada por fake stateful. Sem
essa evidência, pare como INCOMPLETE. Hoje não existe serviço único de findings;
`/censo` conhece snapshots e patient ids, mas nenhum rótulo. Implemente somente
classificador + `/censo`; `/beds`, admissões, health/métricas pertencem a slices
futuros.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Qualquer item ausente/falho implica INCOMPLETE, sem task/commit/push.

1. BASE_REF, árvore limpa, S1 e S2R aprovados, reprovação original de S2
   registrada e matriz requisito→arquivo→teste.
2. Baselines oficiais `./scripts/test-in-container.sh unit` e `integration`, com
   exit/resumo; qualquer failure/error bloqueia.
3. RED funcional primeiro para prioridades, auto-resolução, query budget e
   badges desktop/mobile.
4. GREEN mínimo em no máximo quatro arquivos.
5. REFACTOR local: serviço puro/coeso, bulk, clean code, DRY, YAGNI; templates
   sem regra clínica.
6. Inspeções e todos os gates oficiais.
7. Unit/integration finais exit zero, zero failures/errors e passed não menor
   que respectivos baselines.
8. Relatório evidencial com handoff para terceiro LLM.

## Objetivo vertical

Com fixtures sintéticas de censo, demographics, admissions, events, runs e
stages, `/censo` mostra o finding correto na row desktop e card mobile, mantém o
eixo técnico independente, remove rótulo quando a evidência deixa de valer e
não aumenta queries conforme pacientes crescem.

## Requisitos funcionais

### R1 — DTO e códigos fechados

Criar um serviço bulk em `apps.ingestion.patient_flow_findings` (ou nome exato
equivalente) que recebe os pacientes/registros atuais e retorna mapa por patient
id ou registro. Cada finding expõe somente `code`, `label`, `severity` e
`requires_manual_review`. Definir códigos fechados:

- `recent_encounter_without_admission`;
- `newborn_waiting_registration`;
- `possible_newborn_companion`;
- `recent_admission_awaiting_first_evolution`;
- `suspected_legacy_residual`.

Sem model/migration/JSON livre.

### R2 — Prioridade determinística

Aplicar ordem do design D5 e no máximo um finding primário por paciente.

1. outcome recente mais novo, se nenhuma Admission posterior apareceu;
2. nascimento 0–4 dias e sem Admission;
3. nascimento 5–28 dias, sem Admission e setor fonte Obstetrícia 3A;
4. Admission atual <48h e sem events;
5. Admission ativa >=48h, paciente no censo atual, sem event nas últimas 48h.

Datas usam timezone-aware `now` injetável. DOB ausente/futura não classifica RN.
Setor isolado não cria finding. Suspeita residual não afirma alta.

### R3 — Eixo técnico preservado

O serviço não altera run/batch e não filtra `failure_reason`. Um paciente pode
ter finding e timeout simultaneamente. Um evento posterior ou Admission nova
deve remover/sobrescrever finding obsoleto na próxima avaliação.

### R4 — Bulk e orçamento fixo

Resolver pacientes, última Admission, existência/último event, último outcome
allowlisted e setor atual em conjunto. Proibido query em loop. Testar query
count com coortes de tamanhos diferentes e pequena tolerância fixa.

### R5 — Integração `/censo`

Adicionar finding ao dict de cada paciente em `_build_censo_context`. Renderizar
badge no `<tr>` desktop e card mobile; warning acessível quando
`requires_manual_review`. Sem placeholder para none. Template não importa model
nem classifica.

### R6 — Contratos preservados

Autenticação, busca, setor, especialidade, ordenação, links e patient count
permanecem. `censo_export_xlsx` reutiliza contexto sem adicionar finding ao
workbook/headers. Se necessário, evitar custo do classificador no export por
opção explícita e testada, sem duplicar filtros.

### R7 — Privacidade

Nenhum log/report/output novo contém identificador, nome, DOB, encounter date,
profissional ou clinical text. Labels são constantes. Fixtures sintéticas.

## Arquivos esperados e limite

Máximo de **4 arquivos**, além de `tasks.md`:

1. `apps/ingestion/patient_flow_findings.py` (novo);
2. `apps/services_portal/views.py`;
3. `apps/services_portal/templates/services_portal/censo.html`;
4. `tests/integration/test_censo_patient_flow_findings.py` (novo consolidado).

Não editar models/migrations, arquivos de S1/S2/S2R, `/beds`, patients
views/templates, health, métricas, XLSX library, URLs ou docs. Se orçamento
exigir índice/migration, pare e reporte; não antecipe.

## TDD obrigatório

### RED

1. cada código/label/severity/review com now sintético;
2. prioridades em pacientes que satisfazem mais de uma regra;
3. DOB futura/ausente, setor isolado e Admission com evento não rotulam;
4. outcome antigo superado por Admission posterior;
5. timeout continua intacto no DB e pode coexistir;
6. residual exige censo+ativa+>=48h+sem evento recente;
7. desktop e mobile exibem mesmo badge;
8. none não cria placeholder;
9. filtros/links/auth/export headers preservados;
10. query count coorte pequena versus maior sem N+1.

Pelo menos um teste RED deve falhar por ausência do classificador e um por UI.

### GREEN

Implementar R1–R7 minimamente, sem persistência de findings.

### REFACTOR

Separar consulta bulk de regras puras somente se couber no mesmo módulo. Evitar
abstração repository/rule engine/config genérico. Não colocar ORM em template.

## Checks de inspeção obrigatórios

```bash
rg -n "recent_encounter_without_admission|newborn_waiting_registration|possible_newborn_companion|recent_admission_awaiting_first_evolution|suspected_legacy_residual" \
  apps/ingestion/patient_flow_findings.py \
  tests/integration/test_censo_patient_flow_findings.py
rg -n "for .*objects|objects.*for|\.objects\." \
  apps/ingestion/patient_flow_findings.py \
  apps/services_portal/templates/services_portal/censo.html
rg -n "finding|requires_manual_review" \
  apps/services_portal/views.py \
  apps/services_portal/templates/services_portal/censo.html
rg -n "censo_export_xlsx|headers|Registro|Especialidade" \
  apps/services_portal/views.py \
  tests/integration/test_censo_patient_flow_findings.py
rg -n "login_required" apps/services_portal/views.py
git diff --check
git diff --stat
```

Interpretar: confirmar regra apenas no serviço, nenhuma query no template/loop,
mesmos labels desktop/mobile, export sem coluna e autorização preservada.

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

- [ ] S1 e S2R aprovados; arquivos de S1/S2/S2R inalterados.
- [ ] R1–R7 RED/GREEN.
- [ ] Cinco findings e prioridade exata.
- [ ] Timeout/run/batch não alterados.
- [ ] Auto-resolução provada.
- [ ] Query budget fixo sem template query.
- [ ] Desktop/mobile iguais; auth/filtros/links/export preservados.
- [ ] Sem model/migration/PHI.
- [ ] Máximo quatro arquivos + tasks.
- [ ] Gates e baseline/final verdes.

### Condições automáticas de INCOMPLETO

S1 ou S2R não aprovados; reprovação original de S2 ignorada;
baseline/RED/gate ausente; mais de um finding primário sem
requisito; setor sozinho rotula; residual vira alta confirmada; timeout/run é
reescrito; query em loop/N+1; template classifica/consulta; export muda; auth
relaxa; model/migration aparece; arquivo extra; teste removido/enfraquecido;
relatório sem evidência; tasks prematuras.

## Gates de autoavaliação

1. Qual teste prova cada prioridade e exclusão?
2. Como latest outcome é superado por Admission posterior?
3. Qual comparação de query count prova bulk?
4. Onde se prova coexistência com timeout?
5. Como XLSX permanece byte/shape contratualmente igual?
6. Por que cada arquivo é necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-PFIF-S3-report.md` com Status, BASE_REF, provas de S1
e S2R aprovados, registro da reprovação S2, matriz, baselines unit/integration,
RED/GREEN, tabela de cenários/prioridades,
query counts, snippets antes/depois por arquivo, inspeções, finais versus
baselines, gates, arquivos/justificativa, riscos, respostas e `Handoff para
verificador` R1–R7 com reruns. Sem dados reais.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full recognize-patient-flow-findings change, the rejected PFIF-S2 evaluation, verified PFIF-S1/PFIF-S2R reports and SLICE-PFIF-S3.md. If PFIF-S2R lacks third-party approval, report INCOMPLETE and stop. Implement ONLY PFIF-S3. Follow the DeepSeek4-Flash protocol with clean official unit/integration baselines, real RED, minimal GREEN, local clean-code/DRY/YAGNI refactor, query-count proof, inspections and every official gate. Build one bulk non-persistent classifier with the exact priority/codes and integrate only /censo desktop+mobile while preserving auth, filters, links and XLSX. Never rewrite technical failures or add model/migration. Touch at most four listed files plus tasks. Create /tmp/sirhosp-slice-PFIF-S3-report.md with before/after and verifier handoff. Any missing/failing item is INCOMPLETE without task mark/commit. If complete mark only 3.1–3.5, commit, push, reply REPORT_PATH=..., then STOP.
```
