## Purpose

Definir evidência operacional agregada, fail-closed e revisável antes da ativação humana do fechamento estatístico diário em produção.

## ADDED Requirements

### Requirement: O preflight valida a procedência imutável do runtime

O sistema SHALL fornecer um preflight somente leitura que aceite uma tag exata
de release e MUST confirmar que a imagem configurada, o scheduler e os units
instalados necessários à finalização e às cadências de saída correspondem aos
assets daquela mesma release imutável.

#### Scenario: Runtime corresponde à release selecionada

- **WHEN** o operador executa o preflight para uma tag exata publicada
- **AND** a imagem configurada, o scheduler e todos os units exigidos
  correspondem aos assets imutáveis dessa tag
- **THEN** a verificação de procedência é aprovada
- **AND** a saída identifica somente a tag e o estado técnico agregado

#### Scenario: Asset local diverge da release

- **WHEN** qualquer scheduler, service ou timer obrigatório está ausente ou
  difere do asset da tag selecionada
- **THEN** o preflight termina com código diferente de zero
- **AND** não permite que a evidência seja considerada apta para ativação

#### Scenario: Tag ou release não pode ser validada

- **WHEN** a tag não existe, a release não é imutável ou sua procedência não
  pode ser consultada
- **THEN** o preflight falha fechado
- **AND** não aceita cópias locais como substituto silencioso da validação

### Requirement: A data de ativação é futura e explícita

O preflight MUST validar a data configurada em `STATISTICS_ACTIVATION_DATE` no
calendário `America/Bahia` e MUST recusar valor ausente, inválido ou que não
seja futuro no momento da verificação.

#### Scenario: Data futura está configurada

- **WHEN** `STATISTICS_ACTIVATION_DATE` contém uma data válida posterior ao dia
  corrente em `America/Bahia`
- **THEN** a verificação da fronteira de ativação é aprovada
- **AND** nenhuma data anterior é materializada pelo preflight

#### Scenario: Data não é segura para ativação

- **WHEN** a variável está ausente, inválida, igual ao dia corrente ou no passado
- **THEN** o preflight termina com código diferente de zero
- **AND** não altera a configuração para tentar corrigi-la

### Requirement: Cadências de saída exigem sucesso recente verificável

O preflight SHALL exigir que os timers de altas intradiárias e recuperação D-1
estejam habilitados e ativos com seus calendários oficiais, SHALL exigir uma
execução horária bem-sucedida nas últimas duas horas e uma execução D-1
bem-sucedida nas últimas trinta horas, e MUST considerar o sucesso D-1 somente
quando o runtime da mesma release mantém os quatro extratores canônicos,
incluindo óbitos.

#### Scenario: Todas as cadências possuem evidência recente

- **WHEN** os timers oficiais estão habilitados e ativos
- **AND** existe sucesso de `hourly-discharges` nas últimas duas horas
- **AND** existe sucesso de `d1-recovery` nas últimas trinta horas pelo runtime
  canônico de quatro extratores
- **THEN** a verificação das cadências é aprovada
- **AND** a saída contém apenas horários, modos e estados técnicos agregados

#### Scenario: Alta intradiária está atrasada

- **WHEN** não existe sucesso de `hourly-discharges` dentro da janela exigida
- **THEN** o preflight falha fechado
- **AND** não executa uma extração para produzir evidência artificialmente

#### Scenario: Recuperação D-1 ou cobertura de óbitos não está comprovada

- **WHEN** não existe sucesso recente de `d1-recovery`
- **OR** o runtime validado não comprova a ordem canônica com o extrator de
  óbitos
- **THEN** o preflight falha fechado
- **AND** não aceita apenas o estado ativo do timer como prova de cobertura

### Requirement: O preflight não executa ações mutáveis

O preflight MUST limitar-se a consultar release, configuração, arquivos,
systemd e marcadores técnicos de journal. Ele MUST NOT habilitar ou iniciar
units, executar comandos Django, criar relatórios, disparar extratores, alterar
banco ou configuração e fazer backfill.

#### Scenario: Preflight é executado com sucesso

- **WHEN** todas as pré-condições já são atendidas
- **THEN** o comando retorna sucesso sem alterar qualquer serviço ou dado
- **AND** o timer de estatísticas diárias permanece no estado anterior

#### Scenario: Preflight encontra falha

- **WHEN** qualquer pré-condição não é atendida
- **THEN** o comando retorna falha sem tentar remediação automática
- **AND** não executa `systemctl enable`, `systemctl start` nem materialização

### Requirement: Evidência não contém identidade clínica

O preflight MUST emitir apenas tag, checks de procedência, horários, modos,
estados e motivos técnicos enumerados, sem copiar mensagens brutas do journal,
credenciais, nomes, prontuários, leitos ou texto clínico.

#### Scenario: Journal contém conteúdo não agregado

- **WHEN** o journal da unidade contém mensagens além do marcador técnico
  necessário
- **THEN** o preflight usa o conteúdo apenas para decisão interna
- **AND** não reproduz a mensagem bruta em stdout ou stderr

#### Scenario: Operador registra a evidência

- **WHEN** a saída do preflight é anexada ao checkpoint humano
- **THEN** o registro contém somente evidência operacional agregada
- **AND** não requer persistência de log clínico ou workbook

### Requirement: Ativação exige checkpoint humano separado

O sistema SHALL documentar instalação inicialmente desabilitada e SHALL manter
a ativação do timer de estatísticas como ação explícita posterior ao preflight e
ao aceite humano. O preflight por si só MUST NOT representar autorização para
ativar produção.

#### Scenario: Preflight é aprovado

- **WHEN** o preflight retorna sucesso
- **THEN** o operador revisa e registra a evidência antes de executar a etapa de
  ativação documentada
- **AND** nenhuma ativação ocorre automaticamente

#### Scenario: Evidência expira antes da ativação

- **WHEN** a ativação não acontece enquanto as janelas de frescor continuam
  válidas
- **THEN** o operador deve executar novo preflight
- **AND** a evidência anterior não autoriza a ativação

### Requirement: Rollback preserva dados e cadências existentes

O runbook SHALL permitir desabilitar e remover somente o runtime de estatísticas
diárias sem excluir relatórios materializados, alterar fontes clínicas ou
interromper as cadências de altas e recuperação D-1.

#### Scenario: Timer diário é desativado

- **WHEN** o operador executa o rollback documentado
- **THEN** o timer e o service de estatísticas são desabilitados e removidos
- **AND** relatórios existentes e fontes clínicas permanecem intactos
- **AND** os timers de altas e recuperação D-1 não são modificados
