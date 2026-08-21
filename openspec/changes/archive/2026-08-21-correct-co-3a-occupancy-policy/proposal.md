## Why

A diretoria corrigiu duas premissas da primeira versão da lotação oficial: o
Centro Obstétrico não deve participar de nenhum percentual de ocupação e a
Enfermaria 3A deve ser tratada como dois setores virtuais calculáveis, separados
pela idade do ocupante. Sem a correção, censos futuros produziriam taxa
hospitalar com CO indevidamente incluído e sem os 48 leitos oficiais da 3A.

## What Changes

- Tratar o Centro Obstétrico, ainda agrupando os códigos `20`, `1110`, `1112`,
  `1114` e `1116`, como setor sem capacidade estatística e sem percentual,
  preservando apenas suas contagens brutas para apresentação e auditoria.
- Substituir `OBST-3A` pendente por dois setores virtuais oficiais:
  `OBST-3A-ADULTO`, capacidade 32, e `OBST-3A-INFANTIL`, capacidade 16.
- Classificar cada linha ocupada do código `654` exclusivamente pela coluna
  `Idade` do próprio censo: menor de 12 anos é infantil; 12 anos ou mais é
  adulto; não haverá pareamento mãe-criança nem deduplicação por prontuário.
- Normalizar somente a faixa etária necessária ao cálculo, aceitando os formatos
  conhecidos do legado: inteiro em anos ou no dia de nascimento, `Nm` e
  `NmDd`. Idade ausente ou inválida fica explícita como desconhecida.
- Excluir apenas a linha ocupada de idade desconhecida dos numeradores da 3A,
  manter denominadores 32 e 16, sinalizar a taxa pontual como parcial e excluir
  integralmente esse censo das médias oficiais diárias.
- Apresentar leitos não ocupados da 3A uma única vez em agrupamento auxiliar sem
  classificação etária, sem duplicá-los entre Adulto e Infantil.
- Substituir a cobertura baseada em códigos-fonte na apresentação oficial por
  cobertura de setores oficiais: 39 de 43 calculáveis, capacidade conhecida e
  calculável 666.
- Gravar as novas medições com `occupancy-v2`; preservar sem recálculo todas as
  versões, medições e médias `occupancy-v1`.
- Publicar a fotografia corrigida somente para a primeira meia-noite em
  `America/Bahia` posterior ao deploy da versão corretiva. Não substituir o
  catálogo já publicado para `2026-08-19` nem fazer backfill.
- Restringir os setores virtuais à capacidade, ocupação, histórico, resumo
  diário e `/beds`; os módulos clínicos continuam usando o setor-fonte 3A e o
  código `654`.
- Não alterar as regras gerais de ocupado, manutenção, reserva, isolamento,
  sobrelotação, completude do censo ou pacientes suspeitos de permanência
  indevida.

## Capabilities

### New Capabilities

Nenhuma. A correção evolui capacidades já existentes.

### Modified Capabilities

- `census-snapshot-processing`: preservar uma faixa etária normalizada e
  minimizada para cada linha do censo, sem alterar o processamento clínico.
- `versioned-sector-capacity-catalog`: permitir partições etárias exclusivas de
  um mesmo código-fonte e representar a fotografia corrigida com 43 setores e
  capacidade 666.
- `occupancy-measurement-history`: materializar `occupancy-v2`, excluir CO,
  particionar 3A por idade, auditar linhas desconhecidas e calcular cobertura
  por setor oficial.
- `daily-occupancy-summary`: excluir das médias oficiais o censo que tiver linha
  ocupada da 3A com idade desconhecida e registrar contagens válidas e
  excluídas.
- `bed-status-capacity-view`: mostrar CO sem percentual, duas linhas oficiais da
  3A, aviso de taxa parcial e agrupamento único para posições sem faixa etária.

## Impact

- Código afetado: extração e persistência do censo, modelos/migrations aditivos,
  catálogo temporal, materialização e resumo em `apps/census`, apresentação de
  `/beds` e testes focados.
- Dados: somente a faixa `under_12`, `age_12_or_over`, `unknown` ou
  `not_applicable` será necessária no snapshot; tabelas históricas de ocupação
  continuarão sem idade exata, nome, prontuário ou texto clínico.
- Operação: exige nova release e catálogo integral futuro; ativação e deploy são
  decisões separadas. O catálogo incorreto de `2026-08-19` e eventuais medições
  `occupancy-v1` permanecem imutáveis.
- Compatibilidade: nenhum módulo clínico passa a depender dos setores virtuais;
  não há Celery, Redis, microserviço, scheduler novo ou backfill.
- Governança: uma nova ADR deve substituir apenas as decisões de CO e 3A da
  ADR-0003, preservando suas decisões temporais e de imutabilidade.
- Risco: **CRITICAL/HIGH-ARCH**, pois a mudança altera um indicador hospitalar,
  adiciona dado derivado de idade, exige migrations e precisa manter história
  reproduzível entre duas versões de algoritmo.
