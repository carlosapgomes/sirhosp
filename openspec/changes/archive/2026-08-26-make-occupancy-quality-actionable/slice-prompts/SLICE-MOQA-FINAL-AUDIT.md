# MOQA-FINAL-AUDIT — Auditoria independente antes da release

## Handoff para implementador com contexto zero

Você executará a auditoria final, somente leitura, do change
`make-occupancy-quality-actionable` antes de qualquer release, deploy ou
ativação do catálogo v4. Assuma contexto zero e não confie apenas nos relatórios
dos implementadores.

Leia integralmente, nesta ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. `.gitignore` e `.markdownlint-cli2.yaml`;
3. todos os arquivos em
   `openspec/changes/make-occupancy-quality-actionable/`, incluindo este prompt,
   proposal, design, tasks, quatro delta specs e prompts S1–S3;
4. os três relatórios:
   - `/tmp/sirhosp-slice-MOQA-S1-report.md`;
   - `/tmp/sirhosp-slice-MOQA-S2-report.md`;
   - `/tmp/sirhosp-slice-MOQA-S3-report.md`;
5. as cinco specs canônicas afetadas pelo change anterior em `openspec/specs/`,
   com atenção às quatro modificadas pelo change atual;
6. o change arquivado em
   `openspec/changes/archive/2026-08-23-separate-official-and-physical-bed-realities/`;
7. ADR-0003, ADR-0004, ADR-0005, ADR-0006 e `docs/adr/README.md`;
8. todos os arquivos alterados pelos commits S1–S3, não apenas snippets dos
   relatórios.

Estado esperado no início:

- branch `master`, sincronizada com `origin/master`, árvore rastreada limpa;
- change atual com 17/25 tasks concluídas;
- S1: commit `d822b62`;
- S2: commit `783ec30`;
- S3: commit `b4c42c5`;
- implementation base: commit `742606f`;
- o commit `742606f` já sincronizou e arquivou
  `separate-official-and-physical-bed-realities`;
- nenhum catálogo v4 foi publicado ou ativado operacionalmente;
- produção ainda deve usar `occupancy-v3` até ativação futura explícita.

Não presuma que hashes abreviados bastam: resolva e registre SHAs completos.
Se o histórico divergir, pare como **INCOMPLETO**.

## Protocolo obrigatório para DeepSeek4-Flash

Este é um slice de auditoria independente, não de implementação. Portanto,
**não fabrique um ciclo RED/GREEN e não altere código para fazer a auditoria
passar**. O equivalente verificável é `BASELINE → INSPEÇÃO → GATES → VEREDITO`.
Uma divergência exige slice corretivo separado com TDD RED→GREEN→REFACTOR.

Siga literalmente:

1. Registre `AUDIT_BASE_REF=$(git rev-parse HEAD)`, `IMPLEMENTATION_BASE` e os
   SHAs completos S1/S2/S3.
2. Comprove branch, sincronização, árvore limpa, ancestralidade e presença dos
   três relatórios antes de auditar.
3. Monte no relatório a matriz
   `Requisito → artefato → código/teste → inspeção/gate` antes do veredito.
4. Leia código, migrations, JSON, testes, ADR e relatórios integralmente;
   resultados relatados sem evidência reproduzível não contam.
5. Não acessar produção, banco real, tmux/SSH, dados clínicos ou credenciais.
6. Não editar código, testes, migrations, JSON, specs, ADRs ou relatórios
   anteriores.
7. Execute todas as inspeções e gates deste prompt sem omitir falhas ambientais.
8. Qualquer comando obrigatório com exit diferente de zero torna o slice
   **INCOMPLETO**, inclusive HTTP 429 em integração; não aceite ressalva verbal.
9. Somente se tudo estiver verde, marque exclusivamente tasks 4.1, 4.2 e 4.3.
10. Gere relatório verificável e pare. Não executar task 4.4 nem preparar
    release.

## Objetivo do slice

Entregar um veredito binário e reproduzível sobre a prontidão da implementação
v4 para entrar no processo de release:

- **COMPLETE**: artefatos, código, testes, migrations, catálogo, ADR, histórico,
  privacidade e gates estão consistentes; tasks 4.1–4.3 podem ser marcadas;
- **INCOMPLETE**: existe qualquer divergência, omissão, falha ou evidência
  insuficiente; nenhuma task 4.1–4.3 é marcada e um slice corretivo é proposto.

