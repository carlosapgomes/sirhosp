# Design — `clarify-patient-flow-labels`

## Contexto

Mapeamento completo do texto "Suspeita de paciente residual no legado"
(2026-09-01): exatamente 3 ocorrências vivas — a constante em
`_FINDING_SPECS` (`apps/ingestion/patient_flow_findings.py:96`) e os pinos
de teste em `tests/integration/test_censo_patient_flow_findings.py:72` e
`tests/integration/test_patient_flow_findings_surfaces.py:47`
(`LABEL_RESIDUAL`). Specs referenciam apenas o código
(`suspected_legacy_residual`); nenhum doc de deploy/runbook contém o texto;
archives são imutáveis.

## Decisões

- **D1 — Novo rótulo fechado: "Suspeita de paciente residual"** (decisão do
  operador, 2026-09-01). Curto, sem jargão de TI, preserva o conceito
  operacional já absorvido pela equipe ("paciente residual").
- **D2 — Código interno intocado.** `suspected_legacy_residual` permanece o
  identificador em código, specs, health e testes estruturais. Renomear
  código seria risco sem benefício (o jargão problemático é só o que o
  usuário lê).
- **D3 — Apresentacional puro.** Achados não são persistidos (computados
  on-the-fly a cada avaliação) ⇒ sem migration, sem backfill, sem
  coordenação de deploy; o novo rótulo vale para todas as superfícies no
  mesmo render (`/censo`, `/beds`, admissões, aba patients) porque todas
  consomem o mesmo DTO fechado.
- **D4 — Contrato de spec para linguagem acessível.** Delta ADDED em
  `patient-flow-findings` pinando o texto do rótulo residual e proibindo
  termos de sistema ("legado") em rótulos visíveis — transforma a decisão de
  linguagem em contrato verificável, evitando regressão futura.
- **D5 — Rótulo do `mirror_stale_admission` também renomeado** (decisão do
  operador, 2026-09-01): "Suspeita de admissão órfã no espelho" →
  "Suspeita de internação antiga em aberto ou alta não detectada". O "ou"
  cobre as duas causas-raiz sem afirmar nenhuma (internação antiga em
  aberto OU alta que a sincronização não detectou), respeitando a
  constraint "a suspeita nunca afirma uma alta". Nota de UX: 56 caracteres
  pode quebrar linha em badges de tabela — verificação visual pós-RC18,
  ajuste trivial se necessário.

## Alternativas rejeitadas

- Renomear também o código interno: risco (health, workers, specs
  referenciam) sem ganho de UX.
- Rótulos descritivos longos ("Paciente possivelmente com internação antiga
  sem atividade"): barulho visual nos badges; a revisão manual já tem o
  tooltip/contexto.

## Riscos

- Testes que pinam texto são os únicos impactados (2 arquivos; a
  observabilidade importa de `_FINDING_SPECS` e auto-segue) — contidos.
- Badge de 56 caracteres quebra linha em células estreitas — aceito; checar
  visualmente pós-RC18; encurtar depois (se decidido) é micro-change
  idêntica a esta.

## Dimensionamento de slices

Um único slice vertical (CFL-S1): renomear constante + atualizar 2 pinos de
teste, com RED clássico (testes esperando o rótulo novo falham contra a
constante antiga). Seção 2.x = verificação final.
