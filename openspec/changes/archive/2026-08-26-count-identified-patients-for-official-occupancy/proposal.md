# Change: Contar pacientes identificados na ocupação oficial

## Why

A operação real de `occupancy-v4` mostrou que a posição física informada pelo
sistema de origem não é uma chave confiável para estimar quantos pacientes estão
internados em um setor. Usuários das enfermarias e o NIR registram pacientes sem
leito, compartilham a mesma nomenclatura de leito entre mãe e recém-nascido e
movimentam pacientes sem uniformidade na identificação da posição.

No censo agregado analisado em produção, sem expor dados identificáveis, havia
647 linhas com nome e prontuário válidos, 642 prontuários únicos e 21 pacientes
sem leito informado. A semântica física v4 produziu numerador oficial 561. Uma
simulação por prontuário único dentro do grupo oficial produziu 597 pacientes em
grupos calculáveis e 45 em grupos `unrated`. Na Sala de Observação Adulto, sete
pacientes identificados sem leito resultaram em ocupação v4 zero para capacidade
um; a interpretação desejada é ocupação sete, saldo zero e excedente seis.

A apresentação também mostrou três cards com o mesmo valor 666 e usou
`registro divergente — não autoritativo` para situações heterogêneas. Além
disso, o classificador físico v4 trata uma única linha não ocupada como conflito,
fazendo linhas vagas, reservadas, em manutenção ou isolamento parecerem
ambíguas. A correção de negócio não deve tentar tornar a nomenclatura de leitos
uma autoridade: deve retirar o leito do numerador e tratá-lo somente como dado
informativo do censo.

## What Changes

- Introduzir `occupancy-v5`, ativado somente por catálogo integral futuro.
- Considerar paciente identificado somente quando:
  - o prontuário normalizado é não vazio e contém apenas dígitos;
  - o nome normalizado é não vazio e não é marcador operacional de vaga,
    limpeza/manutenção, reserva ou isolamento.
- Preservar zeros à esquerda e deduplicar pelo prontuário textual normalizado
  dentro de cada grupo oficial.
- Em grupo oficial associado a vários códigos-fonte, deduplicar entre todos os
  códigos do grupo.
- Se o mesmo prontuário aparecer em grupos oficiais diferentes, contá-lo uma vez
  em cada grupo e registrar advertência agregada/factual, sem escolher setor
  verdadeiro.
- Ignorar a nomenclatura do leito no numerador. Paciente sem leito conta;
  pacientes diferentes no mesmo leito contam separadamente.
- Manter a partição 3A em Adulto 32 e Infantil 16. Para cada prontuário deduplicado:
  - usar faixa confiável quando as evidências confiáveis concordarem;
  - sem faixa confiável ou com faixas contraditórias, classificar como Infantil
    se qualquer variante normalizada do nome começar literalmente com `RN`;
  - caso contrário, classificar como Adulto;
  - registrar agregadamente o uso do fallback `RN` sem tornar a medição
    inelegível.
- Tratar nome variável para o mesmo prontuário como um paciente contado uma vez,
  com advertência agregada e todas as variantes visíveis somente na página
  autenticada do censo exato.
- Tratar identificação incompleta como caso visível não contado, sem chamá-lo de
  conflito.
- Manter linhas vagas, reservadas, em manutenção e isolamento como estados
  operacionais informativos; não entram no numerador e não reduzem capacidade.
- Quando a mesma nomenclatura de leito tiver estados diferentes, mostrar todos
  os registros e a mensagem factual `estados informados para o mesmo leito`,
  sem escolher vencedor e sem afetar a taxa.
- Simplificar `/beds` v5:
  - um único card de capacidade oficial;
  - `Pacientes identificados` como numerador;
  - `Saldo da capacidade oficial`, excedente e taxa;
  - cobertura 39/43 como metadado secundário;
  - uma listagem por paciente deduplicado com todos os leitos informados e bloco
    separado de estados operacionais.