A auditoria não publica release, não faz deploy e não ativa catálogo.

## Contexto técnico que deve ser confirmado

A implementação esperada abrange:

- migration 0022: qualidade da medição v4 e contador diário de ressalvas;
- `occupancy-v4`: deduplicação antes da classificação, conflitos tipados,
  reconciliação schema 2 sem PHI e elegibilidade diária com warning;
- migration 0023: `source_display_name` aditivo e sem backfill;
- catálogo integral v4 schema 3.0, algoritmo v4, aliases curados e totais
  43/48/47/39/4/666/666;
- `/beds`: dois resumos agregados, uma lista detalhada, componentes genéricos,
  “sistema de origem”, detalhes não autoritativos para todos os autenticados,
  exact-run e fallback histórico;
- ADR-0006 substituindo parcialmente a política da ADR-0005 sem reescrever
  v1–v3;
- fluxo clínico e gate mínimo de 40 setores preservados.

## Requisitos verificáveis

### R1 — Proveniência e escopo dos três slices

Comprovar:

- `742606f` é ancestral de S1, S2, S3 e `HEAD` na ordem declarada;
- cada commit toca apenas os arquivos permitidos pelo respectivo prompt;
- não existem mudanças não commitadas ou commits MOQA ocultos fora da cadeia;
- relatórios existem, declaram status, baseline, RED/GREEN, gates, snippets e
  handoff;
- contagens de arquivos dos relatórios coincidem com `git show`.

Não considerar o próprio prompt atual como arquivo de implementação.

### R2 — Consistência OpenSpec, ADR e tarefas

Construir uma matriz explícita ligando cada requisito das quatro delta specs a:

- decisão em proposal/design;
- implementação concreta;
- teste automatizado;
- ADR-0006 quando for decisão arquitetural;
- task S1, S2 ou S3 correspondente.

Confirmar que:

- não há requisito implementado sem especificação;
- não há requisito normativo sem implementação/teste;
- ADR-0006 preserva v1–v3 e substitui apenas decisões declaradas da ADR-0005;
- “sistema de origem”, acesso para todos os autenticados e lista detalhada única
  estão alinhados em todos os artefatos;
- não há promessa de backfill, ativação automática ou rollback funcional para
  v3.

### R3 — Domínio occupancy-v4 e resumo diário

Auditar código e testes para comprovar:

- dispatch depende do algoritmo persistido no catálogo;
- duplicata exata é consolidada antes da tipagem;
- precedência é status → idade particionada → ocupante;
- occupant conflict computa uma posição e não escolhe autoridade;
- status conflict não computa posição ambígua;
- age conflict particionado não atribui grupo arbitrário;
- ocupado sem posição não entra no numerador;
- unrated permanece fora da taxa sem virar warning por si só;
- duas pontes fecham e payload persistido possui allowlist agregada sem PHI;
- warning v4 continua elegível no resumo e incrementa contador próprio;
- v1/v2/v3 preservam elegibilidade histórica;
- disponibilidade e excedente continuam não compensados por grupo;
- fluxo clínico e gate de 40 não foram relaxados.

Toda afirmação deve citar função e teste específico.

### R4 — Models, migrations e imutabilidade

Confirmar:

- migrations 0022 e 0023 são aditivas;
- não há `RunPython`, backfill, alteração destrutiva ou edição de migration
  anterior;
- constraints e defaults representam estados históricos e v4 corretamente;
- medições, reconciliação, resumos e catálogos publicados continuam imutáveis;
- nenhuma idade exata, nome, prontuário, leito ou texto clínico foi adicionado a
  modelos agregados;
- nenhum scheduler, Celery, Redis ou serviço novo foi introduzido.

### R5 — Catálogo v4 e aliases

Comprovar no JSON e parser:

- schema 3.0 exige `source_display_name` e algoritmo explícito;
- schemas históricos continuam válidos sem alias e não aceitam reinterpretação;
- aliases divergentes para o mesmo código são rejeitados;
- código 654 usa o mesmo alias nas duas memberships;
- alias é curado, não inferido por regex em runtime;
- nome bruto permanece preservado em `configured_source_name`;
- dry-run informa cobertura sem escrita;
- totais são exatamente 43 grupos, 48 memberships, 47 códigos, 39 standard,
  quatro unrated e capacidades 666/666;
- CO e 3A mantêm a política publicada.

Hashes esperados dos arquivos, a confirmar com `sha256sum`:

