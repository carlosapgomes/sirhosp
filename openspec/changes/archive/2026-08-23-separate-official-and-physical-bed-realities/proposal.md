## Why

A página autenticada `/beds` apresenta atualmente duas bases legítimas com
rótulos semelhantes: capacidade oficial calculável e linhas brutas do censo
legado. Isso faz números como 636 ocupações oficiais, 667 linhas ocupadas, 666
unidades de capacidade e 847 linhas de leito parecerem contraditórios, enquanto
duplicatas exatas do mesmo leito podem ainda inflar o indicador oficial.

A gestão hospitalar precisa enxergar, sem ambiguidade, tanto o indicador
institucional baseado na capacidade publicada quanto a fotografia física
registrada no legado. A separação protege decisões operacionais, a experiência
do usuário e a rastreabilidade de qualidade dos dados.

## What Changes

- Introduzir `occupancy-v3`, ativado somente por catálogo integral futuro, para
  normalizar posições físicas em todos os setores antes do cálculo oficial.
- Colapsar duplicatas exatas do mesmo setor e leito sem deduplicar prontuários
  que estejam em leitos distintos.
- Classificar como conflito uma posição repetida com ocupante, status ou faixa
  etária divergente; excluir a posição do numerador pontual, marcar a medição
  como parcial e excluir o censo das médias oficiais diárias.
- Preservar todas as linhas brutas em `CensusSnapshot` e persistir apenas
  diagnósticos agregados e não identificáveis na história de ocupação.
- Persistir disponibilidade da capacidade oficial por setor e no hospital como
  soma dos saldos positivos setoriais, mantendo o excedente separado.
- Separar visualmente `/beds` em `Capacidade oficial e ocupação` e `Posições
  registradas no sistema legado`, com tabelas, rótulos, fontes e horários
  próprios.
- Exibir reconciliação agregada entre linhas ocupadas brutas, duplicatas,
  conflitos, posições sem identidade, setores fora da taxa, idade desconhecida
  e numerador oficial.
- Preservar integralmente medições `occupancy-v1` e `occupancy-v2`, sem backfill
  ou reinterpretação histórica.
- Registrar a decisão em ADR substitutiva apenas para identidade física,
  deduplicação, disponibilidade oficial e apresentação das duas realidades.

## Capabilities

### New Capabilities

Nenhuma. A mudança evolui capacidades existentes de catálogo, materialização,
resumo e apresentação.

### Modified Capabilities

- `occupancy-measurement-history`: adiciona normalização física auditável,
  `occupancy-v3`, disponibilidade oficial e tratamento parcial de conflitos.
- `daily-occupancy-summary`: exclui medições v3 com conflito físico das médias e
  preserva contagens de elegibilidade por motivo.
- `bed-status-capacity-view`: separa visual e semanticamente a realidade oficial
  da fotografia física do legado e apresenta reconciliação segura.
- `versioned-sector-capacity-catalog`: torna a versão do algoritmo parte do
  contexto temporal publicado e permite ativação futura explícita de v3.
- `census-snapshot-processing`: garante que problemas de identidade física
  afetem somente ocupação e não bloqueiem o fluxo clínico aceito.

## Impact

- **Código:** `apps/census/models.py`, `apps/census/occupancy.py`,
  `apps/census/capacity_catalog.py`, `apps/census/views.py`, template de
  `/beds`, migration aditiva, catálogo integral v3 e testes focados.
- **Banco:** novos metadados agregados de reconciliação, parcialidade,
  disponibilidade e versão do algoritmo; nenhuma alteração destrutiva.
- **Operação:** release e deploy não ativam v3. Um operador publica um catálogo
  completo para futura meia-noite de `America/Bahia`, sem backfill.
- **Privacidade:** nomes, prontuários, leitos e idades exatas permanecem fora das
  tabelas e alertas agregados de ocupação; o detalhe nominal continua restrito
  à página autenticada já existente.
- **Arquitetura:** permanece monólito Django com PostgreSQL, sem Celery, Redis,
  microserviço ou scheduler adicional.

## Non-goals

- Corrigir ou apagar dados no sistema legado.
- Deduplicar por prontuário entre leitos diferentes ou inferir mãe-criança.
- Identificar nominalmente quais leitos do legado compõem a capacidade oficial
  setorial.
- Reprocessar medições ou resumos históricos v1/v2.
- Alterar capacidade 666, política de CO, partição Adulto/Infantil da 3A,
  autenticação, processamento de pacientes ou movimentos clínicos.

## Success Criteria

- Usuário distingue imediatamente capacidade oficial de posições do legado.
- Cada posição física inequívoca aparece uma vez na visão física.
- Duplicatas exatas não entram no numerador v3; conflitos tornam a medição
  parcial e inelegível para médias diárias.
- Disponibilidade oficial não compensa excedente entre setores.
- A reconciliação fecha matematicamente sem expor dados identificáveis.
- V1 e v2 permanecem imutáveis e v3 inicia somente em dia local futuro.
