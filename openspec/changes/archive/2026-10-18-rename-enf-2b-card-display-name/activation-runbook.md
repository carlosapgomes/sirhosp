# Runbook de publicação — catálogo v6 (rename Enfermaria 2B Cardio)

Runbook operacional do change `rename-enf-2b-card-display-name`. A publicação
é AÇÃO DO OPERADOR, pós-deploy do release que contém o arquivo
`apps/census/data/sector_capacity_catalog_v6.json` (tasks.md §5). Nenhuma
etapa deste runbook é executada por build, migração ou startup.

## Pré-condições

1. Release contendo este change deployado e saudável no ambiente alvo
   (app + workers no ar, `/beds` respondendo, migrations em dia — este
   change não introduz migration).
2. Backup do banco recente e verificado.
3. SHA-256 do arquivo `apps/census/data/sector_capacity_catalog_v6.json`
   conferido contra o valor registrado no relatório do slice RCD-S1.
4. Data efetiva aprovada pelo operador: data **estritamente futura** ao hoje
   local `America/Bahia` (abaixo, `YYYY-MM-DD`).

## Procedimento (dentro do container app do ambiente alvo)

### 1. Dry-run obrigatório (nada persiste)

```bash
uv run --no-sync python manage.py activate_sector_capacity_catalog \
  --input apps/census/data/sector_capacity_catalog_v6.json \
  --effective-from YYYY-MM-DD --dry-run
```

Resultado esperado: mensagem "validado (dry-run)"; `occupancy-v5`; 43
grupos, 48 memberships, 47 códigos, 39 standard, 4 unrated, capacidades
666/666. A cobertura de aliases (48/48) não é impressa pelo comando — fica
comprovada pelos testes de contrato do catálogo v6. Qualquer divergência ⇒
PARAR e reportar.

### 2. Publicação (uma única vez)

```bash
uv run --no-sync python manage.py activate_sector_capacity_catalog \
  --input apps/census/data/sector_capacity_catalog_v6.json \
  --effective-from YYYY-MM-DD
```

Resultado esperado: "publicado" (criação atômica da versão completa v6).

### 3. Prova de idempotência

Repetir exatamente o comando do passo 2. Resultado esperado:
"já publicado (idempotente)" — nenhum dado novo é criado.

## Pós-condições e verificação

- À meia-noite local (`America/Bahia`) da data efetiva, todo censo aceito do
  dia usa v6; o dia anterior permanece integralmente v5 — nenhum dia local
  mistura versões.
- Após a primeira medição/materialização do dia vigente, `/beds` e as demais
  superfícies exibem a unidade como `Enfermaria 2B Cardio`, posicionada junto
  das demais enfermarias do 2º andar na ordenação alfabética.
- Medições/materializações de dias anteriores preservam o rótulo
  `Cardioclinica / Enfermaria 2B Cardio` (imutabilidade, ADR-0003) — sem
  backfill.

## Proibições e rollback

- Nunca editar o JSON v6 após publicado; não existe "unpublish" de versão
  (catálogo imutável). Se o dry-run falhar ou o hash divergir, NÃO publicar:
  reportar e corrigir via nova versão (v7) com teste de delta próprio.
- A publicação errada de data só é evitável pelo dry-run + conferência de
  hash: executar sempre nesta ordem.
- Mudanças futuras de rótulo/capacidade = novo catálogo versionado + testes
  de contrato + novo runbook, nunca edição do v6.
