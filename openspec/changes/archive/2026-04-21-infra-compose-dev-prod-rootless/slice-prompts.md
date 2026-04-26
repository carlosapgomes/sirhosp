# Índice de prompts por slice

Este arquivo é apenas um índice.

Cada slice possui **arquivo próprio** com handoff completo para executor iniciando de contexto zero.

## Arquivos

- `slice-prompts/SLICE-S1.md`
- `slice-prompts/SLICE-S2.md`
- `slice-prompts/SLICE-S2-1.md`
- `slice-prompts/SLICE-S3.md`
- `slice-prompts/SLICE-S4.md`
- `slice-prompts/SLICE-S5.md`

## Convenções obrigatórias para todos os slices

- Implementar **um slice por vez**.
- Respeitar limite de arquivos alterados.
- Se precisar ampliar escopo, **parar e reportar bloqueio**.
- Usar **RED/GREEN operacional** (smoke checks) em vez de suíte unitária nova quando o slice for puramente infra.
- **Gate de saída obrigatório:** não aceitar "concluído" com apenas `build`; é obrigatório provar **runtime** com serviços de pé.
- Sempre incluir no relatório: comando executado + exit code + trecho de saída (stdout/stderr).
- Se qualquer comando de gate falhar, o slice fica **não concluído**.
- Gerar relatório em `/tmp/sirhosp-slice-<ID>-report.md`.
