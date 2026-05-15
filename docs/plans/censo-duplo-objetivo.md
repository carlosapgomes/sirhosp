# Censo hospitalar: diagnóstico e plano de ação para os dois objetivos macro

Data base: 09/05/2026

---

## 1. Diagnóstico — o problema dos dados

### 1.1 Fontes de censo comparadas

Temos duas fontes de censo, ambas extraídas do sistema TASY, por páginas diferentes:

|                                   | Nosso scraping (Playwright)     | Censo oficial (arquivo TXT)       |
| --------------------------------- | ------------------------------- | --------------------------------- |
| **Método**                        | Varre todos os setores clicando | Arquivo gerado pelo sistema fonte |
| **Horário da captura analisada**  | 07/05 21:00                     | 09/05 (retroativo ao dia 09)      |
| **Pacientes listados**            | 661                             | 634                               |
| **Pacientes sem evolução em 72h** | 44 (6,7%)                       | 23 (3,6%)                         |

### 1.2 Pacientes-fantasma (sem evolução há 72h+)

Ambos os censos capturam pacientes que não estão mais no hospital. Usando o critério conservador de **72h sem nenhuma evolução clínica**:

- Em ambos os censos (após limpeza): **577** pacientes em comum
- Apenas no nosso (fantasmas removidos): **40** pacientes (a maioria de admissões do dia 08-09/05, capturados às 21h mas não retroativamente)
- Apenas no oficial (fantasmas removidos): **34** pacientes (não capturados pelo nosso scraping)

### 1.3 Setores que inflam o nosso censo

Setores de observação/passagem que o censo oficial tende a excluir mas nosso scraping captura:

| Setor                        | Pacientes extras | Tipo MS                   |
| ---------------------------- | ---------------- | ------------------------- |
| Internação Centro Obstétrico | 11               | Observação/pré-parto      |
| Sala de Medicação — Obs CO   | 7                | Observação                |
| Sala de Observação Adulto    | 6                | Observação                |
| Emergência Adulto            | 5                | Misto (>24h = internação) |

### 1.4 Pacientes com alta no banco mas ainda no censo

Após a limpeza dos 72h, ainda restam 11 pacientes com `discharge_date` preenchido na admissão mas que continuam listados como ocupados no censo. O caso extremo: MARIANA DO AMPARO MOURA (4113296), alta em **junho de 2022**, ainda aparece no censo como ocupante do leito 1998 (Sala de Medicação CO), junto com outros 4 pacientes com datas de alta diferentes no mesmo leito.

---

## 2. Inventário de comandos existentes

### Censo

| Comando                   | O que faz                                                                                              | Quando roda             |
| ------------------------- | ------------------------------------------------------------------------------------------------------ | ----------------------- |
| `extract_census`          | Varre o sistema fonte via Playwright e persiste todas as linhas do censo em `CensusSnapshot`           | systemd timer a cada 8h |
| `process_census_snapshot` | Lê o último `CensusSnapshot`, cria/atualiza `Patient` e enfileira runs de admissão (`admissions_only`) | Após `extract_census`   |
| `sync_current_inpatients` | Não implementado (reservado)                                                                           | —                       |

### Detecção de altas não registradas (criados nesta sessão)

| Comando                             | Flags                                                                                                           | O que faz                                                                                                                                                                                                                                                                                                      |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `report_suspected_stale_inpatients` | `--output` (padrão: `/tmp/suspected_stale_inpatients.csv`), `--include-census-present`, `--only-census-present` | Busca admissões ativas (`discharge_date IS NULL`) cuja admissão mais recente do paciente também é ativa, filtra as que **não têm evento clínico nos últimos 72h**, e gera CSV. Por padrão exclui pacientes que ainda estão no censo; `--only-census-present` mostra só quem está no censo (relatório para TI). |
| `refresh_suspected_admissions`      | `--input` (padrão: `/tmp/suspected_stale_inpatients.csv`)                                                       | Lê o CSV do comando acima e enfileira um `IngestionRun` do tipo `admissions_only` para cada paciente, para o worker atualizar o `discharge_date` consultando o sistema fonte.                                                                                                                                  |
| `sync_missing_discharges`           | `--dry-run`                                                                                                     | Varre **todos** os pacientes com admissão ativa que **não** estão no último censo como ocupados e enfileira atualização em massa. Ignora o critério de 72h — é limpeza geral.                                                                                                                                  |

