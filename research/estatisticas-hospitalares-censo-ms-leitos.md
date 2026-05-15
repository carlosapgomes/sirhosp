# Estatísticas hospitalares segundo o manual do MS sobre censo hospitalar

Fonte analisada: `manual MS leitos.pdf`, Ministério da Saúde, Secretaria de Assistência à Saúde, Portaria SAS n.º 312/2002, “Padronização da Nomenclatura do Censo Hospitalar”.

## Resumo executivo

O SIRHOSP já possui uma boa base para ocupação atual e parte da permanência, porque coleta:

- censo de leitos por snapshot;
- paciente, prontuário, nome, setor, leito e especialidade;
- status básico do leito;
- dados demográficos;
- internações com data de admissão e data de alta quando conhecida;
- evoluções clínicas textuais.

Para calcular corretamente os indicadores do manual, ainda faltam principalmente:

- censo diário padronizado em horário fixo;
- cadastro estruturado de leitos: planejado, instalado, operacional, bloqueado, extra e observação;
- motivo ou tipo da saída hospitalar: alta, evasão, desistência, transferência externa ou óbito;
- registro estruturado de óbitos, com data/hora e distinção hospitalar versus institucional;
- movimentação intra-hospitalar, especialmente transferências internas sem tratá-las como alta;
- distinção entre leitos de internação e leitos de observação ou hospital-dia.

## Indicadores do manual e dados necessários

### Média de pacientes/dia

Fórmula conceitual:

> Total de pacientes/dia no período dividido pelo número de dias do período.

Dados necessários:

- número de pacientes internados em cada dia hospitalar;
- fechamento diário em horário fixo;
- exclusão de observação menor que 24 horas;
- regra de que paciente internado conta como paciente/dia no censo.

Dados já disponíveis parcialmente:

- `CensusSnapshot.captured_at`;
- `bed_status=occupied`;
- `setor`, `leito`, `prontuario`, `nome`.

Lacunas e riscos:

- o censo roda a cada 8 horas, não necessariamente como censo hospitalar diário oficial;
- é necessário escolher um horário institucional fixo para o censo diário;
- é necessário garantir que o snapshot usado represente internação, não observação.

### Média de permanência

Fórmula do manual:

> Total de pacientes/dia dividido pelo total de pacientes que tiveram saída no período, incluindo óbitos.

Dados necessários:

- total de pacientes/dia no período;
- total de saídas hospitalares no período;
- saídas por alta, evasão, desistência, transferência externa e óbito;
- exclusão de transferências internas como saída hospitalar.

Dados já disponíveis parcialmente:

- `Admission.admission_date`;
- `Admission.discharge_date`;
- extração de altas/saídas em `discharges`;
- `DailyDischargeCount`.

Lacunas e riscos:

- `discharge_date` existe, mas não há motivo estruturado da saída;
- `DailyDischargeCount` guarda só contagem diária de altas, sem classificação de tipo;
- óbito ainda não é distinguido de alta comum;
- transferência externa não é distinguida;
- evasão e desistência não são capturadas;
- para cálculo por unidade, é necessário lidar com transferências internas sem duplicar permanência.

### Taxa de ocupação hospitalar instalada

Fórmula conceitual:

> Pacientes/dia dividido por leitos/dia instalados, multiplicado por 100.

No manual, o denominador usa leitos instalados constantes do cadastro, incluindo leitos bloqueados e excluindo leitos extras.

Dados necessários:

- pacientes/dia;
- número de leitos instalados por dia;
- identificação de leitos bloqueados;
- exclusão de leitos extras;
- cadastro oficial ou operacional de leitos instalados.

Dados já disponíveis parcialmente:

- snapshots com cada leito encontrado;
- status aproximado: `occupied`, `empty`, `maintenance`, `reserved`, `isolation`.

Lacunas e riscos:

- não há cadastro mestre de leitos instalados;
- não é possível saber se um leito ausente no censo está desativado, removido ou não capturado;
- `maintenance`, `reserved` e `isolation` não equivalem perfeitamente à nomenclatura do manual;
- não há distinção entre leito instalado e leito extra;
- não há distinção entre leito de internação e leito de observação.

### Taxa de ocupação operacional

Fórmula conceitual:

> Pacientes/dia dividido por leitos/dia operacionais, multiplicado por 100.

Leitos operacionais são os leitos em uso ou passíveis de uso no momento do censo, incluindo leito extra em uso.

Dados necessários:

- pacientes/dia;
- leitos ocupados;
- leitos vagos disponíveis;
- leitos bloqueados excluídos;
- leitos extras ocupados incluídos;
- leitos extras vazios excluídos.

Dados já disponíveis parcialmente:

- status ocupado, vago, manutenção, reservado e isolamento;
- contagem por setor e leito.

