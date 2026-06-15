# SLICE-S1 — Serviço de domínio: agregação estoque/fluxo/resíduo

## Handoff de entrada (contexto zero)

Você está retomando um projeto Django 5.x (monólito modular, PostgreSQL,
sem Celery/Redis). Leia obrigatoriamente, nesta ordem, antes de codar:

1. `AGENTS.md` (regras do projeto, quality gate, anti-patterns).
2. `PROJECT_CONTEXT.md` (arquitetura e estado do sistema).
3. `openspec/changes/hospital-flow-pressure-dashboard/proposal.md`.
4. `openspec/changes/hospital-flow-pressure-dashboard/design.md`.
5. `openspec/changes/hospital-flow-pressure-dashboard/tasks.md`.
6. `openspec/changes/hospital-flow-pressure-dashboard/specs/hospital-flow-visualization/spec.md`.
7. Este arquivo `slice-prompts/SLICE-S1.md`.

Resumo do change: criar um painel "Fluxo Hospitalar" que confronta o
estoque diário de pacientes (ADC do censo snapshot) com o fluxo
(admissões vs. altas+óbitos). Este slice (S1) é o **coração de domínio**:
uma função pura de agregação, sem web, totalmente testável.

## Pré-condição de branch

```bash
git checkout -b feature/hospital-flow-pressure-dashboard
```

Se já existir:

```bash
git checkout feature/hospital-flow-pressure-dashboard
```

## Decisões congeladas para este slice

- Estoque = **ADC** = média diária de `CensusSnapshot` com
  `bed_status='occupied'`, considerando **todos** os setores.
- Inflow = `admissions_dailyadmissioncount.count` por `date`.
- Outflow = `discharges_dailydischargecount.count` +
  `deaths_dailydeathcount.count` por `date`.
- Identidade conservativa:
  `resíduo(dia) = (ADC(dia) − ADC(dia−1)) − (admissões − altas − óbitos)`.
- Sem mudança de schema. Sem persistência nova. Função pura de leitura.
- Sem web, sem views, sem templates neste slice.

## Objetivo do slice

Criar `apps/census/flow_service.py` com função
`compute_hospital_flow(start, end, sector=None)` que retorna, por dia no
intervalo `[start, end]`, um dicionário estruturado com estoque, fluxo,
líquido e resíduo. Implementação 100% guiada por testes (TDD).

## Contrato da função (assinatura obrigatória)

```python
from datetime import date

def compute_hospital_flow(
    start: date,
    end: date,
    sector: str | None = None,
) -> list[dict]:
    """Agrega estoque (ADC) e fluxo (admissões/altas/óbitos) por dia.

    Args:
        start: data inicial (inclusiva).
        end: data final (inclusiva). Deve ser >= start.
        sector: se informado, filtra o estoque (CensusSnapshot.setor)
            e o fluxo não é filtrado por setor (fontes dedicadas são
            hospital-total). Default: hospital-total.

    Returns:
        Lista ordenada por data, um dict por dia, com chaves:
            date (date), adc (float|None), n_snapshots (int),
            admissions (int), discharges (int), deaths (int),
            net_flow (int), delta_adc (float|None),
            residual (float|None).
        adc=None quando não há snapshot no dia.
        delta_adc=None e residual=None no primeiro dia (sem anterior).
    """
```

## Fontes de dados (modelos existentes — NÃO alterar)

- `apps.census.models.CensusSnapshot`: `captured_at` (DateTime),
  `bed_status` (CharField, choices), `setor` (CharField),
  `prontuario` (CharField). Constante `BedStatus.OCCUPIED == 'occupied'`.
- `apps.admissions.models.DailyAdmissionCount`: `date` (DateField),
  `count` (IntegerField). **Atenção: o campo se chama `count`**
  (palavra reservada SQL); acesse via atributo Python `obj.count`, evite
  `Count()` do ORM no mesmo contexto.
- `apps.discharges.models.DailyDischargeCount`: mesmo formato.
- `apps.deaths.models.DailyDeathCount`: mesmo formato.

