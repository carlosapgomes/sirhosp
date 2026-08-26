# Design: Ocupação oficial por pacientes identificados

## Context

V3 e v4 adotaram `(setor de origem, leito normalizado)` como identidade física.
Essa escolha é útil para fotografar como o sistema de origem nomeia posições,
mas a produção mostrou que não representa a lotação clínica: pacientes podem
não ter leito informado, mãe e RN podem compartilhar o mesmo leito e um setor
pode usar nomenclaturas operacionais fora do cadastro oficial.

O censo v4 analisado tinha uma ponte alternativa simples e integral:

```text
647 linhas com nome e prontuário válidos
- 5 linhas repetidas pelo mesmo prontuário no mesmo grupo
= 642 pacientes identificados
= 597 em grupos standard + 45 em grupos unrated
```

A posição física v4 gerou 561/666, saldo 109 e excedente 4. A simulação por
paciente gerou 597/666, saldo setorial 90 e excedente 21. Não se versiona essa
simulação nem seus dados-fonte; ela apenas fundamenta o novo algoritmo.

## Goals / Non-goals

### Goals

- Fazer o numerador representar pacientes identificados no grupo oficial.
- Contar paciente sem leito e pacientes distintos que compartilham leito.
- Deduplicar prontuário dentro do grupo sem esconder evidência na UI.
- Manter a partição etária 3A com fallback RN determinístico.
- Separar pacientes, identificação incompleta e estados operacionais.
- Simplificar linguagem e cards de `/beds`.
- Preservar privacidade agregada, história e operação fase 1.

### Non-goals

- Corrigir o sistema de origem ou atribuir leitos.
- Deduplicar pacientes no domínio clínico.
- Parear mãe e RN.
- Escolher setor verdadeiro quando o mesmo prontuário aparece em dois grupos.
- Alterar capacidade ou políticas publicadas.
- Recalcular medições anteriores.

## Decisions

### 1. V5 usa atribuição paciente→grupo, não posição→grupo

Para v5, a nomenclatura do leito é ignorada pelo cálculo oficial. Cada linha é
primeiro classificada como:

- `identified_patient`: prontuário e nome válidos;
- `incomplete_identity`: há evidência nominal/registral, mas a identidade não
  satisfaz o contrato;
- `operational_state`: linha sem identidade de paciente que representa vaga,
  manutenção/limpeza, reserva, isolamento ou fallback operacional.

Somente `identified_patient` participa do numerador. O leito continua disponível
em memória para a página autenticada.

**Alternativa rejeitada:** corrigir apenas a normalização física. Ela continuaria
omitindo os 21 pacientes sem leito e subcontando pessoas distintas no mesmo
leito.

### 2. Identidade válida é estrita e textual

Normalização de prontuário:

```text
strip externo -> sequência não vazia somente de dígitos
```

O valor permanece string; zeros à esquerda são significativos. Não há conversão
para inteiro nem remoção de pontuação. Um prontuário alfanumérico é inválido.

Normalização de nome:

```text
strip externo -> uppercase -> espaços internos colapsados
```

O nome deve ser não vazio e não corresponder aos marcadores operacionais
mantidos pelo parser: `DESOCUPADO`, `VAZIO`, `LIMPEZA`, `RESERVA` ou
`ISOLAMENTO`. A função pura de v5 centraliza esse contrato sem alterar snapshots
históricos ou o fluxo clínico.

### 3. Deduplicação ocorre dentro do grupo oficial

Depois do mapeamento por código e, quando necessário, da resolução etária, a
chave de contagem é:

```text
(group_stable_key, normalized_record)
```

Um grupo compartilhado, como Cardio, deduplica o prontuário entre todos os seus
códigos-fonte. Nomes e leitos não fazem parte da chave.

Se o prontuário aparece em grupos oficiais distintos, ele conta uma vez em cada
grupo. A medição persiste somente o número agregado de prontuários presentes em
múltiplos grupos. A UI exact-run mostra em cada paciente a mensagem factual
`Prontuário informado em mais de um setor oficial neste censo`, sem escolher um
grupo verdadeiro.

Essa decisão mantém a soma dos grupos igual ao hospital e segue a regra
operacional de lotação por setor. Não há deduplicação hospitalar global.

### 4. A 3A deduplica antes de escolher Adulto ou Infantil

Código 654 permanece dividido em capacidades 32 e 16. Para cada prontuário
identificado, todas as linhas e variantes de nome são reunidas antes da
atribuição:

1. coletar apenas faixas persistidas confiáveis (`under_12` e
   `age_12_or_over`);
