# CIPOO-S2 — Catálogo integral occupancy-v5

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md`;
2. todos os artefatos de
   `openspec/changes/count-identified-patients-for-official-occupancy/`;
3. relatório `/tmp/sirhosp-slice-CIPOO-S1-report.md` e diff/commit S1;
4. `apps/census/capacity_catalog.py` e comando de ativação;
5. os quatro JSONs de catálogo existentes;
6. `tests/unit/test_sector_capacity_catalog.py`;
7. migrations/model/occupancy alterados em S1.

S1 deve estar completo, em `origin/master`, e fornecer dispatch v5. Este slice
entrega um documento integral validável/publicável, mas não publica em produção,
não altera UI e não cria nova migration.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Se qualquer item falhar: `INCOMPLETE`, não marque tasks, não commit/push.

1. Registre `BASE_REF`, árvore limpa e matriz requisito→arquivo→teste.
2. Rode baseline oficial `./scripts/test-in-container.sh unit` em container e
   registre exit/resumo. Falha bloqueia.
3. Testes RED primeiro; ao menos um deve falhar porque v5/documento ainda não é
   aceito, não por erro incidental.
4. GREEN mínimo em no máximo três arquivos.
5. REFACTOR apenas parsing/allowlist já existente; clean code, DRY, YAGNI.
6. Execute hash/JSON/inspeções, integração e todos os gates oficiais.
7. Final deve ter exit 0, zero failures/errors e passed >= baseline.
8. Relatório completo, tasks S2, commit/push e STOP somente após tudo verde.

## Objetivo vertical

Permitir que o operador valide e publique atomicamente um catálogo integral
`occupancy-v5` por uma data futura, com totais e aliases observáveis, mantendo
todos os documentos anteriores byte-preservados.

## Requisitos funcionais

### R1 — Allowlist explícita

`occupancy-v5` deve ser suportado somente porque existe implementação S1 e está
na allowlist. Algoritmo desconhecido continua rejeitado antes de escrita.

### R2 — Documento integral

Criar `apps/census/data/sector_capacity_catalog_v5.json` a partir da estrutura
v4, alterando somente contexto de versão/fonte/algoritmo necessário. Preservar:

- 43 grupos;
- 48 memberships;
- 47 códigos distintos;
- 39 standard e quatro unrated;
- capacidade conhecida/calculável 666/666;
- aliases 48/48;
- CO com cinco códigos, unrated e capacidade null;
- 3A Adulto 32/`age_12_or_over` e Infantil 16/`under_12`;
- Cardio e relações N:M;
- nenhum indicador combinado 3A total.

### R3 — Artefatos anteriores imutáveis

Hashes de initial, corrected, v3 e v4 devem permanecer exatamente os registrados
nos testes. Nenhum desses arquivos pode ser formatado ou reordenado.

### R4 — Dry-run observável sem escrita

Resultado deve informar `created=False`, algoritmo v5, hash próprio, totais,
políticas e aliases 48/48. Snapshot de versões/grupos/memberships antes/depois
idêntico.

### R5 — Publicação futura atômica e idempotente

Teste sintético publica v5 para data estritamente futura, persiste algoritmo,
43/48 e aliases. Retry do mesmo hash/data é no-op; hash diferente na mesma data,
data atual/passada e JSON inválido não escrevem parcialmente.

### R6 — Separação operacional

Nenhuma migration, startup, fixture ou teste importa/publica v5 automaticamente.
Não ativar produção nem criar release neste slice.

## Arquivos esperados e limite

Exatamente ou no máximo **3 arquivos rastreados**:

1. `apps/census/capacity_catalog.py`;
2. `apps/census/data/sector_capacity_catalog_v5.json`;
3. `tests/unit/test_sector_capacity_catalog.py`.

Não tocar modelos, migrations, occupancy.py, templates, docs, catálogos
anteriores ou produção. Se isso for necessário, pare e reporte bloqueio.

## TDD obrigatório

### RED

Antes do JSON/allowlist, adicionar testes para:

1. v5 reconhecido somente na allowlist implementada;
2. documento esperado e hash próprio;
3. totais 43/48/47/39/4/666/666 e aliases 48/48;
4. equivalência estrutural v4↔v5 exceto versão/fonte/algoritmo;
5. hashes byte a byte dos quatro anteriores;
6. CO, 3A, Cardio e aliases;
7. dry-run sem rows;
8. publicação/round-trip/idempotência/conflito/data inválida.

Rode suíte unitária e registre failure funcional esperado.

### GREEN

Adicionar allowlist e JSON mínimos. Não criar schema novo se schema 3.0 já
expressa aliases e algoritmo. Não mudar o output do comando além do necessário
para cobertura já disponível via resultado/serviço.

### REFACTOR

Eliminar somente duplicação introduzida nos testes. Não criar gerador de
catálogo, factory genérica ou migração de dados: YAGNI.

## Checks de inspeção obrigatórios

```bash
sha256sum \
  apps/census/data/initial_sector_capacity_catalog.json \
  apps/census/data/corrected_sector_capacity_catalog.json \
  apps/census/data/sector_capacity_catalog_v3.json \
  apps/census/data/sector_capacity_catalog_v4.json \
  apps/census/data/sector_capacity_catalog_v5.json
