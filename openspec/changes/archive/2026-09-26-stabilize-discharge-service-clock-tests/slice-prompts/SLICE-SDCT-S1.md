# SLICE-SDCT-S1 — Estabilizar testes de altas dependentes do relógio

## Handoff de entrada

Você inicia com contexto zero. Leia `AGENTS.md`, `proposal.md`, `design.md`,
`tasks.md`, `tests/unit/test_discharge_service.py`,
`apps/discharges/services.py` somente para entender o contrato, e as seções 5 e
7.2 de `/tmp/sirhosp-slice-PDSPA-S4-report.md`. Capture o `BASE_REF` antes de
editar. Implemente somente este slice e pare após o relatório e os gates.

## Objetivo

Eliminar a dependência do relógio de parede nos dois cenários unitários que
representam admissões já encerradas no mesmo dia operacional, recuperando um
quality gate determinístico sem alterar código de produção.

## Requisitos verificáveis

- **R1:** `test_already_discharged_is_skipped` e
  `test_multiple_patients_mixed_results` derivam o encerramento e a referência
  passada ao serviço de um mesmo datetime sintético, timezone-aware e explícito.
- **R2:** a referência escolhida mantém `reference - 2 h` e
  `reference - 3 h` no mesmo dia em `America/Bahia`, preservando a semântica das
  asserções atuais.
- **R3:** nenhum cenário, contagem ou asserção existente é removido ou
  relaxado; os 11 testes do arquivo passam em container.
- **R4:** nenhum arquivo de produção, configuração, dependência, modelo,
  migration ou runtime é alterado.
- **R5:** o quality gate oficial passa independentemente da hora em que o slice
  for executado.

## Escopo e blast radius

```yaml
expected_files:
  - tests/unit/test_discharge_service.py
allowed_incidental_files:
  - openspec/changes/stabilize-discharge-service-clock-tests/tasks.md
out_of_scope:
  - apps/discharges/services.py
  - mudança de regra clínica ou dia operacional
  - mock global permanente de timezone
  - nova dependência de congelamento de relógio
  - banco, migrations, deploy ou produção
```

Se qualquer correção exigir arquivo fora do teste esperado, pare e reporte o
bloqueio em vez de ampliar o slice.

## Plano de testes

### RED

Use a evidência já coletada em `/tmp/sirhosp-slice-PDSPA-S4-report.md`: dentro
da janela 00:00–03:00 `America/Bahia`, o arquivo produziu exatamente 2 falhas e
9 passes. Antes da implementação, faça uma reprodução determinística focada
com relógio sintético equivalente a 00:30 em `America/Bahia` ou, se a injeção
local não for segura, registre a evidência existente como RED sem alterar o
produto. A falha esperada deve ser exclusivamente o cruzamento de data nas duas
asserções identificadas.

### GREEN

Faça a alteração mínima em `tests/unit/test_discharge_service.py`: use um
`reference_datetime` sintético e timezone-aware em horário seguro e passe-o
explicitamente em `process_discharges(..., discharge_date=reference_datetime)`;
os encerramentos existentes devem derivar da mesma referência. Execute em
container:

```bash
./scripts/test-in-container.sh unit
```

Registre separadamente que o arquivo focado contém 11 testes passando. Não use
um teste host-only como evidência oficial.

### Verificação final

```bash
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
openspec validate stabilize-discharge-service-clock-tests --strict
git diff --check
```

Inspecione `git diff --name-only BASE_REF` e confirme que nenhum arquivo de
produção foi tocado.

## Critérios de aceitação

- [ ] R1–R5 comprovados.
- [ ] RED e GREEN registrados sem dados reais.
- [ ] Quality gate oficial com `exit=0` em qualquer horário.
- [ ] Relatório `/tmp/sirhosp-slice-SDCT-S1-report.md` contém resumo, checklist,
  arquivos, antes/depois, comandos/resultados, riscos e próximo passo.
- [ ] Nenhum push, tag, release, archive ou ação de produção executado.