2. se o conjunto confiável tiver exatamente uma faixa, usá-la, mesmo que outras
   linhas estejam `unknown`;
3. se não houver faixa confiável ou houver as duas faixas, aplicar fallback;
4. fallback Infantil se qualquer nome normalizado começa literalmente com
   `RN`; caso contrário Adulto.

`R.N.` e nomes apenas semelhantes a RN não satisfazem o prefixo literal. O
fallback e a divergência etária geram contagens agregadas de qualidade, mas a
medição continua elegível. Nunca persistir nome ou idade exata.

**Alternativa rejeitada:** manter paciente desconhecido fora dos dois grupos.
Isso repete a subcontagem que o change pretende remover.

### 5. Nomes variantes não mudam identidade

O prontuário válido é a chave. Se suas linhas têm mais de um nome normalizado:

- conta uma vez dentro do grupo;
- incrementa contador agregado de prontuários com variação nominal;
- a UI autenticada mostra um paciente e todas as variantes informadas;
- nenhuma variante é declarada autoritativa;
- nenhuma variante entra em histórico, log ou relatório.

### 6. Leitos e estados permanecem evidência descritiva

A apresentação v5 deriva duas coleções efêmeras do censo exato:

```text
Pacientes identificados
  prontuário deduplicado
  variantes de nome
  todos os leitos informados, incluindo "sem leito informado"
  códigos/aliases de origem

Estados operacionais
  cada linha vaga, reservada, manutenção ou isolamento
  leito informado, quando houver
```

Se pacientes diferentes informam o mesmo leito, ambos aparecem e contam. A UI
pode informar `N pacientes informados com o mesmo leito`. Se a mesma
nomenclatura operacional aparece com estados diferentes, todas as linhas
aparecem e a UI informa `N estados informados para o mesmo leito`. Nenhum desses
casos altera o numerador ou recebe `conflito`, `registro divergente` ou
`não autoritativo`.

Linhas com identificação incompleta aparecem em bloco próprio e não contam.

### 7. Reconciliação v5 é agregada, fechada e privada

V5 usa novo schema de reconciliação. A allowlist contém somente inteiros,
booleanos e mapas de status com chaves fixas. A ponte principal fecha por
atribuições de linha a grupo:

```text
valid_identity_rows =
    duplicate_identity_rows_within_group
  + standard_identified_patients
  + unrated_identified_patients
  + linked_pending_identified_patients
  + unmapped_identified_patients
```

Como um prontuário em grupos diferentes nasce de linhas/grupos distintos e
conta em cada grupo, ele não é removido da ponte; recebe contador separado
`cross_group_record_count`. Contadores adicionais:

- `incomplete_identity_rows`;
- `name_variant_patient_count`;
- `rn_fallback_patient_count`;
- `age_conflict_fallback_patient_count`;
- linhas operacionais por status;
- linhas repetidas consolidadas dentro do grupo;
- pacientes sem leito informado.

Nenhum valor identificável é persistido. Erro de fechamento aborta a transação.

### 8. Qualidade v5 informa sem excluir

Toda medição v5 materializada permanece elegível para resumo diário. O flag
existente de qualidade é permitido para v5 por migration aditiva e fica true
quando houver:

- identificação incompleta;
- prontuário em múltiplos grupos;
- nomes variantes;
- fallback RN ou fallback adulto por idade não confiável;
- faixa confiável contraditória;
- paciente identificado em código unmapped.

Estados operacionais, leitos compartilhados e ausência de leito não são por si
só falhas de contagem: ausência de leito recebe contador informativo, mas o
paciente conta. O resumo diário reutiliza o contador agregado de medições com
ressalva, sem backfill e sem alterar v4.

### 9. Capacidade, saldo e excedente mantêm aritmética setorial

Para cada grupo `standard`:

```text
occupied = pacientes identificados únicos no grupo
rate = occupied / official_capacity
balance = max(official_capacity - occupied, 0)
excess = max(occupied - official_capacity, 0)
```

Hospital soma `occupied`, `balance` e `excess` separadamente. Não há compensação
entre setores. Percentuais acima de 100% são válidos. Grupos `unrated` listam
pacientes, mas não têm capacidade, saldo, taxa ou excedente.

### 10. `/beds` v5 remove redundância e linguagem de autoridade

Resumo oficial v5:

- `Capacidade oficial` — um único card;
- `Pacientes identificados`;
- `Saldo da capacidade oficial` — não chamado vaga nominal;
- `Excedente`;
- `Taxa de ocupação`;
- `39 de 43 setores com capacidade e cálculo; 4 fora da taxa` como metadado.

