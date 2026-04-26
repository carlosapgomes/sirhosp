# Design: fase-a-integracao-playwright-ingestao-sob-demanda

## Context

O SIRHOSP já possui:

- modelo canônico de eventos (`ClinicalEvent`), pacientes e internações;
- ingestão idempotente em memória;
- busca e navegação clínica básicas.

O ativo externo disponível é o MVP `path2.py` no repositório `https://github.com/carlosapgomes/resumo-evolucoes-clinicas`, que extrai evoluções por registro + período em JSON com metadados de internação/chunk e deduplicação de origem.

Falta conectar esse ativo ao fluxo operacional do SirHosp de modo sustentável para fase 1, mantendo as restrições:

- monólito Django + PostgreSQL;
- sem Celery/Redis;
- jobs por management commands + cron/systemd timers;
- separação laboratório vs produção no scraping.

## Goals / Non-Goals

### Goals (Fase A)

- Habilitar ingestão sob demanda com scraper real para um paciente e intervalo.
- Usar `IngestionRun` como unidade operacional assíncrona e auditável.
- Implementar política cache-first com extração incremental para lacunas.
- Manter compatibilidade com contrato atual do JSON de evoluções.

### Non-Goals (Fase A)

- Fan-out diário de todos os internados.
- Fechamento automático de internações por relatório de alta/lista diária.
- SLOs avançados, retries distribuídos e telemetria ampliada.

## Decisions

### 1) Adapter de produção para Playwright, desacoplado de parser canônico

**Decisão:** criar interface de conector de extração (`EvolutionExtractorPort`) e implementação Playwright (`PlaywrightEvolutionExtractor`) em camada de ingestão.

**Racional:** permite evoluir internamente sem acoplar o domínio ao script de laboratório.

### 2) Reuso inicial do path2 via estratégia de transição controlada

**Decisão:** no primeiro slice da fase A, permitir execução por subprocesso com contrato JSON estável, encapsulada no adapter.

**Diretriz operacional:** o executor deve clonar `https://github.com/carlosapgomes/resumo-evolucoes-clinicas` em `/tmp` (ex.: `/tmp/resumo-evolucoes-clinicas`) e referenciar `path2.py` a partir desse clone.

**Racional:** reduz risco para demo e acelera time-to-value sem acoplar o OpenSpec a diretório local específico.

**Evolução planejada:** internalizar gradualmente lógica crítica (seletores, navegação e parsing) no código SirHosp sem quebrar o contrato.

### 3) Execução assíncrona por fila leve no PostgreSQL

**Decisão:** seguir sem Celery; criar/usar comando worker para processar `IngestionRun` pendente (queued/running/succeeded/failed).

**Racional:** aderência ao AGENTS.md e simplicidade operacional.

### 4) Política cache-first com janela faltante

**Decisão:** antes de extrair, calcular cobertura temporal já existente para paciente/período; extrair apenas lacunas.

**Racional:** melhora experiência no uso sob demanda e prepara terreno para fase B.

### 5) Contrato de compatibilidade de tipo profissional

**Decisão:** manter aceitação do token legado `phisiotherapy` e mapear para classificação interna canônica sem perda de rastreabilidade de origem.

## Fluxo proposto (Fase A)

1. Usuário solicita ingestão (registro + período).
2. Sistema cria `IngestionRun(status=queued)`.
3. Worker executa run:
   - resolve paciente/internação;
   - calcula lacunas temporais;
   - chama conector Playwright para cada lacuna;
   - ingere eventos via serviço canônico idempotente.
4. Run finaliza com métricas (eventos novos, duplicados, lacunas processadas, duração, erros).
5. UI/endpoint consulta status e resultados.

## Risks / Trade-offs

- **Dependência transitória de subprocesso/path externo**: mitigado por adapter e contrato explícito.
- **Mudanças de seletor no sistema fonte**: mitigado por separação conector + testes com fixtures sintéticas.
- **Sobrecarga de polling de status**: mitigado por endpoint leve e estados simples.

## Migration Plan

1. Introduzir adapter Playwright e contrato de retorno.
2. Integrar worker assíncrono para processar runs queued.
3. Implementar cálculo de lacunas/cache-first.
4. Expor endpoint/visão de status operacional mínimo.
5. Validar fluxo ponta-a-ponta com testes de integração sem dado real.

## Open Questions

- Qual timeout/limite por run é aceitável para ambiente de produção inicial?
  Resp.: 90 segundos porque o sistema do hospital costuma ter delays frequentes em momentos de sobrecarga
- Quais mensagens de erro serão mostradas para usuário final vs somente para log técnico?
  Resp.: Na minha opinião, o usuário precisa ver todas as mensagens de erro, porque isso vai ajudar na correção desses erros inicialmente. Então, no momento, ele precisa ver todos, até a gente conseguir deixar o sistema mais fluido.

## Status de Implementação (Fase A — Slices S1–S5)

Todos os artefatos descritos neste design foram implementados:

- **Adapter Playwright**: `PlaywrightEvolutionExtractor` com `EvolutionExtractorPort`, mapeamento de erros e validação de contrato JSON.
- **Worker assíncrono**: `process_ingestion_runs` com transições `queued -> running -> succeeded/failed` e persistência de métricas.
- **Cache-first**: `gap_planner.py` com cálculo de cobertura temporal e extração incremental de lacunas.
- **Superfície de produto**: views `create_run` e `run_status` com autenticação obrigatória.
- **Hardening**: 187 testes passando, incluindo regressões de falhas operacionais do conector (JSON truncado, tipo errado, arquivo ausente).
- **Contrato de compatibilidade**: token legado `phisiotherapy` preservado; conversão de datas `YYYY-MM-DD` para `DD/MM/YYYY`.

Cobertura de testes: unitária (adapter, serviços, modelos, gap planner) + integração (worker lifecycle, HTTP endpoints, falhas do conector).

## Referência de continuidade (Fase B)

A evolução para espelhamento diário de internados fica registrada em:

- `phase-b-roadmap.md` (nesta mesma change)
