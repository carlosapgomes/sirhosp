# Proposal — `clarify-patient-flow-labels`

## Problema

O rótulo visível do achado `suspected_legacy_residual` é "Suspeita de
paciente residual no legado". O termo "legado" é jargão de TI (sistema
legado) e não faz parte do vocabulário hospitalar; usuários clínicos e
operacionais não sabem o que ele significa. O rótulo aparece em todas as
superfícies que renderizam achados (`/censo`, `/beds`, página de admissões)
e, desde a RC17, também na aba patients de `/metrica-ingestao`.

## Objetivo

Renomear dois rótulos visíveis de achados para linguagem hospitalar,
removendo jargão de TI (decisões do operador, 2026-09-01):

- `suspected_legacy_residual`: "Suspeita de paciente residual no legado" →
  **"Suspeita de paciente residual"**.
- `mirror_stale_admission`: "Suspeita de admissão órfã no espelho" →
  **"Suspeita de internação antiga em aberto ou alta não detectada"**
  (o "ou" cobre as duas causas-raiz — internação antiga genuinamente em
  aberto ou alta que a sincronização não detectou — sem afirmar nenhuma).

Ajuste estritamente apresentacional: códigos internos, severidades e flags
de revisão manual permanecem idênticos; nada é persistido (achados são
computados on-the-fly), logo zero migrations e zero backfill.

## Escopo incluído

- Constantes de label em `apps/ingestion/patient_flow_findings.py`
  (`_FINDING_SPECS`: entradas de `suspected_legacy_residual` e
  `mirror_stale_admission`).
- Os pinos de texto nos testes de integração
  (`tests/integration/test_censo_patient_flow_findings.py`:
  `EXPECTED[R_RESIDUAL]` e `MIRROR_LABEL`;
  `tests/integration/test_patient_flow_findings_surfaces.py`:
  `LABEL_RESIDUAL`). O arquivo de observabilidade importa o label direto de
  `_FINDING_SPECS` e acompanha o rename sem edição.
- Delta de spec criando contrato de linguagem acessível para rótulos
  (evita regressão a jargão).

## Escopo excluído

- Qualquer mudança em códigos, regras, severidade, prioridade, queries,
  persistência, models/migrations, workers, docs de deploy.
- Arquivos de archive do OpenSpec (imutáveis por governança).

## Evidência

- Ocorrências dos textos antigos (mapeamento 2026-09-01):
  "Suspeita de paciente residual no legado" → 3 (constante + 2 pinos de
  teste); "Suspeita de admissão órfã no espelho" → 2 (constante + pino
  `MIRROR_LABEL` no teste de censo; observabilidade importa de
  `_FINDING_SPECS`). Specs usam apenas os códigos, sem pinar texto;
  deploy/runbooks sem ocorrências.
- Nota de UX registrada: o novo rótulo do `mirror_stale_admission` tem 56
  caracteres (vs. 29–40 dos demais) e pode quebrar linha/alargar colunas em
  badges de tabela; verificação visual recomendada pós-RC18, ajuste
  posterior trivial (apresentacional).

## Critérios de sucesso

- Todas as superfícies passam a exibir os dois novos rótulos.
- Nenhuma ocorrência dos textos antigos fora de archives.
- Comportamento classificador inalterado (códigos/severidades/revisão
  idênticos; suíte existente verde sem outras edições).
- Gate completo verde com passed >= baseline.