- inicial:
  `7e346a74503d2ea797740bc8773d6a45702fed2e6aa0497f91c7d25e7f2a6bb3`;
- corrigido:
  `d11e26b349b84c7c8f369867348f0ad261c2a2cdfab51cb991055aca1dc27acc`;
- v3:
  `62298efb138af3b0ecec38974e6d2c922f4031a3304c932d230cebb5eb85455c`;
- v4:
  `141166289c296cb5982da3f145edddf576d15392303ba2d7aaf198ff4bfaf0f9`.

### R6 — `/beds`, autorização e privacidade

Comprovar por código, template e testes:

- dois resumos agregados e exatamente uma lista `Setores e posições`;
- nenhuma tab ou segunda lista longa;
- componentes 1↔1, 1↔N, N↔1, unrated e unmapped são genéricos, sem branches
  para 654/CO/Cardio;
- posição/capacidade não duplica em 3A, Cardio ou CO;
- alias limpo é primário e bruto é secundário;
- “sistema legado” não permanece na UI v4;
- alternativas de conflito são não autoritativas e nenhum first/last vence;
- usuário autenticado não-staff vê detalhes já autorizados;
- anônimo recebe 302;
- exact-run nunca reutiliza medição/alias antigo;
- ausência de medição exata preserva estado pendente;
- PHI detalhada é somente efêmera na renderização autenticada e não aparece em
  payload agregado, log, histórico ou relatório.

Use somente fixtures sintéticas. Não copie valores identificáveis para o
relatório de auditoria.

### R7 — Evidência independente dos gates

Reexecutar todos os gates oficiais. Não aceitar como substituto os resultados
dos relatórios S1–S3. Registrar comando, exit code e resumo.

Para testes unitários, registrar explicitamente `passed`, `failed=0`, `errors=0`
e exit 0. Para integração, qualquer falha externa ou rate limit mantém o slice
INCOMPLETO; não mascarar, rerodar seletivamente ou excluir teste.

### R8 — Arquivamento anterior e separação operacional

Comprovar:

- `openspec list --json` mostra somente o change atual ativo;
- diretório ativo do change anterior não existe;
- arquivo arquivado existe em `2026-08-23-...`;
- commit `742606f` sincronizou as cinco specs canônicas anteriores;
- task 4.3 estava apenas desatualizada no checklist, não pendente tecnicamente;
- não existe tag/release posterior criada por esta auditoria;
- não há ativação automática do catálogo v4, data operacional hardcoded,
  publicação em migration/startup ou escrita em banco.

## Arquivos permitidos e limite rígido

Durante a execução, o auditor pode **ler** qualquer arquivo necessário, mas pode
alterar no repositório somente:

1. `openspec/changes/make-occupancy-quality-actionable/tasks.md`, exclusivamente
   para marcar 4.1, 4.2 e 4.3 após veredito COMPLETE.

O relatório obrigatório fica em `/tmp` e não conta no limite.

O diretório ativo de OpenSpec é ignorado por `.gitignore`; não usar `git add -f`
e não criar commit vazio apenas para registrar checkboxes. As tasks serão
versionadas quando o change for arquivado em 4.8. Se houver qualquer outra
mudança rastreada ou ignorada criada pelo auditor, o slice é INCOMPLETO.

## Arquivos e ações proibidos

Não alterar:

- código, testes, migrations, JSONs, templates, ADRs ou specs;
- relatórios S1/S2/S3;
- `.gitignore` ou configuração de lint;
- Compose, workflows, release docs ou versão;
- produção, banco, catálogo publicado ou serviços.

Não:

- criar tag/release/imagem;
- fazer deploy, backup, SSH/tmux ou ativação;
- instalar dependências;
- editar task 4.4–4.8;
- arquivar o change atual;
- fazer commit vazio ou push sem alteração rastreada;
- corrigir divergência encontrada dentro deste slice.

## Método de verificação obrigatório

### BASELINE

