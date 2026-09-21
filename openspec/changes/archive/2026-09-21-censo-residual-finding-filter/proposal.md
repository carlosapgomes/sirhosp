# Proposal — `censo-residual-finding-filter`

## Problema

A página `/censo/` exibe o badge "Suspeita de paciente residual"
(`suspected_legacy_residual`) em pacientes que provavelmente já saíram do
hospital e permanecem registrados como internados. Hoje não há como isolar
esses pacientes: o usuário precisa varrer manualmente a lista (ordenável por
tempo de internação, setor e especialidade) para localizar cada badge e abrir
o prontuário para conferência. Em hospitais com censo cheio, o resíduo
cognitivo é alto e a lista de revisão manual — ação operacional que o
próprio badge exige (`requires_manual_review=True`) — fica dispersa.

O mesmo problema afeta o export XLSX: o botão “Exportar Excel” preserva a
querystring, mas os filtros atuais são resolvidos em SQL antes do
classificador (busca, setor e especialidade; a ordenação é aplicada em
Python sobre a lista pronta) e não existe parâmetro para o achado.

## Objetivo

Adicionar à página `/censo/` um filtro "Situação" com a opção "Suspeita de
paciente residual", que restringe a lista (desktop e mobile) aos pacientes
cujo achado corrente é exatamente `suspected_legacy_residual`, combinando
com os filtros e a ordenação existentes. O export XLSX passa a respeitar o
mesmo filtro (WYSIWYG): com o filtro ativo, a planilha contém o mesmo
conjunto de pacientes da página, sem adicionar coluna/label de achado.

## Valor operacional

- Corpo clínico e gestão de prontuário localizam em um clique a fila de
  revisão manual de pacientes residuais, reduzindo altas não registradas e
  tempo de internação fictício nos indicadores.
- Planilha exportada com o filtro ativo espelha a tela, servindo de anexo
  para conferência/auditoria sem retrabalho manual.

## Escopo incluído

- `apps/services_portal/views.py` — `_build_censo_context`: novo query
  param `finding` (valor `residual`), filtro em Python pós-classificador e
  pré-ordenação, contexto expõe `finding_filter`; `censo_export_xlsx`
  computa achados apenas quando o filtro exige (decisão D3 do design).
- `apps/services_portal/templates/services_portal/censo.html` — novo
  `select` "Situação" no form de filtros, mantendo estado selecionado.
- `tests/integration/test_censo_patient_flow_findings.py` — apenas
  adições: classe `TestCensoFindingFilter` cobrindo filtro, combinações,
  export WYSIWYG e orçamento de queries.
- Delta de spec `censo-current-list-export` (requisito novo + dois
  modificados).

## Escopo excluído

- Qualquer mudança no classificador
  (`apps/ingestion/patient_flow_findings.py`): regras, códigos, labels,
  severidades, prioridade e orçamento de queries permanecem intocados.
- Persistência de achados (models/migrations) — vedada pela spec
  `patient-flow-findings` ("nothing is persisted or migrated").
- Filtro genérico por `requires_manual_review` (pegaria também
  `mirror_stale_admission`): variante reconhecida como follow-up trivial,
  deliberadamente fora deste change (decisão do operador, 2026-09-17).
- Filtro em outras superfícies (`/beds`, página de admissões, aba patients
  de `/metrica-ingestao`).
- Coluna/label de achado no XLSX.

## Riscos

- **Baixo.** Sem schema, sem migration, sem dependência nova; o filtro opera
  sobre dados já em memória (o classificador já roda em todo request HTML
  com orçamento fixo de 5 queries bulk).
- Risco residual 1: export com filtro ativo passa a rodar o classificador
  (custo bornado: 5 queries fixas) — mitigado por teste de orçamento.
- Risco residual 2: opção de filtro sem estado preservado confundiria o
  usuário — coberto por requisito de UI com teste.

## Critérios de sucesso

- `?finding=residual` lista somente pacientes com achado corrente
  `suspected_legacy_residual` (desktop e mobile), total coerente.
- Filtro combina com `q`, `unidade`, `especialidade` e `ordenar`.
- Sem o param (ou valor desconhecido), comportamento idêntico ao atual.
- Export com `?finding=residual` produz exatamente as linhas da página
  filtrada; sem o param, export inalterado (sem rodar classificador).
- Query count da página inalterado com/sem filtro; suíte existente verde.
