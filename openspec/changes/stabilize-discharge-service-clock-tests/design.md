## Context

`process_discharges` aceita `discharge_date` explícita e compara admissões
encerradas pelo dia operacional configurado. Dois testes criam encerramentos
com `timezone.now() - timedelta(...)`, mas deixam o serviço usar outro
`timezone.now()`. Próximo da meia-noite, fixture e referência caem em dias
operacionais diferentes. Consulte `proposal.md` para a motivação e
`/tmp/sirhosp-slice-PDSPA-S4-report.md` para a reprodução RED.

## Goals / Non-Goals

**Goals:**

- Fazer os dois cenários usarem uma única referência temporal sintética e
  explícita.
- Preservar as asserções atuais de contagem e idempotência.
- Provar que a suíte passa dentro da antiga janela de falha, sem depender dela.

**Non-Goals:**

- Alterar `apps/discharges/services.py` ou qualquer regra clínica.
- Adicionar biblioteca de congelamento de relógio.
- Mudar timezone, persistência, modelos, comandos ou runtime.

## Decisions

### Usar a API temporal já injetável

Cada teste afetado deve construir um `reference_datetime` consciente de fuso,
em horário sintético que não cruza a data operacional após subtrair duas ou
três horas, e passá-lo a `process_discharges(..., discharge_date=...)`. A
admissão encerrada deriva da mesma referência.

Isso testa o contrato pretendido — admissão já encerrada no mesmo dia
operacional — sem trocar o timezone global e sem mock de relógio. A alternativa
de reduzir o intervalo para minutos ainda falharia imediatamente após a
meia-noite; congelar globalmente o relógio adicionaria dependência e escopo sem
necessidade.

### Limitar a correção aos testes

O comportamento observado do serviço está correto para datas em dias
operacionais diferentes. Portanto, qualquer mudança no código de produção seria
uma regressão de domínio. O slice deve parar se a correção exigir arquivo fora
de `tests/unit/test_discharge_service.py`.

## Risks / Trade-offs

- **Fixture deixar de representar o mesmo dia operacional** → derivar os dois
  timestamps da mesma referência explícita e manter as contagens existentes.
- **Correção passar apenas fora da janela crítica** → executar o teste focado
  com a referência determinística e o quality gate oficial; o resultado não
  pode consultar a hora corrente para decidir o dia do cenário.
- **Enfraquecimento de cobertura** → não remover cenários nem asserções e exigir
  revisão independente do diff.