Antes de qualquer decisão:

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/master
git log -8 --oneline --decorate
git merge-base --is-ancestor 742606f d822b62
git merge-base --is-ancestor d822b62 783ec30
git merge-base --is-ancestor 783ec30 b4c42c5
git merge-base --is-ancestor b4c42c5 HEAD
openspec list --json
openspec status --change make-occupancy-quality-actionable --json
```

Todos os `merge-base` devem retornar exit 0. `HEAD` e `origin/master` devem ser
iguais. Se a árvore estiver suja, pare sem limpar trabalho alheio.

### INSPEÇÃO

Auditar sem editar. Não existe RED/GREEN neste slice. Se for necessário alterar
um teste para provar um requisito, a evidência atual é insuficiente e o veredito
é INCOMPLETO.

### GATES

Executar somente depois da inspeção estrutural. Se a inspeção já detectar
bloqueio, ainda registre o máximo seguro possível, mas não masque o bloqueio.

### VEREDITO

Marcar 4.1–4.3 somente quando R1–R8 e todos os gates estiverem comprovados. Após
marcar, rerodar OpenSpec strict e Markdown lint e confirmar que não houve outra
mudança.

## Checks de inspeção obrigatórios

Execute e interprete cada bloco no relatório.

### Proveniência e escopo

```bash
for commit in d822b62 783ec30 b4c42c5; do
  git show --format=fuller --stat --summary "$commit"
  git diff-tree --no-commit-id --name-only -r "$commit"
done
git diff --check 742606f..HEAD
git diff --name-status 742606f..HEAD
for report in /tmp/sirhosp-slice-MOQA-S{1,2,3}-report.md; do
  test -s "$report" && printf 'FOUND %s\n' "$report"
done
```

### Domínio, histórico e privacidade

```bash
rg -n "occupancy-v4|quality_warning|reconciliation_schema_version|allowlist" \
  apps/census/models.py apps/census/occupancy.py \
  tests/unit/test_occupancy_measurement.py \
  tests/unit/test_process_census_snapshot.py
rg -n "occupancy-v1|occupancy-v2|occupancy-v3|_is_daily_eligible|MINIMUM_CENSUS_SECTORS|= 40" \
  apps/census tests/unit
rg -n "nome|prontuario|prontuário|idade_exata|exact_age|texto_clinico|clinical_text" \
  apps/census/models.py apps/census/occupancy.py
rg -n "RunPython|RemoveField|DeleteModel|AlterField" \
  apps/census/migrations/0022_*.py apps/census/migrations/0023_*.py
rg -n "Celery|Redis|scheduler|post_migrate|ready\(" apps/census
```

Ocorrências não são automaticamente falha: classifique cada uma. É falha se
PHI aparecer em payload/modelo agregado, migration for destrutiva/backfill ou
novo mecanismo operacional tiver sido introduzido.

### Catálogo e ativação separada

```bash
sha256sum apps/census/data/initial_sector_capacity_catalog.json \
  apps/census/data/corrected_sector_capacity_catalog.json \
  apps/census/data/sector_capacity_catalog_v3.json \
  apps/census/data/sector_capacity_catalog_v4.json
rg -n "source_display_name|configured_source_name|schema_version|occupancy-v4" \
  apps/census/capacity_catalog.py apps/census/models.py \
  apps/census/data/sector_capacity_catalog_v4.json
rg -n "source_code.*654|source_code.*719|source_code.*2156" \
  apps/census/data/sector_capacity_catalog_v4.json
rg -n "post_migrate|effective_from.*2026|timezone\.localdate\(\).*occupancy-v4|activate.*v4" \
  apps/census
```

Confirme totais pelo teste/parser existente; não criar script que publique.
Ausência de ativação automática é obrigatória.

### UI, exact-run e autorização

```bash
rg -n "@login_required|resolve_exact_measurement|build_units_presentation" \
  apps/census/views.py apps/census/occupancy.py
rg -n "Capacidade oficial e ocupação|Posições registradas no sistema de origem|Como as ocupações foram tratadas|Setores e posições" \
  apps/census/templates/census/bed_status.html
rg -n "sistema legado|Conflito no legado|data-bs-toggle=\"tab\"" \
  apps/census/templates/census/bed_status.html
rg -n "654|OBST-3A|Centro Obstétrico|ENF-2B-CARD" \
  apps/census/occupancy.py apps/census/views.py
rg -n "não autoritativo|duplicadas consolidadas|não computad|fora do escopo" \
  apps/census/templates/census/bed_status.html
rg -n "anonymous|non_staff|exact_run|pending|occupant_conflict|status_conflict|age_conflict" \
  tests/unit/test_bed_status_view.py