rg -n 'occupancy-v5|ALLOWED_ALGORITHM' apps/census/capacity_catalog.py \
  tests/unit/test_sector_capacity_catalog.py
rg -n '"stable_key"|"source_code"|"source_display_name"|"age_selector"' \
  apps/census/data/sector_capacity_catalog_v5.json
rg -n 'activate_sector_capacity_catalog|RunPython|post_migrate|ready\(' \
  apps/census apps/census/data/sector_capacity_catalog_v5.json
```

No relatório, compare hashes anteriores com:

```text
initial   7e346a74503d2ea797740bc8773d6a45702fed2e6aa0497f91c7d25e7f2a6bb3
corrected d11e26b349b84c7c8f369867348f0ad261c2a2cdfab51cb991055aca1dc27acc
v3        62298efb138af3b0ecec38974e6d2c922f4031a3304c932d230cebb5eb85455c
v4        141166289c296cb5982da3f145edddf576d15392303ba2d7aaf198ff4bfaf0f9
```

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate count-identified-patients-for-official-occupancy --strict
./scripts/markdown-lint.sh
```

## Critérios binários de sucesso

- [ ] S1 confirmado completo e baseline verde.
- [ ] RED real e GREEN documentados.
- [ ] V5 permitido e desconhecidos rejeitados.
- [ ] JSON v5 tem todos os totais/políticas/aliases aprovados.
- [ ] V4↔v5 difere somente no contexto permitido.
- [ ] Quatro hashes anteriores idênticos.
- [ ] Dry-run zero escrita.
- [ ] Publicação sintética atômica/idempotente.
- [ ] Nenhuma ativação automática/produção.
- [ ] Três arquivos no máximo e todos os gates verdes.

### Condições automáticas de INCOMPLETO

- S1 incompleto ou árvore suja não explicada;
- baseline/RED/gates ausentes ou falhos;
- qualquer total/hash/alias diverge;
- catálogo anterior alterado;
- v5 aceito por inferência de nome/data em vez de allowlist;
- dry-run cria row;
- publicação parcial ou não idempotente;
- migration/startup/produção tocados;
- arquivo extra;
- relatório ausente ou final menor que baseline.

## Gates de autoavaliação

1. Qual teste prova que somente o algoritmo mudou estruturalmente?
2. Quais são os cinco hashes e como os quatro históricos foram preservados?
3. Qual evidência prova aliases 48/48 e 3A/CO intactos?
4. Qual snapshot prova dry-run sem escrita?
5. Qual teste prova criação uma vez e retry no-op?
6. Há qualquer caminho implícito de ativação? Mostre inspeção.

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CIPOO-S2-report.md` com status, BASE_REF, matriz,
RED/GREEN, snippets antes/depois, hashes, comparação estrutural, dry-run,
publicação sintética, inspeções, baseline/final, todos os gates, arquivos,
justificativas, riscos e `Handoff para verificador` R1–R6 com comandos exatos de
rerun.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the complete change
count-identified-patients-for-official-occupancy, S1 report/commit, catalog
service/command, all catalog JSONs, tests, and SLICE-CIPOO-S2.md. Implement ONLY
S2 using the DeepSeek4-Flash protocol: clean baseline, official container unit
baseline, real RED, minimal GREEN, clean-code/DRY/YAGNI refactor, inspections,
all official gates and baseline-vs-final proof. Touch only capacity_catalog.py,
new sector_capacity_catalog_v5.json and its unit test. Preserve four historical
files/hashes exactly, prove 43/48/47/39/4/666/666, aliases 48/48, CO, 3A,
dry-run zero-write and atomic/idempotent synthetic publication. Never activate
production, migrate, edit UI or anticipate S3. Create
/tmp/sirhosp-slice-CIPOO-S2-report.md with evidence and verifier handoff. On any
missing/failing item report INCOMPLETE without tasks/commit. If all pass, mark
only S2, commit, push, reply REPORT_PATH=..., then STOP.
```
