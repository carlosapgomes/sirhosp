## MODIFIED Requirements

### Requirement: O preflight valida a procedência imutável do runtime

O sistema SHALL fornecer um preflight somente leitura que aceite uma tag exata
de release e MUST confirmar que a imagem configurada, o Compose hospitalar, o
scheduler e os units instalados necessários ao fallback e às cadências de saída
correspondem aos assets daquela mesma release imutável.

#### Scenario: Runtime corresponde à release selecionada

- **WHEN** o operador executa o preflight para uma tag exata publicada
- **AND** a imagem configurada, o Compose, o scheduler e todos os units exigidos
  correspondem aos assets imutáveis dessa tag
- **THEN** a verificação de procedência é aprovada
- **AND** a saída identifica somente a tag e o estado técnico agregado

#### Scenario: Asset local diverge da release

- **WHEN** o Compose, qualquer scheduler, service ou timer obrigatório está
  ausente ou difere do asset da tag selecionada
- **THEN** o preflight termina com código diferente de zero
- **AND** não permite que a evidência seja considerada apta para ativação

#### Scenario: Tag ou release não pode ser validada

- **WHEN** a tag não existe, a release não é imutável ou sua procedência não
  pode ser consultada
- **THEN** o preflight falha fechado
- **AND** não aceita cópias locais como substituto silencioso da validação

### Requirement: A data de ativação é futura e explícita

O preflight MUST validar a data configurada em `STATISTICS_ACTIVATION_DATE` no
calendário `America/Bahia`. Ele SHALL aceitar uma data futura ou, para o
bootstrap inicial, a data local corrente somente antes das 20:00, enquanto o
runtime estatístico permanece dormente; MUST recusar valor ausente, inválido,
passado ou bootstrap corrente iniciado a partir das 20:00.

#### Scenario: Data futura está configurada

- **WHEN** `STATISTICS_ACTIVATION_DATE` contém uma data válida posterior ao dia
  corrente em `America/Bahia`
- **THEN** a verificação da fronteira de ativação é aprovada
- **AND** nenhuma data anterior é materializada pelo preflight

#### Scenario: Bootstrap corrente é declarado antes do fechamento

- **WHEN** `STATISTICS_ACTIVATION_DATE` é igual à data corrente em
  `America/Bahia`
- **AND** o preflight ocorre antes das 20:00 locais
- **AND** os timers hourly, D-1 e estatístico continuam desabilitados e
  inativos
- **THEN** a verificação aprova a fronteira como bootstrap corrente
- **AND** nenhuma data anterior ao dia corrente se torna elegível

#### Scenario: Data não é segura para ativação

- **WHEN** a variável está ausente, inválida ou no passado
- **OR** ela é igual ao dia corrente e o horário local já alcançou 20:00
- **THEN** o preflight termina com código diferente de zero
- **AND** não altera a configuração para tentar corrigi-la

### Requirement: Cadências de saída exigem sucesso recente verificável

O preflight SHALL exigir execuções naturais e bem-sucedidas do
`census_orchestrator` para a recuperação hourly nas últimas duas horas e para a
recuperação D-1 nas últimas trinta horas. Ele MUST validar que o runtime da
release mantém os quatro extratores D-1 canônicos, incluindo óbitos. Os timers
legados hourly e D-1 MUST permanecer desabilitados e inativos, e execuções
manuais de seus services MUST NOT ser aceitas como evidência natural.

#### Scenario: Todas as cadências possuem evidência recente

- **WHEN** os logs do `census_orchestrator` contêm evidência agregada de uma
  execução hourly natural e bem-sucedida nas últimas duas horas
- **AND** os mesmos logs contêm evidência agregada de uma execução D-1 natural
  com quatro extratores e resultado bem-sucedido nas últimas trinta horas
- **AND** os timers legados hourly e D-1 estão desabilitados e inativos
- **THEN** a verificação das cadências é aprovada
- **AND** a saída contém apenas janelas, modos, origens e estados técnicos
  agregados

#### Scenario: Alta intradiária está atrasada

- **WHEN** não existe sucesso hourly natural do orquestrador dentro das últimas
  duas horas
- **OR** existe apenas marcador do service manual legado
- **THEN** o preflight falha fechado
- **AND** não executa uma extração para produzir evidência artificialmente

#### Scenario: Recuperação D-1 ou cobertura de óbitos não está comprovada

- **WHEN** não existe sucesso recente do D-1 nos logs do orquestrador
- **OR** a evidência não comprova os quatro extratores canônicos
- **OR** existe apenas marcador do service manual legado
- **THEN** o preflight falha fechado
- **AND** não aceita estado ativo de timer nem disparo manual como substituto

#### Scenario: Timer D-1 legado continua ativo