```

A busca de termos legados/tabs no template deve ser vazia. Códigos especiais não
podem controlar componentes em código de produção. Fixtures sintéticas em testes
podem citá-los.

### OpenSpec, ADR e arquivamento anterior

```bash
openspec list --json
test ! -d openspec/changes/separate-official-and-physical-bed-realities
test -d openspec/changes/archive/2026-08-23-separate-official-and-physical-bed-realities
git show --stat --oneline 742606f
rg -n "occupancy-v4|sistema de origem|autenticad|ADR-0005|sem backfill|futura" \
  docs/adr/ADR-0006-*.md docs/adr/README.md \
  openspec/changes/make-occupancy-quality-actionable
rg -n "^- \[[ x]\] 4\.[1-8]" \
  openspec/changes/make-occupancy-quality-actionable/tasks.md
```

## Gates oficiais obrigatórios

Executar todos, mesmo que pareçam redundantes:

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

Regras binárias:

- cada comando deve ter exit 0;
- unit deve registrar zero failures/errors e contagem de passed;
- integração não pode ter failure/error/429 aceito como ressalva;
- não usar execução host-only como substituto;
- não pular gate por ter passado em S1/S2/S3;
- após marcar tasks 4.1–4.3, rerodar os dois últimos comandos.

## Critérios de sucesso binários

- [ ] Branch, HEAD/origin e árvore inicial comprovados.
- [ ] Cadeia 742606f→S1→S2→S3→HEAD comprovada.
- [ ] Escopo de arquivos de cada slice coincide com seu prompt/relatório.
- [ ] Três relatórios completos e verificáveis, sem dados reais.
- [ ] Matriz delta spec→design→código→teste→ADR sem gaps.
- [ ] Semântica v4 e duas reconciliações fechadas comprovadas.
- [ ] Warning v4 elegível e história v1–v3 preservada.
- [ ] Gate de 40 e fluxo clínico preservados.
- [ ] Migrations 0022/0023 aditivas, sem backfill.
- [ ] Nenhum PHI em histórico, payload agregado ou relatório.
- [ ] Hashes dos quatro JSONs exatamente iguais aos esperados.
- [ ] Totais v4 exatamente 43/48/47/39/4/666/666.
- [ ] Alias curado/versionado sem regex runtime.
- [ ] `/beds` tem dois resumos e uma lista, sem duplicação.
- [ ] Autenticação, non-staff, exact-run e pending comprovados.
- [ ] ADR-0006 consistente e ADR-0005 historicamente preservada.
- [ ] Change anterior sincronizado/arquivado pelo commit 742606f.
- [ ] Nenhuma release, deploy, escrita ou ativação executada.
- [ ] Todos os gates oficiais retornaram exit 0.
- [ ] Somente tasks 4.1–4.3 foram marcadas.
- [ ] Relatório final completo e sanitizado criado.

## Gates de autoavaliação

Responda objetivamente no relatório:

1. Qual requisito normativo tem a evidência mais fraca e por quê?
2. Os relatórios S1–S3 foram confirmados por rerun ou apenas aceitos?
3. Algum commit tocou arquivo fora do limite do prompt correspondente?
4. Como se prova que occupant conflict não escolhe autoridade?
5. Como se prova que warnings v4 entram no resumo sem reinterpretar v3?
6. Quais campos fecham as duas pontes de reconciliação?
7. Quais hashes e totais comprovam imutabilidade/integridade dos catálogos?
8. Como os componentes de UI evitam hardcode e dupla contagem?
9. Qual teste comprova acesso non-staff e qual comprova 302 anônimo?
10. Onde se comprova exact-run sem alias/measurement antigo?
11. Há qualquer PHI em persistência agregada, log ou relatório?
12. Todos os gates, inclusive integração, passaram sem ressalva?
13. Como o commit 742606f comprova task 4.3?
14. Qual evidência prova que v4 ainda não foi ativado?
15. O auditor modificou algo além dos três checkboxes permitidos?

### Condições automáticas de INCOMPLETO

O slice é INCOMPLETO se ocorrer qualquer item:

- árvore inicial suja, branch incorreta ou `HEAD != origin/master`;
- cadeia de commits ou relatórios ausente/inconsistente;
- matriz R1–R8 incompleta;
- relatório anterior aceito sem inspeção independente;
- divergência entre OpenSpec, ADR, código, migration, JSON ou teste;
- requisito crítico sem teste/inspeção reproduzível;
- hash ou total de catálogo divergente;
- alteração/backfill destrutivo ou ativação automática;
- quebra/ambiguidade em v1–v3, gate 40, exact-run ou fluxo clínico;
- posição/capacidade duplicada ou conflito com autoridade implícita;
- detalhe restrito a staff quando deveria atender todo autenticado;
- PHI em histórico agregado, reconciliação, log ou relatório;
- qualquer gate obrigatório omitido ou com exit diferente de zero;
- teste final com failure/error;
- integração com HTTP 429 ou outra falha, mesmo ambiental;
- execução host-only usada como gate oficial;
- código/teste/spec/ADR/JSON/migration alterado pelo auditor;
- task 4.4–4.8 marcada;
- release, deploy, banco, produção ou ativação acessados;
- `git add -f`, commit vazio ou archive do change atual;
- relatório temporário ausente ou não sanitizado.

Em caso INCOMPLETO:

1. não marque 4.1, 4.2 ou 4.3;
2. não corrija dentro deste slice;
3. descreva a causa raiz e o menor slice corretivo possível;
4. liste testes RED necessários para a correção;
5. pare sem commit/push.

## Relatório obrigatório

Criar exatamente:

```text
/tmp/sirhosp-slice-MOQA-FINAL-AUDIT-report.md
```

O relatório deve conter:

1. `Status: COMPLETE` ou `Status: INCOMPLETE`;
2. `AUDIT_BASE_REF`, `IMPLEMENTATION_BASE` e SHAs completos S1/S2/S3;
3. estado de branch, origin, árvore e OpenSpec;
4. matriz R1–R8 com artefato, código, teste e evidência;
5. tabela de escopo por commit: permitido, observado, veredito;
6. avaliação crítica dos três relatórios, inclusive ressalvas de integração;
7. snippets relevantes de auditoria, sem dados identificáveis;
8. hashes e totais dos catálogos;
9. inspeção de migrations/imutabilidade/privacidade;
10. inspeção de domínio, resumo diário, UI, autorização e exact-run;
11. evidência do arquivamento anterior;
12. comandos, exit codes e resumos de todos os gates;
13. confirmação explícita de `failed=0`, `errors=0` e exit 0 onde aplicável;
14. respostas aos 15 gates de autoavaliação;
15. arquivos alterados pelo auditor;
16. riscos, pendências e próximo passo permitido;
17. comandos exatos de rerun;
18. seção `Handoff para verificador` com checklist R1–R8.

Não incluir nomes, prontuários, leitos, idades exatas, conteúdo clínico,
credenciais, dumps, screenshots ou saídas reais de produção.

Se COMPLETE, marcar 4.1–4.3, confirmar que 4.4–4.8 continuam desmarcadas, não
criar commit vazio, responder:

```text
REPORT_PATH=/tmp/sirhosp-slice-MOQA-FINAL-AUDIT-report.md
```

Depois, **STOP**. Não iniciar release.

## Prompt pronto para implementador LLM

```text
Read AGENTS.md, PROJECT_CONTEXT.md and
openspec/changes/make-occupancy-quality-actionable/slice-prompts/SLICE-MOQA-FINAL-AUDIT.md
first, then read every context artifact and all three MOQA reports listed there.
Assume zero prior context.

