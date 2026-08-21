## Context

O catálogo publicado para `2026-08-19` materializa `occupancy-v1`: Centro
Obstétrico (`CO`) é `standard` com capacidade 8 e `OBST-3A` possui capacidade
32 com política `linked_slots_pending`. A diretoria deliberou depois da
publicação que CO deve ter o mesmo tratamento dos setores sem taxa e que a 3A
deve contribuir como dois setores virtuais, Adulto 32 e Infantil 16, separados
pela idade de cada ocupante.

O XLSX legado já contém a coluna `Idade`, e o extrator a inclui no CSV
temporário. `parse_census_csv` e `CensusSnapshot`, porém, descartam esse valor. O
materializador atual agrega apenas código, nome e status; o catálogo proíbe o
mesmo código em dois grupos; e `/beds` associa detalhes aos grupos apenas pelo
código. A correção é, portanto, uma evolução coordenada de ingestão, catálogo,
algoritmo, histórico, resumo e apresentação, não apenas uma troca de JSON.

Os stakeholders são diretoria, qualidade, gestão de leitos e operadores do
censo. Permanecem obrigatórias a imutabilidade histórica, a vigência diária em
`America/Bahia`, a privacidade dos agregados e a disponibilidade do fluxo
clínico. Não serão adicionados Celery, Redis, serviços ou processos agendados.

## Goals / Non-Goals

**Goals:**

- preservar uma faixa etária mínima e determinística em cada snapshot novo;
- excluir CO de percentuais individuais e hospitalares, mantendo dados brutos;
- calcular Adulto 32 e Infantil 16 no código `654` sem parear mãe e criança;
- suportar um código-fonte particionado de forma exclusiva entre grupos;
- materializar `occupancy-v2` sem alterar `occupancy-v1`;
- sinalizar taxa pontual parcial quando idade ocupada for desconhecida;
- excluir esse censo parcial das médias oficiais diárias;
- mostrar cobertura oficial 39/43 e capacidades 666/666;
- publicar a correção somente em catálogo integral futuro, após o deploy.

**Non-Goals:**

- reclassificar ou recalcular catálogos, medições ou resumos existentes;
- mudar o setor clínico, a trajetória, os filtros ou a ingestão de pacientes;
- persistir idade exata em tabelas históricas de ocupação;
- inferir idade por nome, prontuário, especialidade, mãe ou outra linha;
- deduplicar linhas que compartilham prontuário;
- atribuir faixa etária a vaga, reserva, manutenção ou isolamento;
- criar indicador agregado adicional `3A total 48`;
- ativar catálogo ou fazer deploy automaticamente durante migrations;
- criar backfill, scheduler ou infraestrutura assíncrona adicional.

## Decisions

### 1. Normalizar uma faixa etária mínima na entrada

Adicionar ao `CensusSnapshot` uma classificação persistida com quatro estados:

```text
under_12
age_12_or_over
unknown
not_applicable
```

A classificação usa apenas `Idade` e o status da própria linha:

- linha não ocupada recebe `not_applicable`;
- inteiro menor que 12 recebe `under_12`;
- inteiro igual ou maior que 12 recebe `age_12_or_over`;
- `Nm` e `NmDd`, normalizados sem diferença de caixa e espaços, são convertidos
  em meses/dias e comparados ao limite de 12 anos;
- valor vazio, negativo, com unidade desconhecida ou estruturalmente inválido
  recebe `unknown`.

A ambiguidade do inteiro usado tanto para anos quanto no dia do nascimento não
muda o resultado abaixo de 12. O limiar é estrito: idade exatamente 12 pertence
a Adulto. Snapshots históricos recebem default seguro `unknown` e não são
backfilled; `occupancy-v1` ignora o novo campo.

Persistir a faixa, em vez da idade exata, aplica minimização de dados e torna a
classificação reproduzível sem copiar uma informação demográfica desnecessária
para o histórico agregado.

**Alternativas rejeitadas:** consultar nascimento no cadastro de pacientes
introduziria acoplamento e poderia divergir do censo capturado; persistir a
string bruta ampliaria exposição sem necessidade; classificar durante a query
sem persistência impediria auditoria do dado usado.

### 2. Representar partições etárias no catálogo temporal

Adicionar a cada `CapacitySectorMembership` um seletor com default `all` e duas
partições suportadas:

```text
all
under_12
age_12_or_over
```

