# Tasks

## Avaliação e sequência proposta

A change é suficientemente definida para slicing: não foi identificada uma
lacuna de produto/design que impeça estes contratos. Isso não equivale à
aprovação da change ou à autorização de implementação. Aplicam-se `AGENTS.md`,
proposal, design e specs; nenhum requisito ou decisão desses artefatos foi
alterado pelo slicing. A execução sequencial foi posteriormente autorizada
explicitamente pelo operador via `/slice-loop-orca-v2`; o progresso aceito está
registrado abaixo.

Sequência: **ECD-S1 → ECD-S2 → ECD-S3**, sem execução paralela ou deploy
intermediário. Cada item abaixo herda o contrato explicitamente ligado ao grupo.
Os contratos revisados foram autorizados pelo operador para execução sequencial,
com implementação e revisão independentes e aceite por slice.

Três slices bastam porque:

- ECD-S1 entrega transporte → parsing → persistência da precisão, não só schema.
- ECD-S2 entrega um produtor/command coerente e fechado contra coleta parcial,
  usando a aquisição vigente. Não cria backend ou modo operacional novo.
- ECD-S3 troca a aquisição para DOM e prova a composição completa, reutilizando
  as guardas aceitas. Não deixa helpers sem consumidor ou verification para
  um slice separado que não entrega comportamento.

O resumo e seu consumidor entram juntos em ECD-S2; DOM entra depois em ECD-S3.
É uma ordenação interna da mesma entrega descrita no Migration Plan, sem mudar
D1–D7, sem emparelhar versões incompatíveis e sem ativação em produção entre slices.

### Rastreabilidade do plano anterior

| Itens anteriores | Novo contrato | Preservação do objetivo                                         |
| ---------------- | ------------- | --------------------------------------------------------------- |
| 1.1–1.6          | ECD-S1        | Precisão opcional, compatibilidade, banco, regressões e docs.   |
| 3.1, 3.3–3.6     | ECD-S2        | Produtor/command, resumo, atomicidade, privacidade e docs.      |
| 2.1–2.7 e 3.2    | ECD-S3        | DOM, variantes, seleção, tooltips, páginas e troca operacional. |
| 4.1–4.5          | ECD-S3        | Composição browser/banco, runbook, gates e matriz final.        |

## 1. ECD-S1 — Precisão de origem do CSV ao snapshot

Contract: [slice-001-preserve-source-timestamps](slices/slice-001-preserve-source-timestamps.md).
Dependências: nenhuma. Requirements R1–R5 e aceite estão no contrato.

- [x] 1.1 Demonstrar RED para ambos os horários no parser e no snapshot criado
      pelo command; verificar falha de comportamento ausente, não só de import/schema,
      com CSV e no mínimo 40 setores sintéticos — ECD-S1 R1/R2.
- [x] 1.2 Adicionar somente os dois campos opcionais e a transformação de
      precisão/projeção definidos em D6; verificar GREEN, timezone, calendário,
      datas legadas, vazios, migração aditiva e ausência de backfill — ECD-S1 R1–R3.
- [x] 1.3 Persistir os valores opcionais pelo command; verificar em PostgreSQL
      leitura de volta, vínculo ao run e timestamp inválido sem lote parcial ou
      valor vazado, preservando o caminho vigente sem resumo futuro — ECD-S1 R1/R4.
- [x] 1.4 Executar regressões de leito/idade, movimento idempotente, ocupação e
      renderização com entrada enriquecida; verificar projeções/identidades iguais
      e nenhuma criação de paciente para rótulo de leito — ECD-S1 R2/R5.
- [x] 1.5 Documentar precisão opcional, timezone e compatibilidade no README do
      conector; verificar que não promete hora na Trajetória — ECD-S1 R2/R3.
- [x] 1.6 Executar validações/gates pertinentes do contrato e produzir
      `/tmp/sirhosp-slice-ECD-S1-report.md` com R1–R5 → evidência, RED/GREEN, banco,
      comandos e desvios; verificar aceite antes de avançar para ECD-S2.