Execute ONLY the independent MOQA final audit for tasks 4.1-4.3. This is a
read-only verification slice: do not manufacture RED/GREEN and do not fix code.
Use BASELINE -> INSPECTION -> GATES -> VERDICT. Apply clean, DRY and YAGNI
reasoning to evaluate the implementation. Independently map every normative
requirement to design, code, test and ADR evidence; inspect the full commits,
migrations, catalog, UI, privacy, exact-run and historical behavior.

Run every mandatory official container gate, integration, strict OpenSpec and
global Markdown lint. Any missing command, nonzero exit, test failure/error,
HTTP 429, hash/total drift, scope violation, PHI concern or evidence gap makes
the slice INCOMPLETE. Do not accept prior reports as substitutes. On
INCOMPLETE, do not edit or mark tasks; propose the smallest separate corrective
TDD slice and STOP.

Do not access production, SSH/tmux or a real database. Do not publish, deploy,
activate, archive the current change, create a tag, edit application/spec/ADR
files, use git add -f or create an empty commit. The only permitted repository
edit on COMPLETE is marking tasks 4.1, 4.2 and 4.3; leave 4.4-4.8 unchecked.

Create /tmp/sirhosp-slice-MOQA-FINAL-AUDIT-report.md with full reproducible
evidence, exit codes, zero-failure summaries, sanitized snippets, requirement
matrix, self-evaluation and Handoff para verificador. If COMPLETE, reply with
REPORT_PATH and STOP before release.
```