Um código pode ter uma única associação `all` ou exatamente as duas associações
etárias, nunca uma mistura, repetição ou conjunto incompleto. A validação do
JSON rejeita sobreposição antes da persistência e a constraint do banco garante
unicidade por catálogo, código e seletor. Essa regra mantém YAGNI: não haverá
DSL, regex, expressão arbitrária ou seletor por dado clínico.

A fotografia corrigida, em arquivo novo e sem sobrescrever o JSON inicial,
contém:

```text
43 setores oficiais
48 associações em 47 códigos-fonte
39 setores standard com capacidade
4 setores unrated
capacidade conhecida 666
capacidade calculável 666
```

Alterações principais:

| Chave | Capacidade | Política | Código/seletor |
| --- | ---: | --- | --- |
| `OBST-3A-ADULTO` | 32 | `standard` | `654/age_12_or_over` |
| `OBST-3A-INFANTIL` | 16 | `standard` | `654/under_12` |
| `CO` | - | `unrated` | cinco códigos com `all` |

Os outros 40 grupos preservam identidade, capacidade, política e membros da
fotografia inicial. CO continua uma única série e preserva os cinco componentes
brutos, mas não declara capacidade nem percentual.

**Alternativas rejeitadas:** hardcode do código `654` no serviço apagaria o
contexto temporal; criar códigos-fonte artificiais alteraria módulos clínicos;
associar o mesmo código sem seletor seria ambíguo.

### 3. Despachar o algoritmo pelo catálogo sem alterar o passado

O materializador passa a suportar dois caminhos explícitos:

```text
catálogo legado sem partições → occupancy-v1
catálogo corrigido com partições → occupancy-v2
```

`occupancy-v1` mantém integralmente a semântica atual. `occupancy-v2` inclui a
faixa etária observada, aplica o seletor antes de agregar e grava seletor,
contagens e versão do algoritmo nos snapshots imutáveis da medição. Uma nova
release implantada antes da vigência corrigida continua criando v1 sob o
catálogo anterior.

Para `654` em v2:

```text
ocupado + under_12       → numerador Infantil / 16
ocupado + age_12_or_over → numerador Adulto / 32
ocupado + unknown        → omitido dos dois numeradores e auditado
não ocupado              → não pertence a uma faixa etária
```

Cada linha ocupada conta uma vez. Prontuários iguais não são deduplicados e
nenhuma linha usa idade de outra pessoa. As capacidades 32 e 16 permanecem no
denominador mesmo quando houver idade desconhecida, conforme deliberação da
diretoria.

A medição v2 persiste contagem agregada de ocupados com idade desconhecida e um
marcador de classificação parcial. Ela ainda possui percentual pontual, formado
pelas linhas classificadas sobre capacidade 666, mas o valor é explicitamente
rotulado como parcial. Nenhum identificador ou idade individual entra no pai,
filhos, componentes ou logs.

**Alternativas rejeitadas:** assumir desconhecido como adulto inventaria dado;
invalidar toda a medição contrariaria a deliberação de excluir apenas a linha;
excluir a capacidade junto da linha produziria denominador variável.

### 4. Manter diagnósticos de código e adicionar cobertura oficial

Os campos históricos de cobertura por código-fonte permanecem disponíveis para
compatibilidade e qualidade da extração. Medições v2 também persistem cobertura
por setor oficial, calculada sobre a fotografia completa, sem contar grupos
sintéticos ou códigos desconhecidos:

```text
setores oficiais: 43
com capacidade: 39
com lotação calculável: 39
```

`/beds` usa essa cobertura oficial para v2. Medições v1 continuam exibindo seus
valores históricos 44/47, 43/47, 658 e 626. Não se reinterpretam colunas antigas
sem `algorithm_version`.

### 5. Excluir censos parciais das médias diárias

Toda medição continua persistida e contada para auditoria. Para v2, uma medição
com pelo menos um ocupado `654/unknown` não participa de média, mínimo, máximo
ou excedente oficial diário, nem no pai nem nos grupos. O resumo persiste:

- total de medições do dia;
- número elegível para cálculo diário;
- número excluído por classificação etária incompleta;
- primeira e última captura do conjunto auditável.

As estatísticas oficiais usam somente medições elegíveis, sempre com peso igual.
Se nenhuma for elegível, os campos oficiais ficam nulos; não se fabrica zero.
Resumos v1 mantêm todas as medições elegíveis e não são reconstruídos.

Essa decisão evita misturar taxas completas e parciais sem bloquear o censo
clínico ou apagar a evidência pontual.