Aceite técnico ECD-S1: `ACCEPTED`, revisão independente `OK with notes`,
zero P0/P1 e três notas P2 informativas, sem correção exigida. Gates oficiais:
4.440 unitários, 1.077 testes de integração, check, lint/typecheck e Markdown
aprovados; RED/GREEN e persistência PostgreSQL sintética auditados.
Relatório: `/tmp/sirhosp-slice-ECD-S1-report.md`. Evidências e recibo de aceite:
`/tmp/sirhosp-orca-sequence-a3IUbz9l/slices/ECD-S1/`. Delta aceito sem commit;
trabalho prévio preservado. Naquele aceite, ECD-S2/ECD-S3 e deploy ainda não
haviam sido executados; o avanço posterior está registrado nos grupos seguintes.

## 2. ECD-S2 — Publicação integral e atômica do censo

Contract: [slice-002-reject-incomplete-census-publication](slices/slice-002-reject-incomplete-census-publication.md).
Dependência: ECD-S1 aceito. Requirements R1–R5 e aceite estão no contrato.

- [x] 2.1 Demonstrar RED do produtor após 40 sucessos e um setor falho e do
      command com exit zero/resumo ausente ou parcial; verificar que o comportamento
      anterior aceitaria/publicaria uma extração indevida — ECD-S2 R1–R3.
- [x] 2.2 Implementar publicação consistente de CSV/resumo v1 e contadores no
      coletor ainda vigente; verificar GREEN para sucesso, vazio, descoberta
      incompleta, retry esgotado e escopo diagnóstico limitado — ECD-S2 R1/R2.
- [x] 2.3 Integrar a validação do resumo ao command, artefatos únicos,
      `--csv-only`, contadores, row count e threshold 40; verificar rejeição de
      resumo ausente/malformado, inconsistências, ambiguidade e falso sucesso,
      com produtor e consumidor funcionando juntos — ECD-S2 R3/R5.
- [x] 2.4 Tornar atômicos snapshots e aceitação do run; verificar em integração
      a reversão com falha injetada, baseline anterior preservada e nenhum efeito
      posterior originado do run rejeitado, mantendo ECD-S1 — ECD-S2 R4.
- [x] 2.5 Sanear diagnósticos e retirar dumps/cópias clínicas do caminho normal,
      documentando protocolo, limites e falhas no README; verificar sentinelas em
      dados, exceções, arquivos, logs e métricas — ECD-S2 R5.
- [x] 2.6 Executar produtor → transporte → command → banco e os gates do
      contrato; produzir `/tmp/sirhosp-slice-ECD-S2-report.md` com R1–R5 → evidência
      e registrar que DOM ainda não foi entregue; verificar aceite antes de ECD-S3.

Aceite técnico ECD-S2: `ACCEPTED`, revisão independente final `OK with notes`,
zero P0/P1 e três notas P2 informativas. Duas rodadas de revisão e uma correção
mínima concluídas: `P1-C1` resolveu mensagens brutas de exceção em dois helpers,
com regressões comportamentais RED/GREEN. Estado reparado: quality gate com
4.468 unitários, check, lint/typecheck; integração separada com 1.080 testes,
Markdown e diff check aprovados. Os 288 arquivos monitorados, HEAD, index e
inventário permaneceram intactos durante a revisão final.
Relatório atual: `/tmp/sirhosp-slice-ECD-S2-report.md`; evidências originais,
correção, revisão final e recibo: `/tmp/sirhosp-orca-sequence-a3IUbz9l/slices/ECD-S2/`.
Delta aceito sem commit; ECD-S1 e trabalho prévio preservados. Naquele aceite,
a aquisição ainda era XLSX e ECD-S3 não havia sido executado; o avanço posterior
está registrado no grupo seguinte. Sem deploy.

## 3. ECD-S3 — Censo DOM até o snapshot, sem exportação

Contract: [slice-003-switch-census-to-dom](slices/slice-003-switch-census-to-dom.md).
Dependências: ECD-S1 e ECD-S2 aceitos. Requirements R1–R8 estão no contrato.

