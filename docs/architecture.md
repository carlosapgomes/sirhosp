# Arquitetura inicial do SIRHOSP

## 1. Visão geral

O SIRHOSP será um sistema interno de inteligência operacional sobre dados clínicos extraídos do sistema fonte hospitalar. O foco inicial não é substituir o prontuário oficial nem atender o médico assistente em tempo real. O objetivo é oferecer acesso rápido, busca textual e resumos úteis para setores de gestão, qualidade, jurídico, diretoria e gestão de prontuários.

A fase 1 será limitada a pacientes internados.

## 2. Objetivos da fase 1

A fase 1 deve permitir:

1. sincronizar pacientes internados atualmente
2. extrair evoluções médicas em janelas programadas
3. extrair prescrições em janelas programadas
4. armazenar dados clínicos relevantes em banco PostgreSQL paralelo
5. consultar por paciente, período, categoria profissional e internação
6. pesquisar palavras-chave em texto livre
7. manter um resumo atualizado da internação atual
8. oferecer páginas específicas por caso de uso institucional

## 3. Escopo funcional inicial

### Incluído

- login próprio da aplicação
- dois perfis iniciais: `admin` e `user`
- dashboard operacional básico
- execução manual e agendada de automações
- monitoramento de runs
- persistência em PostgreSQL
- busca textual livre
- resumo da internação em Markdown copiável
- páginas orientadas por caso de uso, sem segregação de dados por setor na fase 1

### Fora do escopo inicial

- SSO/LDAP
- desidentificação
- exportação avançada em PDF/XLSX
- múltiplos ambientes completos
- processamento distribuído complexo
- RAG e embeddings como requisito obrigatório
- auditoria detalhada de pesquisa por paciente

## 4. Princípios de arquitetura

1. **Simplicidade operacional primeiro**: a fase 1 rodará em uma única VM Linux.
2. **Monólito modular**: uma aplicação principal bem organizada é preferível a microserviços neste estágio.
3. **Extração desacoplada do portal**: automações de scraping não devem ficar misturadas com lógica de request/response da web.
4. **Separação entre laboratório e produção**: fluxos exploratórios de Playwright devem ficar isolados do código de execução programada.
5. **Banco relacional como eixo do sistema**: PostgreSQL será usado tanto para persistência clínica quanto para coordenação operacional básica.
6. **Crescimento incremental**: componentes mais complexos, como filas distribuídas, só entram se o volume ou a criticidade exigirem.

## 5. Stack proposta

### Aplicação principal

- Python 3.12
- Django
- `uv` para gerenciamento de ambiente virtual, dependências e execução padronizada de comandos Python
- Django Admin para administração operacional interna
- Django Templates + HTMX + Bootstrap para UI inicial

### Banco de dados

- PostgreSQL
- Full Text Search nativo para pesquisa clínica inicial
- advisory locks e tabelas de controle para coordenação de jobs

### Automação

- Playwright + Python
- PyMuPDF quando a captura depender de relatórios PDF
- parsers reutilizados do MVP, adaptados para componentes reaproveitáveis

### Execução programada

- systemd timers preferencialmente
- cron como alternativa aceitável
- Django management commands para disparo de jobs
- comandos Python executados preferencialmente via `uv run`

### Infraestrutura inicial

- VM Linux única
- PostgreSQL local ou no mesmo host
- Nginx como reverse proxy
- serviços Python gerenciados por systemd

## 6. Motivo para não usar Celery + Redis na fase 1

Embora Celery + Redis sejam uma opção comum para processamento assíncrono, a fase 1 do SIRHOSP não exige essa complexidade.

Contexto atual:

- o sistema não é missão crítica
- os jobs serão executados em horários específicos
- não há necessidade de processamento em tempo real
- haverá poucos usuários simultâneos
- a automação terá baixa concorrência inicial, com alvo de até 3 sessões simultâneas
- a operação ficará a cargo de uma equipe pequena

Diante disso, a combinação abaixo oferece melhor relação entre robustez e simplicidade:

- PostgreSQL para persistência e coordenação
- systemd timers ou cron para agendamento
- management commands para execução
- `uv` para padronizar ambiente e execução dos comandos Python

## 7. Componentes principais

## 7.1 Aplicação web principal

Responsável por:

- autenticação
- autorização simples por role
- dashboard operacional
- consulta rápida de pacientes
- busca textual
- páginas por serviço institucional
- visualização de runs e falhas
- administração básica de jobs

## 7.2 Núcleo de domínio

Responsável por modelar:

- usuários
- pacientes
- internações
- documentos clínicos
- jobs agendados
- runs de ingestão
- resumos de internação

