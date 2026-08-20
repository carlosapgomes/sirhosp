# ADR-0004 — Correção da lotação oficial: CO fora da taxa e partição etária da 3A

## Status

Accepted

## Contexto

A ADR-0003 publicou um catálogo integral com vigência em `2026-08-19` que
tratava o Centro Obstétrico (CO) como setor `standard` com capacidade 8 e a
Obstetrícia 3A como `linked_slots_pending` com capacidade 32. Após essa
publicação, a diretoria deliberou duas correções de premissa: o CO não deve
participar de nenhum percentual de ocupação e a Enfermaria 3A deve contribuir
como dois setores virtuais calculáveis, separados pela idade do ocupante
(Adulto 32 e Infantil 16), sem depender do mapeamento cama-berço.

O censo legado já transporta a coluna `Idade` até o CSV temporário da
extração, mas o processamento descartava esse valor. A correção exige,
portanto, preservar apenas a faixa etária normalizada necessária ao cálculo,
particionar o código `654` no catálogo, materializar uma nova versão de
algoritmo e apresentar a lotação corrigida sem reescrever o histórico `v1`.

Esta ADR registra a deliberação e substitui **somente** as decisões de CO e
3A da ADR-0003. As demais decisões — fotografia integral versionada,
vigência diária em `America/Bahia`, imutabilidade, ausência de backfill,
privacidade dos agregados e rollback funcional — permanecem válidas.

## Decisão

- **CO fora de qualquer percentual (opção A da diretoria)**: o CO continua
  agrupando os códigos `20`, `1110`, `1112`, `1114` e `1116` em uma única
  série, com política `unrated` e sem capacidade declarada. Suas contagens
  brutas por status e seus componentes permanecem disponíveis para
  apresentação e auditoria, mas o CO não possui percentual, numerador,
  capacidade ou excedente e não participa da taxa hospitalar.
- **3A particionada por faixa do ocupante, sem pareamento**: cada linha
  ocupada do código `654` é classificada exclusivamente pela sua própria
  faixa etária persistida. Menor de 12 anos entra em `OBST-3A-INFANTIL`
  (capacidade 16); 12 anos ou mais entra em `OBST-3A-ADULTO` (capacidade 32).
  Não há pareamento mãe-criança nem deduplicação por prontuário; cada linha
  conta exatamente uma vez.
- **Faixa etária mínima persistida, nunca idade exata**: o snapshot preserva
  somente `under_12`, `age_12_or_over`, `unknown` ou `not_applicable`. O
  valor bruto de idade, nome e prontuário não entram nas tabelas históricas de
  ocupação.
- **Idade desconhecida exclui só a linha do ponto**: ocupado com faixa
  `unknown` fica fora dos numeradores da 3A e da taxa hospitalar, enquanto as
  capacidades 32, 16 e 666 permanecem fixas no denominador. A medição
  persiste somente a contagem agregada de linhas omitidas e a flag de
  classificação parcial (`age_partial`).
- **Censo parcial excluído das médias oficiais diárias**: uma medição v2 com
  ao menos uma linha ocupada de faixa desconhecida não participa de média,
  mínimo, máximo ou excedente diário. O resumo preserva total, elegíveis e
  excluídas; se nenhuma medição do dia for elegível, os campos oficiais ficam
  nulos, sem fabricar zero.
- **`occupancy-v2` e cobertura por setor oficial**: medições materializadas
  sob o catálogo corrigido registram `algorithm_version=occupancy-v2`,
  cobertura oficial 39 de 43 setores com capacidade e 39 de 43 calculáveis, e
  capacidade conhecida e calculável 666. As medições e resumos `occupancy-v1`
  permanecem com seus valores históricos (44/47, 43/47, 658 e 626) sem
  recálculo.
- **Apresentação `/beds` com dados prontos**: a página renderiza apenas
  valores persistidos — CO sem taxa, duas linhas oficiais da 3A, agrupamento
  auxiliar de apresentação para posições sem classificação etária, alerta
  agregado de taxa parcial e cobertura oficial — sem recalcular percentual ou
  cobertura em view ou template.
- **Vigência pós-deploy com ativação separada**: o catálogo corrigido é
  publicado somente para a primeira data estritamente futura em
  `America/Bahia` após o deploy da release corretiva, por comando explícito
  com dry-run. Nenhum deploy ou migration ativa o catálogo automaticamente e
  nenhum censo anterior é recalculado.