### Ingestão de evoluções

| Comando                                           | O que faz                                                                                                                                              |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `process_ingestion_runs --loop --sleep-seconds 5` | Worker contínuo: processa runs enfileiradas. Fluxo: captura admissões → planeja gaps → extrai evoluções → ingere no modelo canônico (`ClinicalEvent`). |

### Altas

| Comando                 | O que faz                                                      |
| ----------------------- | -------------------------------------------------------------- |
| `extract_discharges`    | Baixa PDF diário de altas do sistema fonte.                    |
| `process_discharge_pdf` | Extrai dados do PDF e atualiza `discharge_date` nas admissões. |

### Sumários

| Comando                                  | O que faz                                                                |
| ---------------------------------------- | ------------------------------------------------------------------------ |
| `process_summary_runs --pipeline --loop` | Worker de sumarização: gera resumos de internação em duas fases via LLM. |

---

## 3. Os dois objetivos macro

### Objetivo A — Fotografia real da ocupação (assistencial)

**O que é:** mostrar, a qualquer momento do dia, **quem está fisicamente dentro do hospital**, em qual setor/leito, independentemente do tempo de permanência ou do tipo de leito.

**Por que importa:** a direção precisa saber a realidade operacional — superlotação na emergência, leitos de observação ocupados como internação, pacientes aguardando vaga. O sistema fonte distorce essa visão porque retém pacientes que já saíram e exclui setores de passagem.

**Fonte de dados:** scraping amplo (nosso `extract_census` atual), que captura **tudo** — todos os setores, todos os leitos ocupados.

### Objetivo B — Censo oficial (gerencial / índices MS)

**O que é:** gerar os indicadores exigidos pelo Ministério da Saúde (taxa de ocupação, média de permanência, paciente/dia) seguindo as definições da Portaria 312/2002.

**Por que importa:** subsidiar a direção em negociações com órgãos superiores (expansão de leitos, recursos), substituir o processo manual atual (planilhas, critérios subjetivos) por um pipeline automatizado e auditável.

**Fonte de dados:** censo oficial (arquivo TXT da segunda página do TASY), capturado 1×/dia na madrugada do dia seguinte.

---

## 4. Estratégia proposta

### 4.1 Limpeza de fantasmas (comum aos dois objetivos)

**Regra:** paciente sem **nenhuma** evolução clínica registrada nos últimos **48h** é considerado fantasma e **excluído** de ambos os relatórios.

Justificativa: 48h é um limite seguro — o hospital confirmou que nenhum paciente internado fica mais de 48-72h sem evolução (médica, enfermagem, fisioterapia ou serviço social). 24h pegaria recém-internados.

**Como aplicar:** antes de gerar qualquer relatório, cruzar a lista de pacientes do censo com `ClinicalEvent` e remover quem não tem evento em 48h.

### 4.2 Classificação observação × internação (para o Objetivo B)

Seguindo a Portaria 312/2002:

| Situação                                                       | Classificação | Entra no censo oficial? |
| -------------------------------------------------------------- | ------------- | ----------------------- |
| Paciente no hospital há **< 24h** (admission_date < 24h atrás) | Observação    | ❌ Não                  |
| Paciente no hospital há **≥ 24h**                              | Internação    | ✅ Sim                  |
| Óbito (independente do tempo)                                  | Internação    | ✅ Sim                  |
| Setor UTI / Semi-intensivo                                     | Internação    | ✅ Sempre               |

**Como aplicar:** derivar do tempo de permanência do paciente. A `admission_date` na tabela `Admission` indica quando a internação formal começou, mas pacientes podem estar no hospital antes disso (em observação na emergência, aguardando vaga). O critério seguro é: calcular o tempo desde a entrada no hospital (que pode ser anterior à `admission_date`) e classificar como observação se < 24h. Quando não houver admissão registrada (paciente recém-chegado ao censo, ainda não sincronizado pelo worker), tratá-lo como **não classificado** — não assumir que é observação.

### 4.3 Dois momentos de captura

| Captura                  | Frequência                             | Método                                                          | Gera                                                      |
| ------------------------ | -------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------------- |
| **Ampla (Objetivo A)**   | A cada 8h (manter systemd timer atual) | Nosso `extract_census` via Playwright                           | CSV com ocupação total, todos os setores, todos os leitos |
| **Oficial (Objetivo B)** | 1×/dia, madrugada (≈01:00)             | Novo `extract_official_census` via Playwright na segunda página | CSV com leitos de internação, para índices MS             |

