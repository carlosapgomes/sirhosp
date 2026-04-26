# Roadmap Fase B (fora do escopo da change de Fase A)

## Objetivo

Evoluir de ingestão sob demanda para espelhamento operacional diário de pacientes internados, com dados quase imediatos para diretoria, qualidade e jurídico.

## Resultado esperado

- Base clínica de internados atualizada diariamente.
- Menor latência para consultas por registro/período.
- Fechamento consistente de internações quando paciente receber alta.

## Capabilities-alvo (futuras)

1. **Snapshot diário de internados**
   - Coletar lista de pacientes internados por setor/unidade.
   - Persistir espelho read-only dos internados do dia.

2. **Fan-out de atualização clínica diária**
   - Para cada internado ativo, disparar job incremental de evoluções.
   - Controlar concorrência com fila leve no PostgreSQL.

3. **Detecção de alta e fechamento operacional**
   - Detectar saída da lista diária de internados.
   - Marcar internação como encerrada no espelho quando evidência de alta for confirmada.

4. **Telemetria e retries operacionais**
   - Contagem de sucesso/falha por rodada diária.
   - Retentativas com limite e classificação de erro transitório vs persistente.

## Sequência sugerida de implementação (quando abrir a change da Fase B)

- **S1-B:** conector de lista de internados + modelo de snapshot diário.
- **S2-B:** planejador diário de jobs por internado ativo.
- **S3-B:** atualização incremental de evoluções por internado.
- **S4-B:** fechamento de internação por detecção de alta.
- **S5-B:** hardening operacional (retries, métricas, painéis de execução).

## Dependências e pré-requisitos

- Fase A concluída com conector sob demanda estável.
- Contrato de identificação de paciente robusto (registro/CNS/CPF/reconciliação).
- Comandos agendáveis por cron/systemd timers em ambiente alvo.

## Não fazer nesta Fase B inicial

- Introduzir Celery/Redis sem nova ADR.
- Expandir para todos os tipos documentais antes de estabilizar evoluções.
- Acoplar regras de negócio diretamente em comandos de scraping.
