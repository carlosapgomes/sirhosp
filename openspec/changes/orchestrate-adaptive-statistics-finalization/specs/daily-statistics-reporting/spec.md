## MODIFIED Requirements

### Requirement: Relatórios diários são materializados e versionados

O sistema SHALL materializar uma revisão reproduzível por dia completo, SHALL
permitir regeneração idempotente e MUST preservar procedência suficiente para
auditar revisões automáticas. A finalização adaptativa MUST usar uma data D-1
explícita e MUST persistir um aviso técnico enumerado quando publicar após uma
recuperação D-1 malsucedida ou quando um processo reiniciado não puder confirmar
se essa recuperação terminou com sucesso.

#### Scenario: Dia posterior à ativação é finalizado

- **WHEN** o dia possui abertura e fechamento válidos após a ativação da
  feature
- **THEN** o sistema materializa uma revisão pronta para consulta

#### Scenario: Dia anterior à ativação é consultado

- **WHEN** o usuário seleciona uma data anterior à ativação
- **THEN** o sistema informa que não existe relatório
- **AND** não tenta reconstruí-lo automaticamente

#### Scenario: Materialização é repetida sem mudança de fonte

- **WHEN** o mesmo dia é materializado novamente sem mudança das evidências
- **THEN** o conteúdo lógico não é duplicado
- **AND** a revisão corrente permanece determinística

#### Scenario: Evidência tardia altera o relatório

- **WHEN** uma alta, óbito ou correção de evidência chega depois da primeira
  materialização
- **THEN** o sistema pode gerar nova revisão automática auditável
- **AND** preserva a mesma fotografia censitária de fechamento
- **AND** a revisão anterior não é apresentada como corrente

#### Scenario: D-1 recovery fails before publication

- **WHEN** a recuperação D-1 falha, mas a data possui abertura e fechamento
  censitários aceitos
- **THEN** o sistema pode publicar a revisão com a evidência disponível
- **AND** persiste um aviso enumerado de reconciliação D-1 incompleta
- **AND** o aviso participa da impressão digital reproduzível da revisão

#### Scenario: Restart cannot confirm previous D-1 recovery

- **WHEN** o processo reinicia após a janela D-1 sem uma revisão pronta
- **AND** não pode comprovar no próprio estado o resultado da recuperação
  anterior
- **THEN** o sistema pode publicar a revisão com a evidência disponível
- **AND** persiste o aviso enumerado `d1_recovery_not_confirmed`
- **AND** não apresenta esse aviso como prova de que a recuperação falhou

#### Scenario: Later successful recovery removes degraded warning

- **WHEN** a mesma data é materializada após uma recuperação D-1 bem-sucedida
- **AND** a revisão corrente contém `d1_recovery_incomplete` ou
  `d1_recovery_not_confirmed`
- **THEN** o sistema publica ou reutiliza a revisão correspondente às novas
  evidências sem o aviso degradado
- **AND** preserva a revisão anterior para auditoria

#### Scenario: Closing census is absent

- **WHEN** a data D-1 não possui fotografia de fechamento aceita
- **THEN** nenhuma revisão pronta é publicada
- **AND** a aceitação de dados clínicos parciais não substitui o gate
  censitário obrigatório

#### Scenario: Usuário tenta corrigir evento manualmente

- **WHEN** um usuário acessa a página nesta versão da capability
- **THEN** nenhuma ação de inclusão, reclassificação ou exclusão manual é
  oferecida
