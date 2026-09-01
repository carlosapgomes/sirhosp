# Tasks — Disambiguate mirror-stale admissions from legacy residuals

## 1. MSA-S1 — Split da regra 5 do classificador com recência de movimento

- [x] 1.1 Ler integralmente `slice-prompts/SLICE-MSA-S1.md`, registrar
      BASE_REF, árvore limpa e baselines oficiais unit/integration com exit
      code e resumo.
- [x] 1.2 RED: testes novos do split (`mirror_stale_admission` com movimento
      ≤ 48 h; `suspected_legacy_residual` preservado sem movimento; movimento
      futuro tratado como ausente; regras 1–4 intactas; orçamento fixo de 5
      queries; auto-aparição em `/censo` sem tocar superfícies).
- [x] 1.3 GREEN mínimo em no máximo dois arquivos (serviço + testes).
- [x] 1.4 REFACTOR local (clean/DRY/YAGNI), sem engine/framework novo.
- [x] 1.5 Inspeções obrigatórias, gates oficiais completos, OpenSpec strict e
      markdown lint; relatório em `/tmp/sirhosp-slice-MSA-S1-report.md` com
      handoff para verificador; marcar somente 1.x após tudo verde.

## 2. MSA-S2 — Situação corrente na aba patients de `/metrica-ingestao`

- [x] 2.1 Ler integralmente `slice-prompts/SLICE-MSA-S2.md`, registrar
      BASE_REF (= commit do S1 aprovado), árvore limpa e baselines.
- [x] 2.2 RED: coluna "Situação" com rótulo corrente para paciente com
      achado; célula vazia sem placeholder quando sem achado; paciente fora
      do censo atual sem rótulo; auth preservada; sem N+1; sem PHI novo.
- [x] 2.3 GREEN mínimo em no máximo três arquivos (view + template +
      testes).
- [x] 2.4 REFACTOR local reutilizando o serviço do classificador (sem
      duplicar regra).
- [x] 2.5 Inspeções, gates, OpenSpec strict, markdown lint; relatório em
      `/tmp/sirhosp-slice-MSA-S2-report.md`; marcar somente 2.x após tudo
      verde.

## 3. Verificação final do change

- [x] 3.1 Relatórios COMPLETE aprovados de MSA-S1 e MSA-S2 por verificador
      independente, com RED reproduzido e gates re-executados.
- [x] 3.2 `./scripts/test-in-container.sh quality-gate` e
      `./scripts/test-in-container.sh integration` com exit code zero.
- [x] 3.3 `openspec validate disambiguate-mirror-stale-admission --strict` e
      `./scripts/markdown-lint.sh` sem erros.
- [x] 3.4 Revisar diff acumulado: sem PHI, sem model/migration/status/
      dependência não autorizados; regras 1–4 e eixos técnicos intactos.
