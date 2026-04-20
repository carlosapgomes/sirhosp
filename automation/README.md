# Automation

Este diretório concentra automações de extração e experimentos de Playwright.

## Estrutura inicial

- `source_system/medical_evolution/` — conector de evoluções médicas
- `source_system/prescriptions/` — conector de prescrições
- `source_system/current_inpatients/` — sincronização de internados atuais
- `lab/playwright_experiments/` — modo laboratório para descoberta e depuração

## Regra importante

Código exploratório do laboratório não deve ser acoplado diretamente aos jobs de produção.
