# SLICE-S5 — Painel de resíduo QC para admin

## Handoff de entrada (contexto zero)

Você está retomando um projeto Django 5.x. S1–S4 estão prontos (serviço,
view/url/template, gráfico, drill-down). Este é o último slice: expor o
**resíduo de qualidade (QC)** da identidade conservativa, visível apenas ao
admin, como monitor de integridade dos pipelines de extração. Leia
obrigatoriamente:

1. `AGENTS.md`.
2. `PROJECT_CONTEXT.md`.
3. `openspec/changes/hospital-flow-pressure-dashboard/design.md` (D3 —
   identidade conservativa e resíduo QC).
4. `openspec/changes/hospital-flow-pressure-dashboard/specs/hospital-flow-visualization/spec.md`.
5. `apps/census/flow_service.py` (o resíduo já é calculado por dia na
  chave `residual` de cada dict).
6. `apps/census/views.py` (`hospital_flow_view`).
7. `templates/census/hospital_flow.html`.
8. Este arquivo `slice-prompts/SLICE-S5.md`.

## Pré-condição de branch

```bash
git checkout feature/hospital-flow-pressure-dashboard
```

S1, S2, S3 e S4 já concluídos.

## Decisões congeladas para este slice

- Resíduo QC = valor `residual` já calculado pelo serviço (S1).
- Visibilidade: **somente admin** (`request.user.is_staff` — ou
  `is_superuser`; confirme o critério do projeto lendo views existentes).
- Apresentação: seção **abaixo do gráfico principal**, com mini-gráfico
  OU tabela compacta + legenda curta.
- Cores de limiar (Open Question 2 do design): `|residual|/adc` (razão
  percentual) — amarelo > 3%, vermelho > 5%. Verde caso contrário.
- Sem alterar o cálculo do resíduo (já no serviço).

## Objetivo do slice

Dar ao admin um monitor gratuito de integridade dos pipelines. Se um dia
o resíduo crescer sistematicamente, é sinal de problema de extração.

## Escopo permitido (somente)

- `apps/census/views.py` (edição — computar `residual_series` e
  `residual_quality` condicional a admin; adicionar ao contexto).
- `templates/census/hospital_flow.html` (edição — bloco
  `{% if user.is_staff %}` com a seção QC).
- `tests/unit/test_hospital_flow_view.py` (edição — testar admin vs.
  não-admin).

## Escopo proibido

- `apps/census/flow_service.py` (resíduo já calculado — não alterar).
- Tornar o QC visível a não-admin.
- Alertas/notificações assíncronas (não-goal).
- Novos modelos.

## Limite de alteração

Máximo: **3 arquivos**.

## Requisitos funcionais do slice

1. View: se `request.user.is_staff`, montar:
   - `residual_series` = lista de `{date, residual, residual_pct}` onde
     `residual_pct = abs(residual) / adc * 100` (ou `None` se adc None ou
     residual None).
   - `residual_quality` = "ok" | "warn" | "alert" baseado no **p95** ou
     **máximo** de `residual_pct` na janela (decida e documente).
2. Template: bloco `{% if user.is_staff %}` abaixo do gráfico, com:
   - Título "Indicador de qualidade dos dados (resíduo)".
   - Legenda curta: "Resíduo da identidade
     ΔADC − (admissões − altas − óbitos). Próximo de zero indica
     consistência entre fontes."
   - Mini-tabela ou mini-gráfico com `residual_series`.
   - Indicador de cor conforme `residual_quality`.
3. Não-admin: o bloco não é renderizado (contexto sem as variáveis).

## TDD obrigatório

1. **RED**: testes cobrindo:
   - Admin (`is_staff=True`): contexto tem `residual_series` e
     `residual_quality`; template renderiza a seção (assert no conteúdo,
     ex.: "Indicador de qualidade").
   - Não-admin (`is_staff=False`): contexto **não** tem
     `residual_series` (ou template não renderiza a seção).
   - `residual_pct` correto para um caso sintético (residual=6, adc=600
     → 1.0).
   - Dia com adc None → `residual_pct` é None (não exceção).
   Rodar: deve falhar.
2. **GREEN**: implementar até passar.
3. **REFACTOR**: sem ampliar escopo.

## Gates obrigatórios S5

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`
3. `./scripts/test-in-container.sh lint`
4. (Opcional, se houver mudança em `.md`) `./scripts/markdown-lint.sh`

## Critérios de auto-avaliação

- [ ] Não-admin **não vê** a seção QC?
- [ ] Admin vê a seção com legenda explicativa?
- [ ] Cores de limiar implementadas (3% / 5%)?
- [ ] Dia com adc None não quebra o cálculo (`residual_pct=None`)?
- [ ] O cálculo do resíduo não foi duplicado (reaproveitado do serviço)?
- [ ] Nenhum arquivo fora do escopo foi tocado?
- [ ] Lint e type check sem erros novos?
- [ ] (Change pronto para fechamento — listar pendências do tasks.md §6.)

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-HFPD-S5-report.md` com:

- resumo, checklist, arquivos (before/after), comandos/resultado,
  riscos/pendências, e nota de fechamento do change (próximo: validar
  markdown de todos os `.md` do change e preparar para apply/arquivar).

Pare ao concluir.
