# Tasks

## Revisão da decomposição

Plano revisto com `openspec-vertical-change-writer`: **quatro slices verticais
sequenciais**. A manutenção do catálogo no admin foi separada do cadastro
estruturado da equipe, reduzindo o acúmulo no antigo S1 sem criar slice apenas
de banco/backend. A sequência está sincronizada com D9 do design; catálogo,
requisitos de produto e arquitetura permanecem os mesmos.

Cada task X.Y pertence ao contrato apontado no grupo X. Formulários e escrita
estruturada são entregues em S2; apresentação/refresh do agregado em S3; novo
contrato de células XLSX em S4. A renumeração ocorre antes da execução: nenhum
slice foi implementado, aceito ou marcado como concluído.

Ajustes para rechecagem do plano: D1/PI-02/S1 explicitam slugs imutáveis,
referência atual ou histórica e contrato fixo de Outro; D8 define a matriz
binária de inicialização/reaplicação; D4/PI-06 enumeram os snapshots. D3 e os
contratos distribuem constraints locais entre S1/S2; S2 inicia a apresentação
compartilhada de D6 e S3 corrige a referência ao XLSX de S4. Os helpers após
flush foram nomeados em S1. Esses ajustes não iniciam implementação.

## 1. S1 — Catálogo categorizado

Contrato: [slice-001](slices/slice-001-catalogo-categorizado.md).
Dependência: aprovação humana da change e deste contrato.

- [x] 1.1 Entregar categorias/tipos/perfis no admin e a carga completa; verificar por testes de integração RED/GREEN a correspondência exata das 10 categorias e 46 entradas, incluindo identidades, perfis e complementos, não somente contagens.
- [x] 1.2 Executar migrations conservadoras e proteger manutenção administrativa; verificar cada caso da matriz D8 desde 0002 e em reaplicação, slugs imutáveis, tipo usado só em revisão, categoria protegida, contrato fixo de Outro sem uso e constraints de S1/D3. Adaptar os dois helpers _ensure_bootstrap nomeados no contrato e comprovar funcionamento após flush, sem criar framework novo.
- [x] 1.3 Preservar os sete metadados de classificação enumerados em D4 e contextualizar rótulos nos seletores; verificar cadastro/edição/finalização, metadados antigos desconhecidos e renomeação seguida de reaplicação sem duplicação ou reescrita histórica, por testes e jornada sintética de admin -> portal.
- [x] 1.4 Executar validações focadas e produzir `/tmp/sirhosp-slice-STRUCT-PEND-S1-report.md`, incluindo notas de migration; verificar R1–R5 do contrato com RED/GREEN e runtime, mantendo os formulários atuais funcionando sem antecipar campos do item. Aceite e atualização das tarefas pertencem ao controller após revisão independente.

## 2. S2 — Cadastro e gestão estruturada

Contrato: [slice-002](slices/slice-002-cadastro-estruturado.md).
Dependência: S1 aceito.

- [x] 2.1 Estender item/revisão com os campos dos quatro perfis e RNM, preservando o estado histórico; verificar upgrade desde S1, matriz normativa de preenchimento por domínio/POST real e constraints locais de S2/D3 por escrita direta em item e revisão, incluindo nulos históricos, em RED/GREEN.
- [x] 2.2 Implementar alterações de detalhes, remoções confirmadas, no-op e snapshots completos em toda escrita; verificar atomicidade, conflitos, finalizações humanas e saídas alta/óbito/transferência/merge, com autoria Sistema e detalhes preservados em testes de regressão.
- [x] 2.3 Entregar cadastro progressivo e todos os formulários de edição, inclusive modal, iniciando a apresentação compartilhada D6 no contexto; verificar quatro perfis, busca RNM contextualizada, adicionar outra sem duplicação, retenção de entradas e mobile/teclado em Playwright sintético, sem renderização paralela que S3 precise refazer.
- [x] 2.4 Executar validações focadas e produzir `/tmp/sirhosp-slice-STRUCT-PEND-S2-report.md`; verificar R1–R6 do contrato com RED/GREEN, runtime e notas de migration, sem adiar defeitos de escrita ou preservação do modal para S3. Aceite e atualização das tarefas pertencem ao controller após revisão independente.

## 3. S3 — Acompanhamento institucional

Contrato: [slice-003](slices/slice-003-painel-categorizado.md).
Dependência: S2 aceito.

- [x] 3.1 Apresentar categoria/tipo/detalhes nas duas visões e no histórico recolhível; verificar igualdade com o contexto, distinção Não/Não informado/Não aplicável e apresentação de versão antiga por testes HTTP e Playwright RED/GREEN.
- [x] 3.2 Acrescentar categoria aos filtros compartilhados antes de agrupamento/paginação; verificar interseção com tipo, combinação incompatível vazia, IDs inválidos, recorte conservador e indicadores invariantes por testes unitários e de integração RED/GREEN.
- [x] 3.3 Integrar o refresh do painel à escrita já entregue por S2, preservando filtros/modo; verificar edição somente de detalhe, conflito, perda de grupo e saída, além de paridade com XLSX anterior por marcadores sintéticos exclusivos, sem antecipar colunas ID.
- [x] 3.4 Executar validações focadas e produzir `/tmp/sirhosp-slice-STRUCT-PEND-S3-report.md`; verificar R1–R5 do contrato com RED/GREEN e runtime, inclusive exclusão de saída confirmada do agregado/exportação e preservação do histórico contextual. Aceite e atualização das tarefas pertencem ao controller após revisão independente.

