# ADR-0005 — Duas realidades em `/beds`: capacidade oficial e posições do legado

## Status

Accepted

## Contexto

A página autenticada `/beds` apresentava duas bases legítimas com rótulos
semelhantes: capacidade oficial calculável e linhas brutas do censo legado.
Números como 636 ocupações oficiais, 667 linhas ocupadas, 666 unidades de
capacidade e 847 linhas de leito pareciam contraditórios, enquanto duplicatas
exatas do mesmo leito podiam inflar o indicador oficial. A gestão hospitalar
precisava enxergar, sem ambiguidade, tanto o indicador institucional baseado
na capacidade publicada quanto a fotografia física registrada no legado.

A ADR-0004 decidiu que prontuários não seriam deduplicados. Essa decisão
permanece válida para prontuários compartilhados por leitos distintos, mas não
define a identidade física de um mesmo leito repetido no censo. A presente ADR
registra a separação das duas realidades e a identidade física transversal, e
substitui somente as decisões afetadas da ADR-0004 sobre deduplicação.

## Decisão

- **Duas realidades simultâneas**: `/beds` exibe, sem abas, a seção
  `Capacidade oficial e ocupação` (catálogo publicado e medição imutável do
  censo exato) e a seção `Posições registradas no sistema legado` (fotografia
  física das posições do censo), com fontes, timestamps e vocabulários
  próprios e não intercambiáveis.
- **Identidade física por origem e leito**: a chave da posição é a identidade
  de origem normalizada (código do setor, ou nome do setor como fallback) mais
  o leito normalizado; prontuário isolado nunca é chave.
- **Duplicata exata versus prontuário em leitos distintos**: linhas com a
  mesma chave e a mesma assinatura observada colapsam em uma posição e contam
  como linhas extras; o mesmo prontuário em leitos diferentes permanece em
  duas posições, sem pareamento mãe-criança.
- **Conflito e identidade ausente como parcialidade**: mesma chave com
  assinaturas divergentes vira um único `Conflito no legado`, sem escolher
  paciente ou status; linha sem leito é linha sem identificação de posição,
  nunca posição. Conflito ou ocupado sem leito tornam a medição v3 parcial e
  inelegível para as médias oficiais diárias.
- **Disponibilidade por saldo setorial positivo**:
  `disponibilidade_i = max(capacidade_i - ocupação_i, 0)`; no hospital, soma
  dos saldos positivos e dos excedentes separadamente, sem compensação entre
  setores. O rótulo é `Disponibilidade na capacidade oficial`, com explicação
  de que é saldo calculado, não lista nominal de leitos vagos.
- **Preservação bruta e privacidade**: snapshots brutos permanecem intactos; a
  história agrega somente inteiros allowlisted; reconciliação e alertas nunca
  expõem nome, prontuário, leito ou idade.
- **Ativação futura v3**: `occupancy-v3` inicia somente por catálogo integral
  publicado para data futura explícita; v1 e v2 preservam seus valores
  persistidos e recebem indicação histórica, sem disponibilidade ou
  deduplicação v3 inventada.
- **Sem medição exata**: a seção oficial permanece `Pendente` e a física
  continua visível; medição antiga nunca é reutilizada como atual.
- **Correção forward**: divergências são corrigidas em versões futuras, nunca
  reescrevendo medições, catálogos ou ADRs anteriores.
- **Substituição parcial da ADR-0004**: esta ADR substitui somente as decisões
  da ADR-0004 sobre não deduplicação por prontuário, esclarecendo que
  prontuário isolado continua sem deduplicação; as decisões de CO fora da taxa
  e partição etária da 3A permanecem íntegras.

## Alternativas Consideradas

1. **Apenas renomear os cards atuais**
   - Vantagens: mudança mínima.
   - Desvantagens: não corrige a inflação por duplicatas nem explica conflitos.
   - Motivo da rejeição: o indicador oficial continuaria contaminado e a
     ambiguidade permaneceria.

2. **Deduplicar por prontuário entre leitos**
   - Vantagens: aparente redução de linhas repetidas.
   - Desvantagens: eliminaria posições legítimas e reintroduziria inferência
     mãe-criança.
   - Motivo da rejeição: prontuário isolado continua sem deduplicação.

3. **Abas que escondem uma das realidades**
   - Vantagens: menos informação por tela.
   - Desvantagens: esconder uma das fontes aumenta a confusão entre elas.
   - Motivo da rejeição: as duas realidades precisam estar simultaneamente
     visíveis.

4. **Calcular disponibilidade como capacidade menos ocupação global**
   - Vantagens: fórmula simples.
   - Desvantagens: excedente de um setor consumiria disponibilidade de outro.
   - Motivo da rejeição: a decisão exige saldo por setor sem compensação.

## Consequências

### Positivas

- Usuário distingue imediatamente capacidade oficial de posições do legado.
- Cada posição inequívoca aparece uma vez; duplicatas exatas não inflam o
  numerador v3; conflitos tornam a medição parcial e inelegível para as
  médias diárias.
- Reconciliação fechada e privada, sem dados identificáveis.
- v1 e v2 imutáveis e v3 iniciando somente em data local futura.

### Negativas / Trade-offs

- Página mais longa, com duas seções e uma ponte de reconciliação.
- Censos v3 com conflito ou linha sem leito ficam fora das médias diárias.
- Mais cerimônia operacional: ativação do v3 exige catálogo integral futuro.

## Referências

- ADR-0004 — correção da lotação oficial: CO fora da taxa e partição etária
  da 3A (substituída parcialmente nas decisões de deduplicação por
  prontuário; CO e 3A preservadas).
- Change OpenSpec `separate-official-and-physical-bed-realities` (proposal,
  design, specs delta e tasks).
- Implementação: `apps/census/occupancy.py`, `apps/census/views.py`,
  `apps/census/templates/census/bed_status.html`.
