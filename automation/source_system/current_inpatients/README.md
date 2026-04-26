# Current Inpatients Connector

Extrai pacientes internados atualmente de todos os setores do Censo
Diário do sistema fonte.

## Uso

```bash
uv run python automation/source_system/current_inpatients/extract_census.py \
    --headless \
    --output-dir downloads/
```

## Output

- CSV: `downloads/censo-todos-pacientes-slim-<timestamp>.csv`
- JSON: `downloads/censo-todos-pacientes-slim-<timestamp>.json`

CSV columns: `setor`, `qrt_leito`, `prontuario`, `nome`, `esp`

## Variáveis de ambiente

- `SOURCE_SYSTEM_URL` — URL do sistema fonte
- `SOURCE_SYSTEM_USERNAME` — Usuário de acesso
- `SOURCE_SYSTEM_PASSWORD` — Senha de acesso