### 4.4 Pipeline de geração de relatórios

```text
┌────────────────────┐
│ extract_census     │  8/8h — scraping amplo
│ (amplo)            │
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│ Limpeza 48h        │  Remove pacientes sem ClinicalEvent em 48h
│ (fantasmas)        │
└────────┬───────────┘
         │
         ├──► Relatório A1: Ocupação total (todos os setores, fotografia real)
         │
         └──► Relatório A2: Pacientes-fantasma detectados (para enviar à TI)


┌────────────────────┐
│ extract_official   │  1×/dia, madrugada — scraping da página de censo oficial
│ _census (oficial)  │
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│ Limpeza 48h        │  Remove pacientes sem ClinicalEvent em 48h
│ (fantasmas)        │
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│ Classificação      │  <24h = observação, ≥24h = internação
│ obs × internação   │
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│ Indicadores MS     │  Taxa de ocupação, média de permanência, paciente/dia
│ (Objetivo B)       │  leito/dia, taxa de mortalidade
└────────────────────┘
```text

---

## 5. Próximo passo imediato

Migrar o scraper do censo para a segunda página do TASY (a que gera o arquivo TXT oficial), criando o comando `extract_official_census`. Você fará o Codegen e eu integrarei no padrão dos extractors existentes.

Após isso:

1. **Investigar os 34 pacientes** que o oficial captura e nós não (por que o scraping amplo não os pega?)
2. **Ajustar o limiar de 72h para 48h** nos comandos existentes
3. **Criar os relatórios A1, A2 e B** como comandos ou views no dashboard
4. **Decidir o que fazer com os comandos antigos:** aposentar, modificar ou manter

---

## 6. Apêndice — todos os comandos e flags

### `report_suspected_stale_inpatients`

```text
Gera CSV de admissões ativas sem evolução há 72h.

Flags:
  --output PATH               Caminho do CSV (default: /tmp/suspected_stale_inpatients.csv)
  --include-census-present    Mostra pacientes dentro E fora do censo
  --only-census-present       Mostra APENAS pacientes dentro do censo (relatório para TI)

Uso típico:
  # Relatório para TI (pacientes no censo sem evolução):
  report_suspected_stale_inpatients --only-census-present

  # Uso interno (altas não sincronizadas):
  report_suspected_stale_inpatients
```text

### `refresh_suspected_admissions`

```text
Lê CSV do report_suspected_stale_inpatients e enfileira admissions_only.

Flags:
  --input PATH                Caminho do CSV (default: /tmp/suspected_stale_inpatients.csv)

Uso típico:
  refresh_suspected_admissions
  # Aguardar worker process_ingestion_runs --loop
  # Re-rodar report_suspected_stale_inpatients
```text

### `sync_missing_discharges`

```text
Enfileira atualização para TODOS pacientes com admissão ativa fora do censo.

Flags:
  --dry-run                   Lista sem enfileirar

Uso típico:
  sync_missing_discharges --dry-run   # Preview
  sync_missing_discharges             # Enfileirar
```text

### `extract_census`

```text
Varre sistema fonte (todos os setores) e persiste CensusSnapshot.

Flags:
  --headless                  Modo headless (sem navegador visível)

Uso: systemd timer a cada 8h
```text

### `process_census_snapshot`

```text
Processa último CensusSnapshot: cria/atualiza Patient e enfileira admissions_only.

Flags:
  --run-id N                  ID específico de IngestionRun para associar

Uso: após extract_census
```text

### `process_ingestion_runs`

```text
Worker contínuo de ingestão. Processa runs enfileiradas.

Flags:
  --loop                      Modo contínuo
  --sleep-seconds N           Intervalo entre polls (default: 5)
  --script-path PATH          Script Playwright alternativo

Uso: processo contínuo (systemd ou container)
```text

### `extract_discharges`

```text
Baixa PDF diário de altas do sistema fonte.

Flags:
  --headless                  Modo headless
```text

### `process_discharge_pdf`

```text
Extrai pacientes do PDF de altas e atualiza discharge_date.
```

---

## 7. Referências

- Portaria MS nº 312, de 30 de abril de 2002 — Padronização da Nomenclatura do Censo Hospitalar
- `docs/architecture.md` — Arquitetura do sistema
- `deploy/README.md` — Agendamento systemd
