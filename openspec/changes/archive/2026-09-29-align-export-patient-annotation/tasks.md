# Tasks — `align-export-patient-annotation`

## 1. Preflight do change

- [x] 1.1 Registrar `BASE_REF`, confirmar working tree sem mudanças relacionadas e executar `openspec validate align-export-patient-annotation --strict` (tolerar ausência de delta de spec, documentada no proposal); preservar a saída no relatório do slice.
- [x] 1.2 Confirmar que não há escritor concorrente em `apps/statistics_reports/export.py` (changes ativos sem implementação pendente nesse arquivo).

## 2. SLICE-AEPA-S1 — Anotação do exportador alinhada a `PatientRow`

- [x] 2.1 Implementar o `Protocol PatientExportRow` (membros read-only `bed`, `name`, `record`, `specialty`, sem `runtime_checkable`) em `apps/statistics_reports/export.py` e trocar a anotação do parâmetro de `_patient_values` para o protocolo, removendo o import órfão de `DailyStatisticsPatient`; sem qualquer outra mudança no arquivo.
- [x] 2.2 Executar `./scripts/test-in-container.sh typecheck`, `lint`, `check`, a suíte focada de integração (página + exportação, sem edição de testes) e `makemigrations --check --dry-run`; gerar `/tmp/sirhosp-slice-AEPA-S1-report.md` com o diff antes/depois e os resultados.
- [x] 2.3 Obter revisão independente do slice e corrigir apenas achados P0/P1 antes de marcar o slice concluído.

## 3. Gate final do change

- [x] 3.1 Executar `./scripts/test-in-container.sh quality-gate`, `./scripts/test-in-container.sh integration` (o quality-gate do container não inclui a suíte de integração) e `./scripts/markdown-lint.sh`, além de `openspec validate align-export-patient-annotation --strict`; registrar contagens e resultados no relatório final.
- [x] 3.2 Verificar diff completo: exatamente um arquivo de código, sem migrations, sem PHI/credenciais, sem mudança de runtime; arquivar com `--skip-specs` (sem delta de spec por design).