- **Substituição parcial da ADR-0003**: esta ADR substitui apenas as decisões
  de CO e 3A da ADR-0003 e preserva suas decisões de imutabilidade, fotografia
  completa, vigência diária, não-backfill, privacidade e rollback funcional.

## Alternativas Consideradas

1. **Manter CO no percentual (status quo)**
   - Vantagens: nenhuma mudança de cálculo.
   - Desvantagens: a taxa hospitalar continuaria contaminada pela capacidade 8
     e pelo percentual do CO, contrariando a deliberação da diretoria.
   - Motivo da rejeição: o indicador oficial perderia a correção aprovada.

2. **Parear mãe-criança ou deduplicar por prontuário na 3A**
   - Vantagens: aparente redução de linhas repetidas.
   - Desvantagens: inventaria uma relação não registrada no censo e poderia
     descartar linhas válidas com o mesmo prontuário.
   - Motivo da rejeição: cada linha é classificada pela própria faixa, sem
     inferência sobre outras linhas.

3. **Tratar idade desconhecida como adulto**
   - Vantagens: numerador sempre completo.
   - Desvantagens: fabricaria classificação etária inexistente no censo.
   - Motivo da rejeição: a deliberação manda excluir somente a linha
     desconhecida e sinalizar a taxa como parcial.

4. **Excluir a capacidade junto da linha desconhecida**
   - Vantagens: denominador proporcional ao numerador.
   - Desvantagens: produziria denominador variável e comparabilidade instável
     entre censos.
   - Motivo da rejeição: as capacidades 32, 16 e 666 permanecem fixas.

5. **Reclassificar ou fazer backfill do catálogo `2026-08-19` e das medições v1**
   - Vantagens: série histórica "corrigida" retroativamente.
   - Desvantagens: reescreveria o passado com premissa posterior e apagaria a
     auditoria da regra vigente à época.
   - Motivo da rejeição: viola imutabilidade, fotografia completa e
     não-backfill da ADR-0003.

## Consequências

### Positivas

- A taxa hospitalar passa a refletir a deliberação: CO fora do percentual e
  os 48 leitos oficiais da 3A contribuindo como Adulto 32 e Infantil 16.
- Histórico reproduzível entre duas versões de algoritmo: `occupancy-v1` e
  `occupancy-v2` coexistem sem recálculo.
- Idade desconhecida fica auditável de forma agregada, com alerta seguro na
  apresentação e exclusão explícita das médias diárias.
- Privacidade preservada: apenas a faixa normalizada é persistida, nunca a
  idade exata ou identificadores de paciente.

### Negativas / Trade-offs

- Censo com linha ocupada de faixa desconhecida fica fora das médias oficiais
  diárias, reduzindo temporariamente a base estatística.
- Formatos etários novos do legado tornam-se `unknown` até classificação
  futura; nunca há inferência automática.
- A correção exige nova release e ativação operacional separada em data
  futura, com mais cerimônia que uma edição de tabela.

## Riscos e Mitigações

- **Idade desconhecida reduzir o numerador pontual da 3A**: alerta explícito,
  contagem agregada persistida e exclusão do censo das médias diárias.
- **Cobertura oficial confundida com cobertura de código-fonte**: campos e
  rótulos separados (`setores oficiais` vs diagnóstico de extração).
- **Lookup de código sobrescrever uma das partições na apresentação**:
  mapeamento por `(código, faixa)` garante uma linha em um único setor.
- **Regressão da apresentação v1**: despacho por catálogo persistido e testes
  de regressão de CO histórico, cobertura 44/47 e fallback sem medição.
- **Ativação acidental durante deploy**: dry-run obrigatório e ativação
  somente por comando explícito para data estritamente futura.

## Referências

- ADR-0003 — catálogo temporal de capacidade e materialização imutável de
  ocupação (substituída parcialmente nas decisões de CO e 3A).
- Change OpenSpec `correct-co-3a-occupancy-policy` (proposal, design, specs
  delta e tasks).
- Implementação: `apps/census/occupancy.py`, `apps/census/views.py`,
  `apps/census/templates/census/bed_status.html`,
  `apps/census/models.py` e migrations aditivas.