## 4. S4 — Exportação estruturada

Contrato: [slice-004](slices/slice-004-xlsx-estruturado.md).
Dependência: S3 aceito.

- [x] 4.1 Ampliar o XLSX para as 23 colunas de PP-08 com tipos de célula corretos; verificar por testes unitários RED/GREEN cabeçalho exato, quatro perfis, RNM, datas civis/instantes nativos e informação desconhecida versus não aplicável.
- [x] 4.2 Preservar seleção compartilhada, textos literais, timezone, cache e ausência de resíduos; verificar paginação completa, filtros/modos/categorias, fórmulas como texto, registro com zero inicial e resultado vazio por integração, com saída real excluída do recorte.
- [x] 4.3 Verificar download real após cadastro/edição e abri-lo com openpyxl; confirmar valores, primeira unidade, autofiltro e cabeçalho fixo. Testar autoria Sistema separadamente em fixture isolada de serialização, sem exigir internação já encerrada no agregado atual.
- [x] 4.4 Executar validações focadas e produzir `/tmp/sirhosp-slice-STRUCT-PEND-S4-report.md`; verificar R1–R5 do contrato com RED/GREEN, download e nota operacional do novo contrato XLSX. Aceite e atualização das tarefas pertencem ao controller após revisão independente.

## 5. Gate integrado da change

Não é um quinto slice nem uma fase para adiar testes dos anteriores. É o gate
final do controller após os quatro slices aceitos, conforme `AGENTS.md`.

- [x] 5.1 Executar `./scripts/test-in-container.sh quality-gate` e, separadamente, `./scripts/test-in-container.sh integration` no estado final; verificar ambos com exit status zero, incluindo browser sintético, sem usar resultados anteriores a alterações de código como evidência final.
- [x] 5.2 Executar `./scripts/markdown-lint.sh` e `openspec validate structure-inpatient-pending-items --strict`; verificar sucesso e cobertura abaixo nos quatro relatórios, sem confundir artefatos de planejamento presentes com implementação aceita.

## Requirements -> slices

| Requisito                                   | Entrega e evidência responsáveis                                                                             |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| PI-01                                       | S2: cadastro com observações condicionais, classificação válida e repetição do mesmo tipo                    |
| PI-02                                       | S1: catálogo/admin/rótulos; S2: busca progressiva dos tipos homônimos                                        |
| PI-05                                       | S2: detalhes e FSM; S1 preserva os comportamentos anteriores                                                 |
| PI-06                                       | S1: classificação observada; S2: campos tipados/revisões/atomicidade; S3: consulta no agregado               |
| PI-09                                       | S2: validação/persistência; S3: apresentação; S4: exportação fiel                                            |
| PI-10                                       | S1: upgrade do catálogo/classificação; S2: upgrade dos campos de item/revisão                                |
| PI-11                                       | S2: mesmos estados, sem inferência clínica ou automação por datas                                            |
| PP-03                                       | S2: contexto; S3: visões institucionais e histórico recolhível                                               |
| PP-04                                       | S3: filtro/interseção; S4: mesmo recorte na exportação nova                                                  |
| PP-06                                       | S2: escrita/formulários/conflitos; S3: refresh e retenção de filtros/modo                                    |
| PP-08                                       | S4: contrato completo, células, seleção, download e segurança                                                |
| PP-10                                       | S2: cadastro individual progressivo e edição coerente                                                        |
| PI-03/04/07/08; PP-01/02/05/07/09, mantidos | Regressões nas superfícies afetadas, incluindo saída real fora do agregado e histórico contextual preservado |

## Comandos e evidências

Os caminhos oficiais e o protocolo de relatórios estão em `AGENTS.md`;
cada contrato delimita os checks e o runtime de sua entrega. Os wrappers usam
`uv` no runner. Para conferência de migrations, executar nesse mesmo ambiente:
`uv run --no-sync python manage.py makemigrations --check --dry-run`.
Execução host-only é diagnóstico, não gate.

Jornadas usam live_server, PostgreSQL e dados sintéticos do harness existente.
Falha de browser/asset é bloqueio de infraestrutura. Evidência isolada de
serialização não substitui uma jornada real nem autoriza ampliar o recorte.
Verificação do portal implantado e deploy exigem autorização própria.

Todos os checkboxes permanecem abertos. Estes contratos não iniciam
workers/reviewers automaticamente, não aprovam implementação, não criam
commits, não fazem push, não arquivam a change e não autorizam descarte de dados.
