# fix-fullsync-failure-exhaustion

Correção do esgotamento de tentativas da coorte fail-only de full-sync,
com causa comprovada pela ADR-0008 (evidência: agregados de produção
read-only de 2026-08-28 e one-shot v0.1.0-rc.14 de 2026-08-29 + reprodução
sintética em laboratório contra código real).

Estado: **pronto para implementação** — 4 slices verticais com prompts
executáveis por DeepSeek4-Flash com contexto zero
(`slice-prompts/SLICE-FX-S1..S4.md`), na ordem:

1. FX-S1 — fail-fast de payload determinístico (política de retry por
   reason nos dois workers);
2. FX-S2 — orçamento de tempo por volume nas janelas de evolução (função
   pura com teto + call site do worker persistente);
3. FX-S3 — caracterização das validações de payload com prova de
   sensibilidade;
4. FX-S4 — regressão do laboratório CFC, nota operacional (§6.3) e
   verificação final.

Verificação por terceiro LLM entre slices; arquivamento somente após
FX-S4 verificado e autorização explícita do operador.

Rastreabilidade: ADR-0008 (decisão), change arquivado
`characterize-fullsync-chronic-failures` (evidência e ferramental),
evidence pack `docs/releases/2026-08-29_v0.1.0-rc.14.md`.
