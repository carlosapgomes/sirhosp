## 1. PFIF-S1 — Fallback persistente de Atendimentos

- [x] 1.1 Ler integralmente `slice-prompts/SLICE-PFIF-S1.md`, registrar
      `BASE_REF`, árvore limpa e baselines oficiais antes de editar.
- [x] 1.2 RED: cobrir contrato mínimo, parser estrutural, faixas de recência,
      navegação condicional, cleanup e ausência de vazamento.
- [x] 1.3 GREEN/REFACTOR: implementar fallback no worker persistente até run
      reconhecido, contadores zero, stage allowlisted e batch drainage.
- [x] 1.4 Provar que snapshot não vazio, standalone, full-sync e evidência não
      recente preservam contratos fail-closed existentes.
- [x] 1.5 Executar inspeções e gates oficiais, gerar
      `/tmp/sirhosp-slice-PFIF-S1-report.md`, marcar apenas 1.x e parar.

## 2. PFIF-S2 — Paridade do worker clássico

> **Governança:** a implementação `829afd5` e o relatório original foram
> reprovados por verificação independente. O fluxo não clicava
> `Atendimentos` antes de ler a tabela e solicitava sidecar em standalone.
> Corrigido e aprovado em PFIF-S2R (commit `14969c6`, verificação
> independente com RED reproduzido e gates exit zero); 2.x e 2R.x marcados
> pelo verificador com base na aprovação de S2R.

- [x] 2.1 Confirmar S1 COMPLETE/verificado e ler integralmente
      `slice-prompts/SLICE-PFIF-S2.md` antes de editar.
- [x] 2.2 RED: cobrir saída lateral opcional de `path2.py`, adapter clássico e
      matriz de paridade current/persistent com fixtures sintéticas.
- [x] 2.3 GREEN/REFACTOR: reutilizar o contrato S1 sem quebrar o JSON/lista de
      internações e sem novo browser/login/subprocess por fallback.
- [x] 2.4 Provar equivalência de status, counters, stages, follow-ups, cleanup e
      batch para recente e não recente.
- [x] 2.5 Executar inspeções e gates oficiais, gerar
      `/tmp/sirhosp-slice-PFIF-S2-report.md`, marcar apenas 2.x e parar.

## 2R. PFIF-S2R — Correção da navegação clássica

- [x] 2R.1 Ler integralmente `slice-prompts/SLICE-PFIF-S2R.md`, confirmar a
      reprovação de S2 e registrar baseline a partir de `829afd5`.
- [x] 2R.2 RED: usar página fake stateful para provar que rows de Atendimentos
      só ficam acessíveis após clique exato e na ordem correta.
- [x] 2R.3 GREEN/REFACTOR: clicar `Atendimentos` antes da leitura e pedir o
      sidecar somente para `admissions_only` batch-bound.
- [x] 2R.4 Provar que batch-bound usa um subprocesso/sessão e que standalone,
      lista não vazia e full-sync não navegam para Atendimentos.
- [x] 2R.5 Executar inspeções e gates oficiais, gerar
      `/tmp/sirhosp-slice-PFIF-S2R-report.md` e submeter o commit corretivo sem
      marcar tasks; somente o planner, após aprovação independente, marca 2.x e
      2R.x e libera S3.

## 3. PFIF-S3 — Classificador bulk e rótulos em `/censo`

- [x] 3.1 Confirmar S1 e S2R COMPLETE/verificados, com S2 original registrado
      como reprovado, e ler integralmente `slice-prompts/SLICE-PFIF-S3.md`
      antes de editar.
- [x] 3.2 RED: cobrir prioridades de classificação, eixo técnico independente,
      auto-resolução e orçamento fixo de queries.
- [x] 3.3 GREEN/REFACTOR: implementar serviço único de findings e integrá-lo à
      linha desktop e card mobile de `/censo`.
- [x] 3.4 Preservar autenticação, filtros, ordenação, links e XLSX sem nova
      coluna ou query em loop.
- [x] 3.5 Executar inspeções e gates oficiais, gerar
      `/tmp/sirhosp-slice-PFIF-S3-report.md`, marcar apenas 3.x e parar.

## 4. PFIF-S4 — Rótulos em `/beds` e admissões

- [x] 4.1 Confirmar S3 verificado e ler integralmente
      `slice-prompts/SLICE-PFIF-S4.md` antes de editar.
- [x] 4.2 RED: cobrir pacientes v5, apresentações históricas, página sem
      internação/com internação e finding com revisão manual.
- [x] 4.3 GREEN/REFACTOR: reutilizar o mapa bulk S3 nas duas superfícies, com
      helper de template somente para lookup/apresentação.
- [x] 4.4 Provar que medição/capacidade/reconciliação, conflitos, autorização e
      queries permanecem inalterados.
- [x] 4.5 Executar inspeções e gates oficiais, gerar
      `/tmp/sirhosp-slice-PFIF-S4-report.md`, marcar apenas 4.x e parar.

## 5. PFIF-S5 — Métricas, health e operação

- [x] 5.1 Confirmar S4 verificado e ler integralmente
      `slice-prompts/SLICE-PFIF-S5.md` antes de editar.
- [x] 5.2 RED: cobrir vazio reconhecido versus anômalo, details forjados,
      achados agregados, falha parcial e timeout técnico preservado.
- [x] 5.3 GREEN/REFACTOR: ajustar health/portal sem novo status persistido e com
      saída estritamente agregada.
- [x] 5.4 Documentar canário, métricas de avanço/parada e rollback sem executar
      produção ou reclassificar história.
- [x] 5.5 Executar inspeções, gates oficiais, OpenSpec strict e markdown lint;
      gerar `/tmp/sirhosp-slice-PFIF-S5-report.md`, marcar apenas 5.x e parar.

## 6. Verificação final do change

- [x] 6.1 Ter relatórios aprovados de S1, S2R, S3, S4 e S5, além do registro da
      reprovação do relatório S2 original, todos com handoff verificável por
      terceiro LLM.
- [x] 6.2 Executar `./scripts/test-in-container.sh quality-gate` e
      `./scripts/test-in-container.sh integration` com exit code zero.
- [x] 6.3 Executar
      `openspec validate recognize-patient-flow-findings --strict`.
- [x] 6.4 Executar `./scripts/markdown-lint.sh` sem inibições.
- [x] 6.5 Revisar diff para ausência de PHI, profissional, HTML/PDF, URL real,
      credencial, model/migration/status/dependência não autorizados.
- [x] 6.6 Não acessar o legado, fazer deploy, rollout, backfill, requeue ou
      arquivamento sem autorização explícita posterior.
