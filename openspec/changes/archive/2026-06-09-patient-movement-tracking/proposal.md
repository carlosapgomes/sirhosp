# Change Proposal: patient-movement-tracking

## Why

O censo hospitalar extrai, 3-4 vezes ao dia, um snapshot de todos os pacientes
internados. Com as novas colunas `data_movimentacao`, `tipo_alta` e `origem`
(recentemente adicionadas ao `CensusSnapshot`), é possível reconstruir a
trajetória de cada paciente pelos setores do hospital durante uma internação.

Hoje não existe mecanismo para responder perguntas como:

1. por quais setores o paciente passou e por quantos dias em cada um?
2. quantos pacientes passaram pelo setor X nos últimos 7 dias?
3. qual o tempo médio de permanência por setor?
4. quais setores mais recebem pacientes de um determinado setor de origem?
5. há pacientes há mais de 15 dias no mesmo setor?
6. existem setores com mais entradas do que saídas (gargalos)?

Esta change implementa o modelo `PatientMovement`, as views e os templates para
responder a todas essas perguntas.

## What Changes

1. Criar modelo `PatientMovement` com chave única `(patient, movement_date,
   sector)` e campo `sequence` para ordenação cronológica.
2. Criar serviço de processamento que, a partir do `CensusSnapshot` mais
   recente, faz upsert em `PatientMovement` detectando mudanças efetivas de
   setor e fechando a trajetória quando `tipo_alta` está preenchido.
3. Exibir timeline de trajetória e dias por setor na página de detalhes da
   internação (`Admission`).
4. Criar menu `Setores` no sidebar, com duas subpáginas:
   - **Ocupação** (`/setores/ocupacao/`): pacientes que passaram pelo setor X
     no período Y.
   - **Indicadores** (`/setores/indicadores/`): análises agregadas (tempo
     médio por setor, fluxo entre setores, longa permanência, gargalos).
5. Atualizar `process_census_snapshot` (ou criar comando complementar) para
   alimentar `PatientMovement` a cada ciclo de censo.

## Scope

| Camada | Arquivos |
| --- | --- |
| Modelo | `apps/census/models.py` (novo `PatientMovement`) |
| Migrations | `apps/census/migrations/0013_patientmovement.py` |
| Serviço | `apps/census/services.py` (`upsert_patient_movements`) |
| Management command | `apps/census/management/commands/sync_patient_movements.py` ou hook em `process_census_snapshot` |
| Views | `apps/services_portal/views.py` |
| URLs | `apps/services_portal/urls.py` |
| Templates | detalhes da internação, `setores/ocupacao.html`, `setores/indicadores.html`, sidebar |
| Testes | unitários (modelo, serviço, views) e integração (commands) |

## Non-Goals

- Não reprocessar snapshots históricos na fase inicial — apenas snapshots
  futuros.
- Não criar API REST para consulta de movimentações.
- Não alterar a extração do censo (Playwright/XLSX) — as colunas já estão
  disponíveis.
- Não introduzir gráficos nas páginas de setores no MVP — apenas cards e
  tabelas.
- Não migrar dados de snapshots já existentes no banco automaticamente.

## Assumptions

- `data_movimentacao` no snapshot está no formato `DD/MM` ou `DD/MM/AAAA`.
- `tipo_alta` vazio significa paciente ativo; qualquer valor preenchido indica
  fim da internação (alta, transferência externa ou óbito).
- `origem` vazio + `data_movimentacao` igual à data de internação = primeiro
  setor da internação.
- O processamento do `PatientMovement` ocorre como etapa adicional após o
  `process_census_snapshot`, no mesmo ciclo agendado.
- A navegação `Setores` aparece no sidebar apenas para usuários autenticados
  (mesmo controle de acesso do dashboard).

## Risks

- `data_movimentacao` pode não ser granular o suficiente (só dia, sem hora) —
  duas movimentações no mesmo dia ficam ambíguas. Mitigado pela unique key
  `(patient, movement_date, sector)`.
- Snapshots podem falhar ocasionalmente, criando lacunas na trajetória.
- O campo `tipo_alta` pode ter semântica diferente da esperada (ex: valor
  numérico diferente de 0 pode não significar alta).

## Mitigations

- Usar `movement_date` + `sequence` para reconstruir ordem cronológica com
  heurística de `origem` como fallback.
- Exibir indicador de "última atualização" nas páginas de setor para
  transparência sobre dados faltantes.
- Documentar a interpretação de `tipo_alta` como configurável se a semântica
  mudar no futuro.

## Capabilities

### Added Capabilities

- `patient-movement-model`: modelo `PatientMovement` com unique constraint e
  campo `sequence` para rastrear trajetória do paciente entre setores.
- `patient-trajectory-view`: exibição de linha do tempo de movimentações e
  dias por setor na página de detalhes da internação.
- `sector-occupation-page`: página de ocupação por setor com filtro de período
  e tabela de pacientes.
- `sector-indicators-page`: página de indicadores agregados por setor (tempo
  médio, fluxo, longa permanência, gargalos).
- `sidebar-sectors-menu`: menu `Setores` no sidebar com sublinks para Ocupação
  e Indicadores.

### Modified Capabilities

- `census-snapshot-processing`: adiciona etapa de upsert em `PatientMovement`
  após `process_census_snapshot`.

## Impact

- Gestão de leitos ganha visibilidade sobre trânsito de pacientes e gargalos
  operacionais.
- Equipe clínica visualiza a trajetória completa do paciente dentro do
  hospital em uma única tela.
- A mudança usa apenas dados já extraídos (colunas adicionadas em change
  anterior) e não requer nova integração com o sistema fonte.
- Volume de dados é baixo (~50K registros/ano), sem impacto relevante no
  PostgreSQL.
