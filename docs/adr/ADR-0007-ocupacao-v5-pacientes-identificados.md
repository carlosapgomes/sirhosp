# ADR-0007 — Ocupação v5 por pacientes identificados e apresentação de `/beds`

## Status

Accepted

## Contexto

As ADR-0005 e ADR-0006 consolidaram a identidade física `(origem, leito)` e
uma lista única por componente do grafo catálogo↔origem. A produção mostrou
que essa fotografia física não representa a lotação clínica: pacientes podem
não ter leito informado, mãe e RN compartilham o mesmo leito, um mesmo
prontuário pode ser informado em mais de um setor oficial e um setor pode usar
nomenclaturas operacionais fora do cadastro oficial.

A v4 analisada tinha uma ponte alternativa simples e integral por paciente:
647 linhas com nome e prontuário válidos, 642 pacientes identificados (597 em
grupos standard + 45 em grupos unrated), enquanto a posição física gerava
561/666. O sistema precisa de um numerador que represente pacientes
identificados no grupo oficial, sem omitir pacientes sem leito e sem fundir
pessoas distintas que dividem leito.

Esta ADR registra a unidade de contagem v5 e a nova apresentação de `/beds`,
substituindo as ADR-0005/0006 somente para `occupancy-v5`. V1, v2, v3, v4, as
ADR-0005/0006, catálogos e medições persistidas permanecem imutáveis e
históricos.

## Decisão

- **Paciente é a unidade de contagem**: para v5, cada linha ocupada é
  classificada como `identified_patient` (prontuário numérico não vazio e nome
  não vazio sem marcador operacional), `incomplete_identity` ou
  `operational_state`. Somente pacientes identificados participam do
  numerador; o leito é atributo descritivo, nunca chave de contagem.
  Paciente sem leito conta; pacientes distintos no mesmo leito contam
  separadamente.
- **Identidade estrita e textual**: prontuário é sequência não vazia de
  dígitos mantida como string (zeros à esquerda significativos); nome é
  strip, uppercase e colapso de espaços. Marcadores `DESOCUPADO`, `VAZIO`,
  `LIMPEZA`, `RESERVA` e `ISOLAMENTO` (por substring) nunca são pacientes.
- **Deduplicação dentro do grupo oficial**: a chave é
  `(grupo oficial, prontuário normalizado)`. Grupos compartilhados (Cardio)
  deduplicam entre todos os seus códigos-fonte. O mesmo prontuário em grupos
  oficiais distintos conta uma vez em cada grupo e recebe advertência factual
  `Prontuário informado em mais de um setor oficial neste censo`, sem escolher
  setor vencedor.
- **Partição 3A antes da escolha**: o código 654 deduplica o prontuário antes
  de resolver Adulto/Infantil; faixa confiável única decide, e na ausência ou
  conflito o fallback é o prefixo literal `RN` para Infantil, senão Adulto.
  Não há grupo 3A combinado e o total 48 nunca é usado como capacidade única.
- **Estados operacionais são linhas do sistema de origem**: vago, reservado,
  manutenção e isolamento aparecem com seu estado e leito informado (inclusive
  uma única linha isolada); não entram no numerador, não reduzem capacidade e
  em UI v5 nunca recebem `conflito`, `registro divergente` ou
  `não autoritativo`. Identificação incompleta fica em bloco próprio
  `Identificação incompleta — não contada`.
- **Mensagens factuais sem vencedor**: nomes variantes mostram todos os nomes
  e `Nome informado de formas diferentes em N linhas`; leito repetido entre
  pacientes mostra `N pacientes informados com o mesmo leito`; o mesmo leito
  com estados diferentes mostra `N estados informados para o mesmo leito`.
  Nenhum nome, leito, setor ou estado é escolhido como verdade.
- **Privacidade**: nomes, prontuários e leitos existem somente em memória de
  materialização e no HTML autenticado do censo exato. Medição, resumo diário,
  logs, reconciliação (schema 3 allowlisted) e relatórios recebem somente
  agregados.
