# Proposal

## Why

A equipe de Desospitalização e a diretoria já investigam pendências de pacientes, com foco inicial em longa permanência, mas acompanham sua evolução em uma planilha separada. Integrar esse trabalho ao Prisma permitirá consultar as barreiras ao andamento da investigação, tratamento ou alta no contexto correto da internação, preservando autoria, histórico e uma visão institucional atual.

## What Changes

- Introduzir pendências vinculadas à internação canônica existente, sem criar outro identificador de episódio nem duplicar o vínculo com paciente.
- Permitir cadastro manual com tipo e descrição/observação obrigatórios, sem título separado, responsável designado, prazo ou prioridade. Não restringir por tempo de internação nem por quantidade ou repetição de tipos.
- Usar os estados `Ativa`, `Resolvida` e `Encerrada sem resolução`. Estados finais serão imutáveis; não haverá reabertura, exclusão física, cópia para reinternação ou acompanhamento separado das versões do registro.
- Registrar criação e cada alteração em histórico próprio, com versões, autor e horário. Finalização poderá conter anotação opcional, sem exigir justificativa adicional.
- Criar o grupo Django `Desospitalização`: seus integrantes poderão operar pendências de colegas; nem administrador nem superusuário terão exceção à associação ao grupo. Todos os usuários autenticados poderão consultar, ler histórico e exportar XLSX.
- Encerrar automaticamente pendências ainda ativas quando uma saída da internação for confirmada, com autoria `Sistema`, sem interpretar ausência no censo como saída ou resolução.
- Acessar pendências pela internação selecionada em `/patients/<id>/admissions/`; criar/editar somente na internação atual identificada sem ambiguidade. Após a saída, manter consulta histórica.
- Adicionar `Pendências` ao menu lateral e um agregado dos internados atuais, com visão por paciente como padrão, alternativa por pendência, histórico recolhível, edição rápida e apresentação desktop/mobile.
- Oferecer filtros por status, setor/leito atual, especialidade, tipo, criador, último atualizador e tempo em aberto. Exibir somente ativas por padrão, permitindo consultar também finalizadas da internação atual.
- Mostrar a primeira unidade registrada durante o episódio, incluindo pronto-socorro; quando não identificável, mostrar `Primeira unidade não identificada`.
- Mostrar indicadores hospitalares de pacientes distintos com pendências ativas, idade média das pendências ativas e maior idade. Indicadores não mudarão com filtros, paginação ou modo de visualização.
- Exportar todos os resultados filtrados, uma linha por pendência em seu estado atual, sem versões históricas, usando XLSX em memória.
- Iniciar o catálogo somente com `Outro`; novos tipos serão cadastrados posteriormente pelo administrador.

### Fora de escopo

- Importação da planilha existente, detecção por evoluções, LLM, notificações ou integração de agendamentos/resultados.
- Etapas estruturadas por tipo, subtarefas, Kanban, cálculo de impacto clínico ou priorização automática.
- Cadastro provisório sem internação identificada, sincronização automática disparada pelo formulário ou mudanças no significado das saídas hospitalares.
- Reformulação geral da ingestão, da reconciliação ou do histórico de movimentações; novas fontes para reconstruir o primeiro setor real.
- Deploy, publicação, inclusão automática de usuários no grupo ou execução da suíte de verificação do portal dev implantado.

## Capabilities

### New Capabilities

- `inpatient-pending-items`: catálogo, identidade por internação, autorização de escrita, ciclo de vida, histórico e integração com saída confirmada e reconciliação de episódios.
- `pending-items-portal`: navegação contextual e agregada, edição rápida, consulta de versões, filtros, indicadores hospitalares e exportação XLSX autenticada.

### Modified Capabilities

Nenhuma. Os contratos de identificação canônica, reconciliação de saídas, movimentações e censo continuam válidos; suas implementações recebem apenas integrações necessárias para preservar o novo conteúdo.

## Impact

- Nova área `apps/pending_items/`, migrations aditivas, cadastro administrativo de tipos, bootstrap do grupo e histórico persistido em PostgreSQL.
- Integrações focadas em `apps/patients/`, `apps/ingestion/services.py`, configurações de apps/URLs, templates do portal e contexto do menu lateral.
- Reuso de Django Templates, HTMX, Bootstrap, Playwright e `openpyxl`, já presentes; sem nova infraestrutura ou dependência de produção.
- Riscos principais: mistura de episódios, perda de histórico em consolidação legada, associação incompleta de movimentações, bypass de grupo por superusuário e concorrência entre edição e saída. O design exige bloqueios conservadores e testes dessas fronteiras.
- Planejamento em quatro slices verticais: gestão contextual auditada; encerramento por saída confirmada; acompanhamento agregado; exportação XLSX. Artefatos sujeitos à revisão/aprovação antes da implementação.
