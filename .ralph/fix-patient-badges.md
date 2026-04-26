# fix-patient-badges — COMPLETE ✅

## Progress

- [x] `apps/patients/services.py`: `distinct=True` adicionado nos 3 `Count()`
- [x] `tests/unit/test_patient_list_view.py`: teste fortalecido com regex para validar cada badge
- [x] `check`: 0 issues
- [x] `unit`: 455 passed
- [x] `lint`: All checks passed

## Summary

Causa raiz: `Q(admissions__events__isnull=False)` forçava LEFT JOIN com
`clinical_docs_clinicalevent`, multiplicando linhas. `COUNT()` sem `DISTINCT`
contava as duplicatas → badges mostravam contagem de eventos, não de admissões.

Correção: `distinct=True` → `COUNT(DISTINCT "patients_admission"."id")` → badges
corretos.

Relatório: `/tmp/sirhosp-slice-fix-patient-badges-report.md`
