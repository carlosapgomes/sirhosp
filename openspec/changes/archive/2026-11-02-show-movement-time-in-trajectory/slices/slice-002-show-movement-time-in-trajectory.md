# SMT-S2 — Hora exibida na Trajetória quando disponível

## 1. Identity

- Change: `show-movement-time-in-trajectory`.
- Task: `openspec/changes/show-movement-time-in-trajectory/tasks.md`, grupo 2.
- Dependências: SMT-S1 aceito (campo populado pelo upsert); contrato
  proposto, não execução autorizada.

## 2. Objective

Exibir a hora real de movimentação na seção `Trajetória` da página de
admissão quando disponível, com degradação graciosa para data-only na
mesma linha do tempo.

Entrega vertical: contexto da view → template → testes de renderização →
verificação de produto. Estilo/posicionamento sem dado não aceitam o slice.

## 3. Read first

- `AGENTS.md`, `PROJECT_CONTEXT.md`, `openspec/config.yaml`.
- `openspec/changes/show-movement-time-in-trajectory/{proposal.md,design.md}`
  — D4/D5.
- Delta `specs/patient-trajectory-view/spec.md` deste change; spec vigente
  `openspec/specs/patient-trajectory-view/spec.md`.
- Contrato e relatório aceitos de SMT-S1.
- `apps/patients/views.py` (bloco PMT-S3 da trajetória),
  `apps/patients/templates/patients/timeline.html` e
  `_patient_trajectory.html`.
- `tests/unit/test_patient_trajectory.py` e testes de view de admissão
  existentes; `docs/dev-verification.md` (camada complementar sob demanda).

## 4. Requirements → Evidence

| ID  | Requisito observável                                                                                                                                     | Evidência planejada                                                                   |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| R1  | Entrada com hora exibe `DD/MM/AAAA HH:MM` na timezone configurada; sem hora exibe `DD/MM/AAAA`; nenhum placeholder `00:00`.                              | Testes de render/view com movimentos mistos; verificação de produto.                  |
| R2  | Trajetória com granularidade mista (entradas antigas date-only e novas com hora) renderiza corretamente as duas formas, ordenada como hoje.              | Fixtures sintéticas na mesma trajetória; asserções por entrada.                       |
| R3  | Durações por setor continuam date-based na presença de horas; identidade/ordenação inalteradas.                                                          | Regressões de `days` com movimentos com e sem hora.                                   |
| R4  | Verificação de produto da renderização mista em uma única trajetória no portal dev com dataset fictício (ou template test equivalente), sem dados reais. | Evidência de browser/template conforme `docs/dev-verification.md` ou teste de render. |

Referência normativa: delta `patient-trajectory-view` inteiro; D4/D5 do
design.

## 5. Expected blast radius

Esperado:

- `apps/patients/views.py` (contexto da trajetória),
  `apps/patients/templates/patients/timeline.html`;
- testes de view/template e, se necessário, fixture de teste.

Sensível: não mudar cálculo de `days`, query/ordenação, cabeçalho de
admissão, outras seções da página, modelos ou upsert (SMT-S1 fechou o
persistência). Sem novo endpoint, componente ou dependência.

## 6. Failing-before plan

1. RED R1/R2: test de render com paciente sintético contendo dois
   movimentos — um com `source_movement_at`, outro NULL — asserindo
   `DD/MM/AAAA HH:MM` no primeiro e `DD/MM/AAAA` (sem `00:00`) no segundo;
   falha antes da alteração da view/template.
2. RED R3 (caracterização): `days` iguais com e sem horas presentes —
   prova de não-regressão do cálculo.

## 7. Implementation constraints

- Seguir `AGENTS.md`; menor mudança correta; convenções de template do
  projeto.
- A hora vem exclusivamente do campo persistido (nunca de snapshot em
  join na view); exibição via filtro de data do Django com timezone do
  projeto (D4).
- Durações permanecem calculadas com `movement_date` (D5); nenhuma
  alteração de ordenação/identidade.
- Sem horas na entrada de internação da trajetória (o cabeçalho da
  admissão permanece a fonte da hora de internação).
- Verificação de produto somente com dados fictícios; nunca dados reais.

## 8. Validation

### Focused validation

- TDD: RED/GREEN de renderização com granularidade mista.
- Regressões: `tests/unit/test_patient_trajectory.py`, testes de view de
  admissão/portais afetados.

### Project-required gates

- `./scripts/test-in-container.sh quality-gate` e `integration` separada
  no estado final; `./scripts/markdown-lint.sh` quando `.md` alterado.

### Runtime / verification evidence

- Verificação de produto (R4): portal dev com dataset fictício e sessão
  efêmera conforme `docs/dev-verification.md` (camada sob demanda, janela
  dev autorizada), ou teste de render equivalente declarado no relatório;
  evidência distingue o que foi provado por teste do que foi visto em
  browser.

## 9. Acceptance criteria

- [ ] R1: hora exibida quando disponível; data-only sem placeholder.
- [ ] R2: trajetória mista renderiza as duas formas, mesma ordenação.
- [ ] R3: durações e identidade inalteradas com horas presentes.
- [ ] R4: verificação de produto registrada (método declarado).
- [ ] Gates oficiais e Markdown aprovados; relatório completo.

## 10. Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se a exibição da hora sugerir mudança de
interpretação clínica (por exemplo, equipe pedir durações horárias), se o
template atual não comportar a anotação sem redesign ou se a verificação de
produto exigir dados reais.

## 11. Evidence report

Produzir `/tmp/sirhosp-slice-SMT-S2-report.md` conforme `AGENTS.md` §13,
incluindo o método da verificação de produto e o que ela efetivamente
cobriu.

## 12. Worker handoff

Quando aprovado, implementar somente SMT-S2 sobre SMT-S1 aceito. Produzir
failing-before evidence, a menor mudança correta, gates e verificação. Não
atualizar `tasks.md`, criar commit/push/merge ou arquivar o change.
Finalizar com `READY_FOR_REVIEW` e
`REPORT_PATH=/tmp/sirhosp-slice-SMT-S2-report.md`.
