# Proposal

## Why

A exportação XLSX do Censo Diário dos Pacientes omite os horários disponíveis
na UI e acrescenta uma etapa de download ao ciclo operacional. A investigação
comprovou paridade nos 11 campos usados pelo sistema em quatro setores,
124 linhas, com ambos os horários recuperáveis pelo DOM: há base para propor
uma coleta mais direta, preservando a confiabilidade necessária à ocupação,
à gestão de prontuários e à rastreabilidade das movimentações.

## What Changes

- Substituir a exportação/parse do XLSX pela extração do DOM no coletor
  operacional do censo, mantendo o login, proxy, descoberta de setores,
  CLI, orquestrador e coordenação existentes.
- Preservar os 11 campos aproveitados pelo parser atual e os dois metadados
  de setor, inclusive linhas de leitos sem paciente e as classificações
  existentes. Não incorporar médico, nascimento, transferência ou controles
  adicionais da UI ao contrato de linhas.
- Capturar `Dt Int` e `Dt Mvt` com a precisão efetivamente disponível nos
  tooltips, aguardando sua inicialização e sem inferir horas ausentes.
- Usar página de 100 linhas ou opção nativa maior, confirmando o tamanho,
  percorrendo páginas adicionais quando necessário e comprovando o término.
  A premissa de até 100 pacientes por setor não limita a quantidade de linhas.
- Rejeitar coleta parcial mesmo quando os setores já extraídos superarem o
  mínimo de 40: a execução deve contabilizar todos os setores solicitados,
  inclusive os vazios, sem falhas de setor ou paginação pendentes.
- Preservar o contrato de datas dos consumidores atuais. Propor dois campos
  opcionais de timestamp de origem em `CensusSnapshot`, sem backfill, para
  reter as horas sem alterar identidade de internações ou movimentos.
- Manter o CSV temporário como transporte interno e adicionar um resumo
  agregado de completude validado pelo management command. Não há fallback
  automático para XLSX nem nova opção operacional de múltiplos extratores.

### Não objetivos

- Exibir horas na Trajetória ou mudar sua seleção, ordenação, duração em dias
  ou chave de deduplicação; essa entrega permanece para change posterior.
- Alterar `Admission.admission_date`, `PatientMovement.movement_date`, regras
  de reconciliação, classificação de leitos, faixas etárias ou indicadores.
- Reconstruir horários históricos, criar pacientes para leitos sem prontuário
  ou atribuir a um paciente a movimentação de um leito sem paciente.
- Introduzir serviços, filas, dependências, agendamento ou infraestrutura novos.
- Executar deploy, janela clínica de teste ou navegação hospitalar automática
  durante implementação/CI. A implementação requer aprovação posterior.

### Riscos principais

- Tooltips inicializam após as linhas; ler cedo pode perder horários.
- Cabeçalhos repetidos/ocultos não são intercambiáveis: a variante exportada
  deve ser reconhecida e testada, não escolhida pela visibilidade.
- Rótulos e seletores do legado podem variar; falhas devem impedir publicação
  do lote, não gerar um censo aparentemente completo.
- Datas locais não trazem offset. A interpretação proposta e os limites da
  migração estão explícitos no design, sujeitos à revisão humana.

## Capabilities

### New Capabilities

- `daily-census-extraction`: contrato de extração direta dos campos do censo,
  seleção correta de setor, paginação completa, captura de precisão temporal
  e segurança do transporte operacional.

### Modified Capabilities

- `census-extraction-completeness`: acrescentar contabilização integral dos
  setores solicitados, falha fechada para qualquer setor incompleto e resumo
  agregado verificável, sem reduzir o mínimo existente de 40 setores.
- `census-snapshot-processing`: reter timestamps opcionais da fonte nos
  snapshots mantendo as projeções de data e os efeitos clínicos atuais.

## Impact

- Coletor: `automation/source_system/current_inpatients/extract_census.py`
  e seu README; módulos auxiliares de produção somente se necessários.
- Ponte Django: `apps/census/management/commands/extract_census.py`, parser em
  `apps/census/services.py`, `CensusSnapshot` em `apps/census/models.py` e
  migração aditiva de dois campos opcionais.
- Testes: extração, proxy/readiness, completude, parsing, persistência e
  regressões de movimentos, ocupação e processamento por run.
- Verification: cenários locais sintéticos e evidências agregadas de paridade;
  o código de laboratório não será importado pelo caminho operacional.
- Sem alteração intencional de URLs, telas ou contratos públicos. O transporte
  interno mantém nomes de colunas, mas amplia datas para timestamp e passa a
  exigir resumo de completude: coletor e command devem ser implantados na
  mesma imagem, sem mistura de versões.
- Referências da investigação: `research/census-dom-xlsx-comparison.md` e
  `research/census-dom-production-fields-evidence.json`. São evidências de
  descoberta, não aceite da implementação futura.
