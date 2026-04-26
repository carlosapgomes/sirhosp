# Change Proposal: fase-a-integracao-playwright-ingestao-sob-demanda

## Why

A fundação canônica de eventos clínicos no SIRHOSP já está pronta, porém ainda falta conectar o scraper real (MVP `path2.py`) ao fluxo operacional do produto.

Para a reunião com a diretoria, o maior valor imediato é demonstrar o caso de uso fundador: informar registro + período e obter rapidamente timeline/resumo da internação. Esse objetivo exige integração real de extração sob demanda com rastreabilidade operacional e fallback para dados já espelhados.

## What Changes

- Integrar conector Playwright real para evoluções clínicas (adapter de produção), preservando separação laboratório vs produção.
- Implementar fluxo sob demanda orientado a job (`IngestionRun`) com execução assíncrona via management command + PostgreSQL (sem Celery/Redis).
- Implementar estratégia "cache-first":
  - se o período já estiver coberto no banco paralelo, responder imediatamente;
  - se houver lacuna, disparar extração incremental apenas da janela faltante.
- Padronizar mapeamento de payload do scraper (`path2.py` JSON) para o modelo canônico `ClinicalEvent`.
- Referenciar explicitamente o conector externo no repositório `https://github.com/carlosapgomes/resumo-evolucoes-clinicas`, evitando dependência de path local do executor.
- Expor estado operacional mínimo para UI/CLI (queued/running/succeeded/failed + métricas básicas).

Escopo desta fase (A):

- integração sob demanda ponta-a-ponta (request -> job -> extração -> ingestão -> consulta).

Não-objetivos desta fase:

- sincronização diária de todos os internados;
- fechamento automático de alta por detecção de saída da lista de internados;
- orquestração de fan-out diário por setor/leito.

## Phase B (documentada, fora do escopo desta change)

A estratégia de espelhamento periódico de internados e atualização diária ficará registrada em:

- `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/phase-b-roadmap.md`

## Capabilities

### New Capabilities

- `playwright-evolution-connector`: conector de produção para extração de evoluções via Playwright com contrato de dados compatível com o ledger canônico.

### Modified Capabilities

- `evolution-ingestion-on-demand`: passa a exigir execução assíncrona com política cache-first e complemento incremental de lacunas temporais.

## Impact

- **Ingestão**: entrada real de dados via automação Playwright.
- **Operação**: controle de jobs assíncronos por PostgreSQL + commands já aderentes à fase 1.
- **Produto**: menor tempo de resposta para consultas com cobertura prévia e comportamento previsível quando houver lacunas.
- **Governança**: trilha explícita de evolução de fase A -> fase B sem expandir escopo prematuramente.