### 6. Separar indicadores virtuais do detalhamento não classificável

Em `/beds`, uma medição v2 mostra duas linhas oficiais:

```text
Enfermaria 3A – Adulto
Enfermaria 3A – Infantil
```

Ocupados com faixa válida aparecem uma única vez na expansão correspondente.
Vagos, reservas, manutenção, isolamento e ocupados de idade desconhecida são
mostrados uma única vez em agrupamento auxiliar `3A – posições sem
classificação etária`, sem capacidade ou percentual. Esse agrupamento é apenas
de apresentação sobre os snapshots do run exato; não é um 44º setor oficial e
não entra no catálogo ou nas médias.

CO mostra contagens e componentes em uma linha única, com `Capacidade não
cadastrada` e `Não incluído na taxa de ocupação da unidade`, nunca 0% ou 675%.
A página apresenta alerta agregado quando a taxa v2 é parcial e a quantidade de
linhas omitidas, sem dados de paciente no texto do alerta.

O restante do sistema continua vendo `setor_codigo=654` e o nome original. Essa
restrição evita alterar domínio clínico por uma classificação criada apenas
para gestão de ocupação.

### 7. Preservar ativação futura e imutabilidade

O JSON inicial e o catálogo publicado para `2026-08-19` não são editados ou
removidos. Após o deploy da release corretiva, o operador executa dry-run do
novo documento e publica para a primeira data estritamente futura em
`America/Bahia`; a vigência começa à meia-noite dessa data.

Medições e resumos anteriores permanecem v1, ainda que reflitam a premissa
posteriormente corrigida. Não haverá backfill. Uma nova ADR substitui somente
as decisões de CO e 3A da ADR-0003; as decisões de fotografia integral,
vigência, imutabilidade, privacidade e rollback funcional permanecem válidas.

## Risks / Trade-offs

- **Idade desconhecida reduz o numerador pontual da 3A** → mostrar alerta
  explícito, persistir contagem omitida e excluir o censo das médias diárias.
- **Formato etário novo no legado** → classificar como `unknown`, nunca inferir,
  e monitorar somente contagem agregada para orientar change futuro.
- **Posições não ocupadas não têm faixa** → exibi-las uma vez em agrupamento
  auxiliar e não fingir que pertencem a Adulto ou Infantil.
- **Dois grupos usam o código `654`** → seletor limitado, validação integral e
  constraint impedem sobreposição e duplicação.
- **Cobertura oficial pode ser confundida com cobertura da extração** → manter
  diagnóstico de código separado e rotular explicitamente `setores oficiais`.
- **Catálogo v1 continua vigente até a nova meia-noite** → despacho por versão
  preserva comportamento coerente; a correção não é aplicada no meio do dia.
- **História v1 contém CO calculado e 3A pendente** → manter como fato auditável
  da regra vigente, sem recálculo ou apagamento.
- **Mudança cross-cutting crescer em excesso** → quatro slices enxutos, sem
  DSL, backfill, refactor global ou virtualização clínica.

## Migration Plan

1. Implantar migration aditiva e persistência da faixa etária normalizada; não
   alterar cálculo v1.
2. Implantar suporte de catálogo particionado e documento corrigido; validar o
   dry-run sem ativar a fotografia.
3. Implantar campos auditáveis, algoritmo v2 e resumo elegível; validar que o
   catálogo v1 ainda produz v1.
4. Implantar apresentação v2 e ADR substitutiva, preservando fallback e UI v1.
5. Executar quality gate completo e auditoria de privacidade sem dados reais.
6. Publicar release imutável; não ativar catálogo durante deploy ou migration.
7. Depois do deploy, escolher a primeira data futura local, executar dry-run e
   confirmar 43 setores, 48 associações, 47 códigos distintos e 666/666.
8. Ativar o catálogo para essa data e validar que nenhum censo anterior foi
   recalculado.
9. No primeiro censo completo v2, conferir CO sem taxa, duas linhas da 3A,
   cobertura 39/43 e alerta agregado caso haja idade desconhecida.

Rollback funcional:

- voltar a aplicação para release anterior ou desabilitar apresentação v2;
- não remover migrations, catálogo, medições ou resumos;
- não editar a versão futura após publicação;
- nunca executar `down -v` ou backfill destrutivo.

## Open Questions

Não há questão funcional bloqueante. A data concreta de vigência será escolhida
operacionalmente após o deploy e deverá ser estritamente posterior ao dia local
da ativação em `America/Bahia`.
