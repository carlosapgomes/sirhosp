# Change Proposal: Versioned sector capacity and occupancy history

## Why

O SIRHOSP exibe as contagens do censo mais recente em `/beds`, mas não possui
capacidade oficial por setor, percentual de lotação nem histórico auditável das
medições. A diretoria forneceu capacidades oficiais e a produção já demonstrou
mudanças de identidade, nomes e agrupamentos de setores; aplicar uma tabela
estática aos censos antigos produziria indicadores incorretos e apagaria o
contexto usado em cada cálculo.

## What Changes

- Introduzir um catálogo completo e versionado por data local para capacidades,
  nomes oficiais, códigos do sistema fonte e grupos que compartilham uma única
  capacidade.
- Ativar versões somente para o início de um dia futuro em `America/Bahia`, por
  comando controlado, idempotente e com `--dry-run`.
- Carregar a configuração inicial com 39 grupos de capacidade, 44 dos 47
  códigos atuais cobertos e capacidade oficial conhecida de 658 unidades.
- Persistir uma medição imutável para cada censo completo e aceito após a
  ativação, sem backfill, incluindo configuração, algoritmo, contadores,
  cobertura, percentual e excedente aplicados naquele momento.
- Calcular grupos compartilhados sem duplicar capacidade, incluindo
  Cardiologia (`719`, `2156`) e Centro Obstétrico (`20`, `1110`, `1112`,
  `1114`, `1116`).
- Manter pacientes suspeitos de permanência indevida no numerador enquanto o
  sistema legado os classificar como ocupados, sem criar taxa ajustada.
- Registrar a capacidade 32 da Obstetrícia 3A, mas manter sua lotação
  indisponível e fora da taxa hospitalar até existir o mapeamento dos 16 pares
  cama-berço.
- Persistir resumos diários por grupo e para o hospital, usando média aritmética
  das medições aceitas do dia local.
- Enriquecer `/beds` com capacidade, lotação, excedente, alertas acima de 100%
  e coberturas de capacidade e de cálculo, preservando o detalhamento atual dos
  leitos.
- Tratar códigos novos ou sem capacidade como não calculáveis, sem bloquear o
  censo clínico e sem ocultá-los da interface.
- Não criar página histórica, não recalcular censos anteriores, não excluir
  automaticamente pacientes suspeitos e não importar periodicamente a planilha
  da diretoria nesta entrega.

## Capabilities

### New Capabilities

- `versioned-sector-capacity-catalog`: catálogo integral com vigência diária,
  grupos, códigos, capacidades, políticas de cálculo, ativação controlada e
  configuração inicial auditável.
- `occupancy-measurement-history`: materialização idempotente e imutável da
  lotação de cada censo aceito, incluindo grupos compartilhados, cobertura,
  totais hospitalares e estados não calculáveis.
- `daily-occupancy-summary`: resumo diário persistido por grupo e hospital com
  média, mínimo, máximo, primeira e última medição.
- `bed-status-capacity-view`: apresentação da capacidade e da lotação calculada
  na página autenticada `/beds`, com fallback seguro quando a medição ainda não
  existir.

### Modified Capabilities

- `census-snapshot-processing`: o processamento de um snapshot completo passa
  a materializar, de forma idempotente, sua medição de lotação antes de
  enfileirar o processamento dos pacientes; snapshots anteriores à ativação ou
  sem catálogo aplicável continuam sem estatística.

## Impact

- Código principal afetado: modelos e serviços de `apps/census`, comandos de
  ativação/materialização, integração de `process_census_snapshot`, view e
  template de `/beds` e testes focados.
- Banco de dados: novas tabelas aditivas para versões de catálogo, grupos,
  membros, medições por censo e resumos diários; nenhuma alteração destrutiva
  ou backfill clínico.
- Operação: a configuração inicial exige ativação explícita para uma data
  futura; rollback funcional desativa a integração/UI nova sem apagar o
  histórico já materializado.
- Dependência: a integração automática requer a defesa em profundidade do slice
  GCEC-S2 do change arquivado e concluído
  `openspec/changes/archive/2026-08-16-guard-census-extraction-completeness`
  para nunca medir um snapshot incompleto.
- Privacidade: as novas tabelas armazenam somente identificadores de setor,
  contagens e metadados agregados, nunca nomes de pacientes, prontuários ou
  textos clínicos.
- Risco: **CRITICAL/HIGH-ARCH**, por introduzir modelos temporais, migrações e
  indicadores hospitalares auditáveis. Um ADR sobre catálogo temporal e
  materialização imutável é obrigatório antes do arquivamento do change.
