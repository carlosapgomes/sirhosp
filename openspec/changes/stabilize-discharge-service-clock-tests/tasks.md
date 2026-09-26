## 1. Slice SDCT-S1 — estabilizar cenários e recuperar o gate

- [ ] 1.1 RED: confirmar no relatório PDSPA-S4 a reprodução de `test_already_discharged_is_skipped` e `test_multiple_patients_mixed_results` na janela 00:00–03:00 `America/Bahia`, preservando a evidência de 2 falhas pelo cruzamento da data operacional
- [ ] 1.2 GREEN: fazer os dois cenários derivarem admissão e chamada do serviço da mesma referência temporal sintética explícita, sem alterar código de produção, e verificar `tests/unit/test_discharge_service.py` em container
- [ ] 1.3 Gerar `/tmp/sirhosp-slice-SDCT-S1-report.md`, executar `./scripts/test-in-container.sh quality-gate`, Markdown lint, OpenSpec strict e `git diff --check`, e confirmar que o resultado independe do horário corrente