A página não exibe cards separados `Capacidade conhecida` e
`Capacidade calculável` em v5. V1–v4 mantêm apresentação histórica.

A lista passa a `Setores, pacientes e estados de leitos`. Cada componente do
grafo catálogo↔origem mantém capacidade oficial e aliases, mas apresenta:

- pacientes deduplicados por grupo, com todas as variantes/leitos;
- identificação incompleta;
- estados operacionais por código-fonte;
- mensagens factuais de repetição entre grupos, leitos e estados.

Autenticação, links de paciente e exact-run permanecem. PHI existe apenas no
HTML autenticado e na memória da requisição.

### 11. V5 é correção forward e catálogo integral

O documento v5 copia a estrutura oficial v4, altera somente o algoritmo para
`occupancy-v5` e recebe hash próprio. Mantém 43 grupos, 48 memberships, 47
códigos, 39 standard, quatro unrated, 666/666, aliases 48/48, CO e 3A.

Build, migration e deploy não publicam catálogo. Após release imutável:

1. dry-run para data futura;
2. publicação atômica explícita;
3. v4 continua aplicável até meia-noite local;
4. primeiro censo completo v5 é validado somente com agregados;
5. v1–v4 permanecem imutáveis e sem backfill.

### 12. O defeito físico v4 permanece histórico

Não alterar a semântica persistida de `occupancy-v4` nem recalcular medições. A
nova apresentação v5 não usa o classificador posição-leito para o numerador ou
para estados operacionais. Testes devem caracterizar que uma única linha
operacional v5 é exibida como seu estado, não como conflito. Não fazer refactor
amplo do motor v3/v4.

## Data model

Mudanças esperadas:

- adicionar constante/dispatch `occupancy-v5`;
- migration aditiva alterando a constraint de `quality_warning` para aceitar v4
  ou v5 e textos/metadados necessários;
- reutilizar campos parent/group existentes;
- reconciliação v5 em novo schema JSON allowlisted;
- nenhum campo de identidade e nenhum backfill;
- novo JSON integral de catálogo, sem editar os anteriores.

## Privacy and security

- Prontuários e nomes são usados apenas em memória na materialização e na
  apresentação exact-run.
- Histórico, resumo, reconciliação, logs, exceptions e relatórios recebem apenas
  agregados.
- Testes usam dados sintéticos.
- `/beds` continua `login_required`; anônimo continua 302.
- Screenshot e dados reais não entram no repositório ou relatórios.

## Slice strategy

1. **CIPOO-S1 — Medição v5:** identidade, deduplicação, 3A, reconciliação,
   qualidade e resumo diário; até cinco arquivos.
2. **CIPOO-S2 — Catálogo v5:** allowlist, JSON integral, dry-run e ativação
   idempotente; até três arquivos.
3. **CIPOO-S3 — `/beds` e ADR:** apresentação paciente/estado, cards e ADR-0007;
   até cinco arquivos.
4. **CIPOO-S4 — Auditoria/release/deploy:** gates, runbook, release imutável,
   backup e deploy sem ativação.
5. **CIPOO-S5 — Publicação futura:** confirmar v4, dry-run, publicação v5 futura
   e prova de ausência de backfill.
6. **CIPOO-S6 — Primeiro censo/arquivo:** validar agregados v5, UI, fluxo
   clínico, sincronizar specs e arquivar.

Três slices de código são o mínimo que mantém domínio, artefato de catálogo e
experiência autenticada verificáveis sem exceder o limite de arquivos. Operações
ficam separadas porque deploy, ativação e primeira observação têm stop rules e
janelas temporais diferentes.

## Risks / trade-offs

- **Prontuário incorreto conta paciente:** validação numérica e advertências de
  repetição reduzem, mas não provam identidade clínica.
- **Mesmo prontuário em dois setores infla hospital:** decisão explícita para
  preservar soma setorial; advertência factual torna o caso acionável.
- **Fallback RN classifica por nome:** somente quando idade é ausente/conflitante,
  com contador agregado e testes de prefixo literal.
- **Nome operacional com prontuário:** contrato exige nome válido e impede
  contagem silenciosa.
- **Listagem expõe variantes:** somente autenticada, exact-run e efêmera.
- **Mudança grande de série:** novo algoritmo/data futura e sem backfill tornam a
  quebra explicitamente versionada.

## Deployment and activation

- Próxima release candidata imutável, preferencialmente RC11.
- Backup protegido e migrations antes da aplicação, sem catálogo v5.
- Dry-run e publicação em operações separadas do deploy.
- Vigência à meia-noite futura em `America/Bahia`.
- Após vigência v5, correções são forward; não retornar funcionalmente à RC10.