## Escopo permitido (somente)

- `apps/census/flow_service.py` (novo).
- `tests/unit/test_hospital_flow_service.py` (novo).

## Escopo proibido

- Views, URLs, templates.
- `templates/includes/sidebar.html`.
- Qualquer modelo/migration.
- Outros apps além de `census` (apenas importar para leitura).

## Limite de alteração

Máximo: **2 arquivos**.

## Requisitos funcionais do slice

1. `compute_hospital_flow` cobre todos os dias de `start` a `end`
   inclusivos (inclusive dias sem snapshot nem fluxo — retornam zeros e
   `adc=None`).
2. `adc(dia)` = média de `CensusSnapshot` com
   `bed_status=BedStatus.OCCUPIED` cujo `captured_at::date == dia`,
   dividida pelo número de snapshots distintos nesse dia. Se nenhum
   snapshot: `adc=None`, `n_snapshots=0`.
3. `sector` informado filtra `CensusSnapshot.setor == sector` (estoque);
   fluxo permanece hospital-total (fontes dedicadas não têm setor).
4. `admissions(dia)` = `DailyAdmissionCount.count` para `date==dia`, ou 0.
5. `discharges(dia)` e `deaths(dia)` análogos.
6. `net_flow(dia) = admissions − discharges − deaths`.
7. `delta_adc(dia) = adc(dia) − adc(dia−1)`; `None` no primeiro dia.
8. `residual(dia) = delta_adc − net_flow`; `None` quando `delta_adc` é
   `None`.
9. Performance aceitável: usar agregações do ORM
   (`values('captured_at__date').annotate(...)`) e dicts em memória,
   evitar N+1.

## TDD obrigatório

1. **RED**: escrever `tests/unit/test_hospital_flow_service.py` com
   fixtures sintéticos (criar `CensusSnapshot`, `DailyAdmissionCount`,
   etc. via ORM em `setUp`) cobrindo:
   - ADC com múltiplos snapshots no mesmo dia (média correta).
   - ADC com um único snapshot.
   - Dia sem snapshot → `adc=None`, `n_snapshots=0`.
   - Inflow/outflow de cada fonte dedicada.
   - `net_flow`, `delta_adc` e `residual` calculados corretamente.
   - Primeiro dia → `delta_adc=None`, `residual=None`.
   - Filtro por `sector` filtra estoque mas não fluxo.
   - Intervalo com dias vazios no meio (retorna zeros + `adc=None`).
   Rodar: deve falhar (função ainda não existe).
2. **GREEN**: implementar `flow_service.py` até todos os testes passarem.
3. **REFACTOR**: eliminar duplicação, nomes claros, sem ampliar escopo.
   Rodar testes novamente — devem continuar passando.

## Gates obrigatórios S1

Registrar comando + exit code + resultado (pass/fail) no relatório:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`
3. `./scripts/test-in-container.sh lint`

## Critérios de auto-avaliação (verifique ANTES de declarar pronto)

- [ ] A função é **pura** (sem efeitos colaterais, sem escrita em banco)?
- [ ] Todos os casos de teste do TDD passam?
- [ ] Nenhum arquivo fora do escopo permitido foi tocado?
- [ ] O campo `count` das fontes dedicadas foi acessado corretamente (sem
      colidir com `Count` do ORM)?
- [ ] Dias sem snapshot retornam `adc=None` (não 0, não exceção)?
- [ ] O primeiro dia do intervalo tem `delta_adc=None` e `residual=None`?
- [ ] Não há `<!-- markdownlint-disable -->` em nenhum `.md`?
- [ ] Lint e type check sem erros novos?

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-HFPD-S1-report.md` com:

- resumo do slice;
- checklist de aceite (critérios de auto-avaliação acima);
- lista de arquivos alterados;
- snippets before/after por arquivo (para arquivo novo, snippet integral
  comentado);
- comandos executados e resultados (exit codes);
- riscos/pendências;
- próximo passo sugerido (S2).

Pare ao concluir. Não iniciar S2.