- [x] 3.1 Demonstrar RED de `run` em browser sintético com tabela/tooltips e
      sem superfície de exportação; acrescentar RED de paridade, seleção, variantes,
      inicialização e paginação, usando workbook sintético e parser XLSX real como
      referência, não payload clínico da investigação — ECD-S3 R1–R5.
- [x] 3.2 Implementar mapeamento/normalizações dos 11 campos, metadados e
      confirmação de setor nativo; verificar cabeçalhos repetidos/ocultos,
      acentos/códigos compartilhados, ordem não relacionada e elegibilidade de
      linhas, sem coletar campos extras ou deduplicar conflitos — ECD-S3 R2/R3.
- [x] 3.3 Implementar os dois tooltips associados à célula e a espera limitada,
      página longa confirmada e travessia completa; verificar atrasos, vazio,
      associação errada, ambiguidade, inconsistências, 100+1, reset, totais e
      paginação parada/repetida ou excedida — ECD-S3 R4/R5.
- [x] 3.4 Trocar a aquisição de `run` para DOM e reutilizar o handoff ECD-S2;
      verificar ausência de exportação/fallback, bootstrap/proxy/CLI e proteção
      contra resultado vazio obsoleto, falha após 40 sucessos e vazamento — ECD-S3 R1/R6.
- [x] 3.5 Criar o verificador local restrito de UI sintética e executar
      `uv run python automation/lab/playwright_experiments/verify_census_dom.py --synthetic`;
      verificar o coletor operacional, golden workbook e protocolo realmente
      produzidos, sem `.env` hospitalar ou rede externa — ECD-S3 R1–R6.
- [x] 3.6 Compor o transporte real do teste com integração PostgreSQL;
      verificar ambos os timestamps, datas antigas, isolamento de run e efeitos
      clínicos/ocupação/ausência equivalentes — ECD-S3 R7.
- [x] 3.7 Atualizar README/runbook para extração DOM, limites, implantação
      conjunta, migração aditiva, conferência agregada e rollback de imagem;
      verificar coerência com `deploy/README.md`, sem serviços novos, horas na UI
      ou deploy executado — ECD-S3 R8.
- [x] 3.8 Executar quality gate final, integração separada, verification
      sintética e Markdown conforme contrato/`AGENTS.md`; produzir
      `/tmp/sirhosp-slice-ECD-S3-report.md` e matriz dos três deltas → evidências,
      verificar o estado final reparado e submeter à revisão antes de aceite,
      commit ou publicação — ECD-S3 R1–R8.

Aceite técnico ECD-S3: `ACCEPTED`, uma revisão independente `OK with notes`,
zero P0/P1 e quatro notas P2 não bloqueadoras. RED operacional em Chromium sem
exportação e caracterização das horas ausentes no workbook preservados; casos
GREEN de seleção, variantes, tooltips e paginação auditados. Estado final:
quality gate com 4.492 unitários, check, lint/typecheck (499 arquivos), integração
separada com 1.081 testes e oito cenários do verificador sintético aprovados,
sem requisições externas. Markdown e diff check aprovados. Os 295 arquivos
monitorados, HEAD, index e inventário permaneceram intactos durante a revisão.
Relatório: `/tmp/sirhosp-slice-ECD-S3-report.md`; revisão e recibo de aceite:
`/tmp/sirhosp-orca-sequence-a3IUbz9l/slices/ECD-S3/`. Delta atribuível sobre os
slices anteriores preservado sem commit; cinco arquivos originais da investigação
intactos. Extração DOM composta até PostgreSQL sintético; nenhuma visita à fonte
real, alteração de semântica clínica ou implantação executada.

Notas P2: atenção ao novo nome-base do CSV para consumidores manuais não
documentados; observar o formato nativo do paginador na primeira janela de fonte
separadamente autorizada (falhas permanecem fechadas); verificador completo leva
aproximadamente dez minutos; seleção diagnóstica só por descrição rejeita
ambiguidade. Não motivam correção ou acesso à fonte neste workflow.

Todos os três slices estão aceitos tecnicamente. Publicação, deploy, sync e
archive continuam dependentes de autorização separada.
