## Why

Batches de censo terminam sistematicamente como falha porque uma captura vazia
de internações ou um `full_sync` sem evoluções é tratado apenas como erro
técnico, embora a operação tenha confirmado fluxos válidos e acionáveis:
atendimento recente ainda não consolidado, recém-nascido aguardando registro,
internação recente aguardando primeira evolução e suspeita de paciente residual
no legado. A distinção é necessária agora para reduzir alarmes falsos sem
ocultar timeouts reais e para orientar revisão de prontuários nas telas já
usadas pela equipe.

## What Changes

- Capturar de forma condicional e read-only o último item de `Atendimentos`
  quando um `admissions_only` batch-bound encontra uma lista de internações
  vazia, reutilizando a sessão Playwright existente.
- Classificar somente datas de atendimento estruturalmente válidas em três
  faixas seguras: hoje/ontem, anteontem limítrofe e antiga; a página fonte não
  fornece horário, portanto o sistema não alegará precisão literal de 48 horas.
- Reconhecer `admissions_only` vazio com atendimento de hoje/ontem como achado
  operacional válido, sem criar Admission, full-sync ou contador clínico
  positivo; ausência, data limítrofe/antiga ou payload inválido continuam
  fail-closed.
- Manter paridade entre os workers persistente e clássico com fixtures
  exclusivamente sintéticas; nenhum teste acessará o legado.
- Calcular rótulos atuais e auto-resolvíveis, separados do resultado técnico:
  atendimento recente sem internação, RN aguardando registro, possível RN
  acompanhante, internação recente aguardando primeira evolução e suspeita de
  residual no legado.
- Exibir os rótulos na linha do paciente em `/censo` e `/beds` e na página de
  admissões do paciente, preservando autenticação e sem expor novo conteúdo
  clínico.
- Separar, nas métricas de batches, achados operacionais de falhas técnicas e
  apresentar `Concluído com achados` ou `Falha parcial` como estado derivado de
  apresentação, sem alterar o status persistido do batch.
- Ajustar o health check para aceitar apenas vazio reconhecido por evidência de
  atendimento recente e continuar alertando qualquer sucesso vazio não
  classificado.
- Não persistir nome de profissional, HTML, screenshot, texto clínico ou linha
  bruta de `Atendimentos`; stage metrics guardarão somente códigos fechados e
  contagens.

## Capabilities

### New Capabilities

- `patient-flow-findings`: captura condicional do último atendimento,
  classificação operacional separada da falha técnica e projeção de rótulos
  atuais nas superfícies assistenciais e operacionais.

### Modified Capabilities

- `persistent-session-ingestion-worker`: adiciona fallback read-only de
  `Atendimentos` após internações vazias e resultado operacional sanitizado.
- `patient-admission-mirror`: permite que vazio batch-bound seja aceito somente
  quando atendimento recente válido comprovar fluxo ainda não consolidado.
- `ingestion-pipeline-health`: distingue sucesso vazio reconhecido de falso
  sucesso vazio.
- `ingestion-run-metrics-portal`: separa achados operacionais de falhas técnicas
  na leitura do batch.
- `censo-current-list-export`: acrescenta rótulos somente à lista HTML atual,
  preservando filtros, ordenação e exportação XLSX existente.
- `bed-status-capacity-view`: acrescenta rótulos operacionais às linhas de
  pacientes sem alterar medição, capacidade ou reconciliação oficial.

## Impact

- Código afetado: navegação e bridge Playwright, adapters dos dois workers,
  lifecycle de `admissions_only`, classificador de apresentação, views/templates
  de censo, leitos, admissões, métricas e health check.
- Dados: nenhum novo modelo ou migration planejado; o resultado mínimo
  persistido usa `IngestionRunStageMetric.details_json` com enum allowlisted.
- Fonte externa: no máximo um clique e uma leitura tabular adicionais quando a
  lista de internações batch-bound estiver vazia; nunca para todas as capturas.
- Privacidade: testes e relatórios usam somente fixtures sintéticas; artefatos
  não conterão registros, nomes, datas de nascimento, profissionais, HTML/PDF,
  URLs reais ou credenciais.
- Compatibilidade: status persistidos de runs/batches e taxonomia de falhas
  permanecem; timeout de `full_sync` nunca vira sucesso por causa de um rótulo.
- Risco ESAA: **CRÍTICO**, por integrar sistema legado, afetar fluxo de dados de
  saúde, atravessar mais de cinco arquivos e alterar interpretação operacional.
  O classificador automático foi inconclusivo para texto em português
  (`confidence=0`); prevalece avaliação manual conservadora. Exige testes
  extensivos, rollout canário agregado e rollback documentado.

### Fora de escopo

- Abrir detalhes individuais de `Atendimentos` para obter horário.
- Persistir a lista completa de atendimentos ou o nome do profissional.
- Marcar timeout, PDF inacessível ou payload malformado como sucesso.
- Criar workflow de confirmação manual, edição de prontuário ou baixa no legado.
- Alterar escolhas de status, criar nova fila/worker, Celery, Redis ou serviço.
- Executar scraping real, rollout, backfill ou mutação de produção durante a
  implementação dos slices.