- **Saldo da capacidade oficial**: o rótulo v5 é `Saldo da capacidade
oficial`, explicando que é saldo calculado por setor, não lista nominal de
  leitos vagos. `Capacidade oficial` aparece uma única vez; `Pacientes
identificados`, `Excedente` e `Taxa de ocupação` completam o resumo, com
  cobertura (39 de 43, quatro fora da taxa) como metadado secundário.
- **Lista única v5**: a seção detalhada passa a `Setores, pacientes e estados
de leitos`; cada componente do grafo catálogo↔origem mantém capacidade
  oficial e aliases e lista pacientes deduplicados com todas as variantes,
  leitos e códigos, identificação incompleta e estados operacionais por
  código-fonte.
- **Ativação future-only e correção forward**: v5 inicia somente por catálogo
  integral publicado para data futura explícita, sem backfill; divergências
  são corrigidas em versões futuras, nunca reescrevendo medições, catálogos,
  ADRs ou relatórios anteriores.
- **Substituição parcial das ADR-0005/0006**: esta ADR substitui somente as
  decisões de unidade de contagem (posição física → paciente identificado) e
  de apresentação (cards, ponte e lista) para `occupancy-v5`. As decisões de
  catálogo temporal imutável (ADR-0003), CO fora da taxa e partição etária
  (ADR-0004) e as regras históricas v1–v4 permanecem vigentes.

## Alternativas Consideradas

1. **Corrigir apenas a normalização física v4**
   - Vantagens: mudança incremental pequena.
   - Desvantagens: continua omitindo pacientes sem leito e subcontando pessoas
     distintas no mesmo leito.
   - Motivo da rejeição: a simulação v4 mostrou 21 pacientes sem leito e a
     contagem física não representa a lotação clínica.

2. **Deduplicar prontuário no hospital inteiro**
   - Vantagens: um paciente contaria uma única vez.
   - Desvantagens: a soma dos setores deixaria de fechar com o hospital e
     exigiria escolher um setor verdadeiro.
   - Motivo da rejeição: a decisão mantém a soma setorial e trata o caso
     múltiplo-setor com advertência factual.

3. **Escolher nome/leito/estado vencedor na UI**
   - Vantagens: detalhe mais curto.
   - Desvantagens: criaria autoridade implícita sobre identidade e estados.
   - Motivo da rejeição: todas as evidências devem permanecer visíveis sem
     vencedor.

4. **Continuar com os cards v3/v4 em v5**
   - Vantagens: continuidade visual.
   - Desvantagens: capacidade duplicada e linguagem de autoridade que não
     corresponde à contagem por paciente.
   - Motivo da rejeição: o resumo v5 remove redundância e usa vocabulário
     factual.

## Consequências

### Positivas

- Numerador representa pacientes identificados no grupo oficial, sem omitir
  sem-leito e sem fundir ocupantes do mesmo leito.
- Evidências completas na página autenticada (nomes variantes, leitos,
  códigos, estados) sem persistir PHI.
- Mensagens factuais tornam duplicação, repetição de leito e estados
  divergentes acionáveis sem linguagem de conflito.
- V1–v4, ADR-0005/0006 e todos os valores persistidos permanecem imutáveis.

### Negativas / Trade-offs

- Prontuário incorreto pode contar paciente; a validação numérica e as
  advertências de repetição mitigam, mas não provam identidade clínica.
- Mesmo prontuário em dois setores infla o total hospitalar; decisão explícita
  para preservar a soma setorial, com advertência factual.
- Fallback etário classifica por nome somente quando a idade é ausente ou
  conflitante, com contadores agregados.
- Listagem expõe variantes e leitos somente autenticada, exact-run e efêmera.

## Referências

- ADR-0005 — duas realidades em `/beds` (substituída parcialmente para v5 na
  unidade de contagem e apresentação).
- ADR-0006 — ocupação v4 acionável (substituída parcialmente para v5 na
  unidade de contagem e apresentação; elegibilidade v4 preservada).
- ADR-0003 e ADR-0004 — catálogo temporal imutável e política CO/3A
  preservados.
- Change OpenSpec `count-identified-patients-for-official-occupancy` (proposal,
  design, specs delta, tasks e relatórios dos slices S1–S3).
- Implementação: `apps/census/occupancy.py`,
  `apps/census/templates/census/bed_status.html`, catálogo
  `sector_capacity_catalog_v5.json`.
