## Why

O relatório estatístico diário já possui runtime desabilitado por padrão, mas os
dois units correspondentes ainda não são publicados pela release imutável e a
ativação depende de inspeção manual não reproduzível das cadências de altas e
recuperação D-1 com óbitos. Sem fechar essas lacunas, instalar ou habilitar o
timer em produção não tem procedência operacional suficiente.

## What Changes

- Anexar `sirhosp-daily-statistics.service` e
  `sirhosp-daily-statistics.timer` à mesma release imutável da imagem e do
  Compose hospitalar, recusando a publicação antes da criação do draft quando
  qualquer asset obrigatório estiver ausente.
- Adicionar um preflight operacional somente leitura e fail-closed que produza
  evidência agregada da tag/asset instalado, configuração futura de ativação,
  cadência horária de altas e execução D-1 bem-sucedida dos quatro extratores,
  incluindo óbitos.
- Garantir que o preflight nunca habilite units, materialize relatórios, execute
  extratores, faça backfill ou exponha mensagens clínicas do journal.
- Documentar checklist humano separado para instalação desabilitada, coleta e
  aceite da evidência, ativação explícita, observação e rollback.
- Cobrir workflow, preflight e runbook com testes estáticos e sintéticos; nenhum
  teste ou implementação deste change operará produção.

Não são objetivos deste change alterar a classificação clínica, reconstruir
dias anteriores, mudar cadências existentes, automatizar o aceite humano ou
introduzir Celery/Redis.

Riscos principais: aceitar evidência antiga ou incompleta, vazar conteúdo do
journal, instalar asset que não corresponde à tag e habilitar o timer por
engano. O contrato será fail-closed, emitirá apenas estado técnico agregado,
comparará procedência dos assets e manterá instalação e ativação como etapas
separadas.

## Capabilities

### New Capabilities

- `daily-statistics-production-activation`: preflight agregado, critérios de
  evidência, checkpoint humano e ativação/rollback seguros do fechamento diário.

### Modified Capabilities

- `release-image-hospital-deploy`: a release imutável passa a distribuir e
  validar também os dois units de estatísticas diárias da mesma tag.

## Impact

Classificação de risco: **CRÍTICO**, por alterar contrato de release e preparar
ativação em ambiente hospitalar. A abordagem reutiliza as decisões já aceitas
nas ADR-0009 e ADR-0011; não introduz nova arquitetura ou fonte clínica.

- Workflow `.github/workflows/publish-release-image.yml` e seus testes de
  contrato.
- Novo preflight operacional em `deploy/`, units existentes e runbook
  `deploy/README.md`.
- Testes unitários estáticos/sintéticos de release e ativação.
- GitHub Releases, host hospitalar com systemd e journal técnico, sem alteração
  de schema, API clínica, fontes de dados ou dependências Python.
- Valor operacional: diretoria e qualidade recebem relatório diário somente
  depois de uma cadeia de publicação e cadências verificável; jurídico e gestão
  de prontuários ganham evidência sem identidade clínica persistida.