Lacunas e riscos:

- falta diferenciar leito vago operacional, leito bloqueado, leito extra ocupado e leito instalado indisponível;
- `reserved` precisa de regra institucional, pois pode significar reserva operacional, bloqueio ou outra situação;
- `isolation` hoje aparece como status, mas o manual trata isolamento como tipo ou característica de leito, não necessariamente indisponibilidade.

### Taxa de ocupação planejada

Fórmula conceitual:

> Pacientes/dia dividido por leitos/dia planejados, multiplicado por 100.

O denominador considera todos os leitos planejados, inclusive não instalados ou desativados.

Dados necessários:

- pacientes/dia;
- capacidade hospitalar planejada;
- leitos planejados por unidade ou setor;
- leitos instalados versus desativados.

Dados já disponíveis:

- nada confiável para capacidade planejada.

Lacunas:

- cadastro institucional de leitos planejados;
- leitos desativados;
- capacidade planejada por setor ou unidade;
- data de vigência das mudanças de capacidade.

### Taxa de mortalidade hospitalar

Fórmula do manual:

> Óbitos ocorridos em pacientes internados divididos por pacientes que tiveram saída, multiplicado por 100.

Dados necessários:

- óbitos hospitalares;
- total de saídas no período;
- exclusão de pessoas que chegaram mortas ao hospital;
- óbito como motivo estruturado de saída.

Dados já disponíveis parcialmente:

- evoluções clínicas podem conter texto mencionando óbito;
- `Admission.discharge_date` pode fechar internação.

Lacunas:

- campo estruturado `discharge_reason`;
- data/hora do óbito;
- marcação de óbito hospitalar;
- distinção entre óbito intra-hospitalar e chegada já em óbito;
- fonte confiável de óbitos, idealmente relatório administrativo ou evento de alta por óbito.

### Taxa de mortalidade institucional

Fórmula do manual:

> Óbitos após pelo menos 24 horas da admissão divididos por pacientes que tiveram saída, multiplicado por 100.

Dados necessários adicionais:

- data/hora exata da admissão;
- data/hora exata do óbito;
- cálculo se o óbito ocorreu após 24 horas da admissão.

Dados já disponíveis parcialmente:

- `Admission.admission_date`;
- `Admission.discharge_date`.

Lacunas:

- data/hora específica do óbito;
- motivo de saída igual a óbito;
- confiabilidade da hora de admissão;
- separação entre óbito com menos de 24 horas e óbito com 24 horas ou mais.

## Dados que o SIRHOSP já coleta e aproveita

### Censo e leitos

Modelo atual: `CensusSnapshot`.

Dados disponíveis:

- data/hora da captura;
- setor;
- leito;
- prontuário;
- nome;
- especialidade;
- status básico do leito: ocupado, vago, manutenção, reservado e isolamento.

Isso já permite:

- ocupação pontual;
- leitos ocupados por setor;
- vagas aparentes;
- histórico aproximado de ocupação, se snapshots forem preservados.

Ainda não basta para indicadores oficiais do manual sem normalização adicional.

### Pacientes

Modelo atual: `Patient`.

Dados disponíveis:

- prontuário ou chave fonte;
- nome;
- data de nascimento;
- sexo/gênero;
- CNS/CPF;
- nome da mãe;
- endereço e contato;
- raça/cor etc.

Esses dados ajudam reconciliação e estratificação, mas os indicadores do manual são majoritariamente de movimento hospitalar e leitos, não demográficos.

### Internações

Modelo atual: `Admission`.

Dados disponíveis:

- paciente;
- chave da internação no sistema fonte;
- data de admissão;
- data de alta/saída quando conhecida;
- setor;
- leito.

Isso ajuda:

- permanência;
- identificação de internação ativa;
- associação de eventos clínicos à internação;
- cálculo bruto de tempo de internação.

Mas falta o dado mais importante para estatística hospitalar: tipo de saída.

### Altas e saídas

Dados disponíveis:

- extração de altas;
- `DailyDischargeCount`;
- `Admission.discharge_date`.

Hoje ainda é insuficiente para separar:

- alta médica;
- evasão;
- alta a pedido ou desistência;
- transferência externa;
- óbito.

Para os indicadores do manual, essa separação é crítica.

## Principais dados adicionais que precisamos coletar

### Cadastro mestre de leitos

É necessário ter uma entidade ou tabela conceitual de leitos, com histórico de vigência.

Campos necessários:

- código do leito;
- setor/unidade;
- tipo: internação, observação, hospital-dia, UTI, semi-intensivo, berçário, alojamento conjunto, pré-parto ou recuperação pós-anestésica;
- se é leito de internação válido para censo;
- se é planejado;
- se é instalado;
- se está desativado;
- se é extra;
- se é reversível;
- data de início e fim da vigência;
- capacidade planejada por setor;
- capacidade instalada por setor.

