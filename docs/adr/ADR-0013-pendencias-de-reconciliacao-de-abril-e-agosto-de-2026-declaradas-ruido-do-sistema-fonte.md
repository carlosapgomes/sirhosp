# ADR-0013: Pendências de reconciliação de abril e agosto de 2026 declaradas ruído do sistema fonte

## Status

- **Status:** Accepted
- **Data:** 2026-10-25
- **Decisores:** Operação hospitalar (operador do portal)
- **Consultados:** Engenharia SirHosp
- **Informados:** Revisores do gráfico histórico de saídas

## Contexto

O defeito de espelhamento pré-28/08/2026 exigiu re-extração em massa das
internações de abril e agosto de 2026. Boa parte das altas extraídas do fonte
nesses meses referencia pacientes e episódios que o espelho re-extraído não
contém (ou contém em forma diferente), ficando `pending` sem âncora
reconciliável.

Após a ativação completa da coorte `mirror_exits`
(change `mirror-exit-backfill-cohort`, arquivada 2026-10-25), o quadro em
produção é:

- pendências abril: 1.286; agosto: 998 (total 2.284), concentradas nesses
  meses legados;
- pipeline corrente saudável: set/2026 e out/2026 com ~99% das altas
  reconciladas no dia (`pending` residual 12 e 0);
- a massa restante de abril/agosto está no bucket de revisão manual
  (patient_not_found, mirror_patient_not_found, admission_not_found,
  ambiguous), para a qual não existe prova segura de vinculação.

## Decisão

As 2.284 pendências de reconciliação de abril e agosto de 2026 são
**declaradas ruído do sistema fonte naquele período**:

- não serão perseguidas nem curadas manualmente;
- nenhuma nova coorte automática será construída para elas (sem prova
  segura, o reconciliador permanece fail-closed);
- os registros permanecem no banco com seus status atuais — a decisão é
  interpretiva e de documentação, sem mutação de dados;
- a lacuna residual entre sumários e saídas canônicas nesses dois meses é
  aceita como artefato conhecido e documentado do fonte legado.

Exclusões explícitas (fora desta ADR):

- o gotejamento corrente de ~40 altas/mês `admission_not_found`;
- óbitos com apenas data (crescimento perpétuo), tratados na change
  dedicada ao critério de óbito por data.

## Alternativas Consideradas

1. **Construir coortes adicionais com evidência mais fraca**
   - **Vantagens**: fecharia a lacuna dos meses legados.
   - **Desvantagens**: violaria o princípio fail-closed da reconciliação
     canônica (ADR-0009); criaria vínculos sem procedência confiável em
     dado clínico histórico.
   - **Por que não escolhida**: risco clínico e de auditabilidade sem
     contrapartida operacional — os meses correntes estão íntegros.

2. **Curadoria manual das 2.284 pendências**
   - **Vantagens**: precisão máxima.
   - **Desvantagens**: custo alto e irrepetível; a fonte legada não permite
     confirmar a maioria dos vínculos de qualquer forma.
   - **Por que não escolhida**: custo/benefício desfavorável; o valor
     analítico de abril/agosto não justifica.

3. **Fechar os registros com um status "ruído" no banco**
   - **Vantagens**: sinalizaria a decisão no próprio dado.
   - **Desvantagens**: exige mudança de schema/status sem consumidor atual;
     a decisão é sobre interpretação, não sobre o registro.
   - **Por que não escolhida**: YAGNI; esta ADR é a fonte canônica da
     decisão. Se um consumidor real surgir, nova mudança pode propô-lo.

## Consequências

### Positivas

- o backlog de revisão manual deixa de ser dívida aberta: os itens de
  abril/agosto têm veredito registrado e rastreável;
- o gráfico histórico de abril/agosto passa a ser lido com nota de rodapé
  conhecida em vez de suspeita de bug;
- o reconciliador mantém o comportamento fail-closed sem pressão para
  "fechar números".

### Negativas/Trade-offs

- a série canônica de saídas de abril/agosto de 2026 subestima a
  realidade daqueles meses permanentemente;
- comparações mês-a-mês que cruzem o período legado precisam dessa ADR
  como contexto.

### Riscos e Mitigações

- **Análises futuras ignorarem o artefato**: mitigado por esta ADR e pela
  menção na archive da change `mirror-exit-backfill-cohort`.
- **Fonte fornecer correção retrospectiva desses meses**: nova decisão
  será necessária (e nova coorte pode ser proposta com a evidência que
  vier a existir).