- **WHEN** `sirhosp-historical-recovery.timer` está habilitado ou ativo
- **THEN** o preflight falha fechado
- **AND** não o desabilita automaticamente

#### Scenario: Timer hourly legado continua ativo

- **WHEN** `sirhosp-discharges.timer` está habilitado ou ativo
- **THEN** o preflight falha fechado
- **AND** não o desabilita automaticamente

### Requirement: O preflight não executa ações mutáveis

O preflight MUST limitar-se a consultar release, configuração, arquivos,
estados systemd, journal e estado/logs do Compose por comandos Docker
explicitamente read-only. Ele MUST NOT habilitar ou iniciar units, criar ou
recriar containers, executar comandos Django, criar relatórios, disparar
extratores, alterar banco ou configuração e fazer backfill.

#### Scenario: Preflight é executado com sucesso

- **WHEN** todas as pré-condições já são atendidas
- **THEN** o comando retorna sucesso sem alterar qualquer serviço, container ou
  dado
- **AND** os timers hourly, D-1 e de estatísticas permanecem desabilitados e
  inativos

#### Scenario: Preflight encontra falha

- **WHEN** qualquer pré-condição não é atendida
- **THEN** o comando retorna falha sem tentar remediação automática
- **AND** não executa `systemctl enable`, `systemctl start`, `docker compose up`,
  `docker compose run`, `docker compose exec` nem materialização

#### Scenario: Evidência do orquestrador é consultada

- **WHEN** o preflight verifica as recuperações hourly e D-1 naturais
- **THEN** ele pode executar somente consultas equivalentes a `docker compose
  ps` e `docker compose logs`
- **AND** não reproduz linhas brutas dos logs em stdout ou stderr

### Requirement: Evidência não contém identidade clínica

O preflight MUST emitir apenas tag, checks de procedência, janelas, modos,
origens, estados e motivos técnicos enumerados, sem copiar mensagens brutas do
journal ou dos logs Docker, credenciais, nomes, prontuários, leitos ou texto
clínico.

#### Scenario: Journal contém conteúdo não agregado

- **WHEN** o journal ou os logs do container contêm mensagens além do marcador
  técnico necessário
- **THEN** o preflight usa o conteúdo apenas para decisão interna
- **AND** não reproduz a mensagem bruta em stdout ou stderr

#### Scenario: Operador registra a evidência

- **WHEN** a saída do preflight é anexada ao checkpoint humano
- **THEN** o registro contém somente evidência operacional agregada
- **AND** não requer persistência de log clínico ou workbook

### Requirement: Ativação exige checkpoint humano separado

O sistema SHALL documentar instalação inicialmente dormente e SHALL manter a
ativação da finalização adaptativa como ação explícita posterior ao preflight e
ao aceite humano. A ativação MUST recriar somente o `census_orchestrator` para
carregar a fronteira declarada; os timers hourly, D-1 e de estatísticas MUST
permanecer desabilitados e inativos. O preflight por si só MUST NOT representar
autorização para ativar produção.

#### Scenario: Preflight é aprovado

- **WHEN** o preflight retorna sucesso
- **THEN** o operador revisa e registra a evidência antes de executar a etapa de
  ativação documentada
- **AND** nenhuma ativação ocorre automaticamente

#### Scenario: Aceite humano autoriza a ativação adaptativa

- **WHEN** existe preflight `PASS` ainda fresco e aceite humano explícito
- **THEN** o operador recria somente o serviço `census_orchestrator` com o
  Compose da release validada
- **AND** confirma que a fronteira configurada chegou ao novo container
- **AND** não habilita os timers legados hourly, D-1 ou estatístico

#### Scenario: Evidência expira antes da ativação

- **WHEN** a ativação não acontece enquanto as janelas de frescor ou a janela de
  bootstrap corrente continuam válidas
- **THEN** o operador deve executar novo preflight
- **AND** a evidência anterior não autoriza a ativação

### Requirement: Rollback preserva dados e cadências existentes

O runbook SHALL permitir retirar a configuração estatística do orquestrador ou
retornar à imagem anterior sem excluir relatórios materializados, alterar fontes
clínicas ou interromper a cadência intradiária de altas. Os units de fallback
SHALL permanecer desabilitados durante o rollback.

#### Scenario: Timer diário é desativado

- **WHEN** o operador executa o rollback documentado
- **THEN** remove a fronteira estatística da configuração e recria somente o
  `census_orchestrator`, ou retorna esse serviço à release anterior
- **AND** relatórios existentes e fontes clínicas permanecem intactos
- **AND** a cadência intradiária de altas não é modificada
- **AND** os timers hourly, D-1 e de estatísticas não são habilitados