Sem isso, as taxas de ocupação instalada, operacional e planejada ficam frágeis.

### Status oficial diário do leito

Além do status básico atual, é necessário mapear para a nomenclatura do manual:

- ocupado;
- vago;
- bloqueado;
- operacional;
- extra ocupado;
- extra desocupado;
- desativado;
- observação;
- internação.

Pontos de atenção:

- manutenção transitória equivale a bloqueado;
- isolamento pode ser tipo de leito, não status;
- reserva pode ou não representar bloqueio;
- leito extra precisa ser identificado explicitamente.

### Movimento diário de pacientes

O manual define que o censo diário deve registrar, nas 24 horas:

- internações;
- altas;
- óbitos;
- transferências internas;
- transferências externas;
- evasões;
- desistência do tratamento;
- leitos bloqueados;
- leitos extras.

É necessário capturar eventos de movimento como:

- entrada por internação;
- entrada por transferência externa;
- transferência interna origem/destino;
- saída por alta;
- saída por evasão;
- saída por desistência ou alta a pedido;
- saída por transferência externa;
- saída por óbito.

### Motivo da saída da internação

Campo essencial para quase todos os indicadores.

Valores alinhados ao manual:

- alta;
- evasão;
- desistência do tratamento ou alta a pedido;
- transferência externa;
- óbito hospitalar;
- outros motivos administrativos, mapeados para uma categoria oficial quando necessário.

Sem isso:

- média de permanência pode ser calculada apenas parcialmente;
- mortalidade hospitalar não pode ser calculada corretamente;
- mortalidade institucional não pode ser calculada corretamente.

### Óbito estruturado

É necessário dado confiável, não apenas inferência por texto clínico.

Campos necessários:

- se houve óbito;
- data/hora do óbito;
- se ocorreu após entrada no hospital;
- se ocorreu após 24 horas da admissão;
- se paciente chegou morto, para excluir da mortalidade hospitalar;
- vínculo com a internação;
- unidade/setor no momento do óbito.

### Censo diário oficial em horário fixo

O manual exige um dia hospitalar entre dois censos consecutivos.

Hoje o sistema coleta a cada 8 horas, o que é útil para operação, mas para indicador oficial é necessário definir:

- horário institucional de fechamento do censo;
- snapshot oficial do dia;
- regra quando faltar captura no horário;
- regra para usar captura mais próxima;
- timezone institucional.

Sem isso, o cálculo de pacientes/dia pode variar artificialmente.

### Leitos de observação e hospital-dia

O manual separa:

- internação hospitalar;
- observação hospitalar menor que 24 horas;
- hospital-dia;
- leito/hora;
- paciente/hora.

Se o hospital quiser medir observação, será necessário coletar:

- início e fim da observação;
- leito de observação;
- paciente/hora;
- leito/hora;
- conversão de observação para internação se passar de 24 horas.

Para os indicadores principais de internação, esses casos precisam ser excluídos ou convertidos corretamente.

## Matriz de suficiência atual

| Indicador                          | Dá para calcular hoje? | Confiabilidade                                      |
| ---------------------------------- | ---------------------- | --------------------------------------------------- |
| Média pacientes/dia                | Parcialmente           | Média/baixa, falta censo diário oficial             |
| Média permanência                  | Parcialmente           | Média, falta tipo de saída e óbito                  |
| Taxa ocupação hospitalar instalada | Não plenamente         | Baixa, falta leitos instalados oficiais             |
| Taxa ocupação operacional          | Parcialmente           | Baixa/média, falta status oficial de bloqueio/extra |
| Taxa ocupação planejada            | Não                    | Falta capacidade planejada                          |
| Mortalidade hospitalar             | Não corretamente       | Falta óbito estruturado                             |
| Mortalidade institucional          | Não corretamente       | Falta óbito estruturado e regra de 24 horas         |

## Prioridade sugerida de coleta

Se o objetivo é chegar rapidamente aos indicadores do manual, a ordem sugerida é:

1. Definir censo diário oficial a partir dos snapshots existentes.
2. Criar cadastro mestre de leitos com planejado, instalado, tipo e setor.
3. Normalizar status do leito: ocupado, vago, bloqueado, extra e desativado.
4. Capturar motivo de saída da internação.
5. Capturar óbito estruturado com data/hora.
6. Capturar transferências internas e externas.
7. Depois, se necessário, medir observação/hospital-dia com paciente/hora e leito/hora.

## Conclusão

O SIRHOSP já tem a base para ocupação e permanência, mas para estatísticas hospitalares segundo o manual precisa evoluir de “snapshot de pacientes internados” para “censo hospitalar diário mais movimento hospitalar mais cadastro oficial de leitos”.
