# Índice de prompts por slice

Este arquivo é apenas um índice.

Cada slice possui **arquivo próprio** com handoff completo para executor
iniciando de contexto zero.

## Arquivos

- `slice-prompts/SLICE-S1.md`
- `slice-prompts/SLICE-S2.md`
- `slice-prompts/SLICE-S3.md`
- `slice-prompts/SLICE-S4.md`
- `slice-prompts/SLICE-S5.md`

## Convenções obrigatórias para todos os slices

- Implementar **um slice por vez**.
- Respeitar limite de arquivos alterados.
- Se precisar ampliar escopo, **parar e reportar bloqueio**.
- Usar TDD para código e RED/GREEN operacional para infraestrutura.
- Não ler, imprimir ou versionar credenciais do `.env`.
- Não persistir resposta real do sistema legado no repositório.
- Não adicionar `/dev/net/tun`, `NET_ADMIN`, `NET_RAW`, `privileged`, host
  networking ou `network_mode: service:tailscale-app`.
- Sempre incluir no relatório: comando executado, exit code e trecho de saída.
- Se qualquer comando de gate falhar, o slice fica **não concluído**.
- Gerar relatório em `/tmp/sirhosp-slice-<ID>-report.md`.