## 7.3 Módulo de automação

Responsável por:

- login no sistema fonte
- navegação Playwright
- extração de dados
- normalização de texto
- persistência no banco

Esse módulo deverá ser dividido por conector, por exemplo:

- `medical_evolution`
- `prescriptions`
- `current_inpatients`

## 7.4 Modo laboratório

Responsável por:

- testar novos fluxos interativos
- descobrir seletores
- validar caminhos de navegação
- gerar fixtures sintéticas

Não deve ser dependência direta do portal web.

## 8. Estratégia de jobs

## 8.1 Modelo de execução

Os jobs do SIRHOSP serão executados por comandos do Django, disparados por systemd timers ou cron.

Exemplos:

- `manage.py run_due_jobs`
- `manage.py sync_current_inpatients`
- `manage.py extract_medical_evolutions`
- `manage.py extract_prescriptions`
- `manage.py refresh_admission_summaries`

## 8.2 Coordenação pelo PostgreSQL

O PostgreSQL será usado para:

- armazenar a configuração dos jobs
- registrar execuções
- impedir duplicidade de execução
- controlar concorrência
- registrar falhas e retries

Técnicas previstas:

- tabelas `scheduled_job` e `ingestion_run`
- status explícitos (`pending`, `running`, `succeeded`, `failed`)
- advisory locks do PostgreSQL
- eventualmente `SELECT ... FOR UPDATE SKIP LOCKED` se necessário

## 8.3 Concorrência

O sistema deve suportar até 3 automações simultâneas na fase 1, respeitando o limite operacional já validado com a TI.

A concorrência será controlada no próprio banco, por tipo de job e por quantidade máxima de execuções ativas.

## 9. Modelo de dados inicial

### Entidades principais

#### User

- autenticação local
- papel `admin` ou `user`

#### Patient

- registro do sistema fonte
- nome
- gênero
- data de nascimento

#### Admission

- referência da internação
- paciente
- status
- datas conhecidas

#### ClinicalDocument

- tipo do documento
- categoria profissional
- paciente
- internação
- data/hora do documento
- texto final
- hash do conteúdo
- timestamps de captura e atualização

#### ScheduledJob

- nome
- tipo
- ativo/inativo
- janela programada
- parâmetros
- limite de concorrência

#### IngestionRun

- job associado
- status
- horário de início e fim
- mensagem operacional
- totais processados

#### AdmissionSummary

- internação
- resumo atual
- última atualização
- janela móvel utilizada

## 10. Estratégia para resumo de internação

O resumo da internação será recalculado incrementalmente.

Estratégia inicial:

- manter o resumo vigente armazenado
- a cada nova captura, enviar ao LLM:
  - resumo anterior
  - últimos 2 dias
  - evolução atual
- substituir o resumo anterior pelo novo resultado

Objetivo operacional:

- manter o resumo dos internados atualizado pelo menos até o dia anterior

## 11. Busca clínica inicial

A busca inicial será baseada em texto livre com PostgreSQL Full Text Search.

Filtros previstos:

- paciente
- período
- categoria profissional
- internação
- tipo de documento

Eventos prioritários monitoráveis:

- broncoaspiração
- queda
- úlcera por pressão
- lateralidade
- reintubação
- extubação acidental
- sepse
- transferência UTI
- óbito
- deiscência
- infecção de ferida operatória
- choque
- convulsão

## 12. Primeiros conectores prioritários

1. sincronização de pacientes internados atualmente
2. extração de evoluções médicas
3. extração de prescrições

O conector de evoluções médicas será derivado do MVP `resumo-evolucoes-clinicas`, mas incorporado ao SIRHOSP como módulo de extração reutilizável e persistente.

## 13. Riscos principais

1. fragilidade do scraping diante de mudanças de UI do sistema fonte
2. uso inicial de credencial nominal
3. variações de performance do sistema fonte em horários específicos
4. necessidade de manter fixtures sintéticas para teste seguro
5. crescimento futuro do escopo sem modularização adequada

## 14. Mitigações iniciais

- separar seletores e fluxos por conector
- criar modo laboratório para descoberta de navegação
- manter logs e artefatos sintéticos para depuração
- usar banco relacional com modelo explícito desde o início
- adiar componentes distribuídos até necessidade real
- registrar ADRs para mudanças estruturais

## 15. Evolução futura prevista

Componentes que podem ser adicionados depois, se necessário:

- SSO/LDAP
- fila distribuída com Celery + Redis
- exportação em PDF/XLSX
- múltiplos ambientes formais
- auditoria de acesso por paciente
- busca semântica com pgvector
- resumos especializados mais sofisticados por setor