- Remover da apresentação v5 os rótulos genéricos `conflito`,
  `registro divergente` e `não autoritativo`; preservar páginas históricas v1–v4.
- Persistir somente contagens agregadas e faixas etárias permitidas; nunca nome,
  prontuário, leito, variantes nominais ou idade exata no histórico, resumo,
  logs ou relatórios.
- Preservar v1–v4, exact-run, autenticação, fluxo clínico, capacidades, política
  CO, aliases e ausência de backfill.

## Capabilities

### Modified capabilities

- `occupancy-measurement-history`: adiciona algoritmo v5 por paciente
  identificado, deduplicação por grupo, fallback etário e reconciliação privada.
- `daily-occupancy-summary`: inclui medições v5 elegíveis e contadores agregados
  de qualidade sem reinterpretar dias anteriores.
- `bed-status-capacity-view`: remove redundância v5 e apresenta pacientes
  deduplicados, leitos informados e estados operacionais factuais.
- `versioned-sector-capacity-catalog`: permite catálogo integral futuro que
  declara `occupancy-v5`, mantendo 43/48/47/39/4/666/666 e aliases 48/48.

### New capabilities

Nenhuma. A mudança evolui as quatro capacidades existentes.

## Scope

### Included

- Função determinística de identidade válida e deduplicação em memória.
- Materialização v5 imutável, grupos e resumo diário.
- Migration aditiva para permitir qualidade v5 nos campos existentes.
- Reconciliação agregada v5 versionada e fechada.
- Catálogo JSON v5 integral e dry-run/ativação idempotentes.
- Apresentação autenticada exact-run e ADR-0007.
- Testes sintéticos de mãe/RN, sem leito, mesmo leito, duplicação, nomes
  variantes, prontuário entre grupos, estados operacionais e privacidade.
- Release imutável, deploy sem ativação, publicação futura e primeira validação
  v5 somente com agregados seguros.

### Excluded

- Backfill ou recálculo de v1–v4.
- Alteração de capacidades, CO, 3A 32/16 ou indicador combinado 3A total.
- Pareamento mãe–criança ou inferência de parentesco.
- Escolha autoritativa de setor, nome, leito ou estado operacional.
- Deduplicação clínica fora da ocupação e `/beds`.
- Mudança do gate de 40 setores, scraping, scheduler ou fluxo clínico.
- Celery, Redis, microserviços ou nova infraestrutura.
- Persistência de identidade na medição ou no resumo.

## Dependencies and sequencing

O change depende da RC10 e do catálogo v4 já publicados. O change
`make-occupancy-quality-actionable` permanece histórico e não deve ser
reinterpretado. Sua task 4.7 fica pausada até que este change defina a correção
forward. V5 deve usar nova release e novo catálogo futuro; deploy, migration,
dry-run, publicação e primeiro censo permanecem etapas separadas.

## Success Criteria

1. Uma linha com prontuário numérico e nome válido conta mesmo sem leito.
2. Dois prontuários distintos no mesmo leito contam duas pessoas.
3. O mesmo prontuário no mesmo grupo conta uma vez e conserva todos os leitos e
   nomes somente na renderização autenticada.
4. O mesmo prontuário em grupos diferentes conta uma vez em cada grupo e gera
   advertência factual agregada.
5. A 3A usa faixa confiável; no fallback, prefixo literal `RN` vai para Infantil
   e demais nomes para Adulto.
6. Vaga, reserva, manutenção e isolamento não entram no numerador nem reduzem a
   capacidade e não são chamados de conflito.
7. A reconciliação fecha e não persiste nem registra identidade.
8. `/beds` v5 exibe um único valor de capacidade e usa terminologia de pacientes
   identificados e saldo oficial.
9. Catálogo v5 preserva 43/48/47/39/4/666/666, CO, 3A e aliases 48/48.
10. V1–v4, exact-run, autenticação, fluxo clínico e história permanecem intactos.
