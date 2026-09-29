## 1. Preflight do change

- [x] 1.1 Registrar `BASE_REF`, confirmar working tree sem mudanças relacionadas e executar `openspec validate link-statistics-patients-to-admissions --strict`; preservar a saída no relatório do slice.
- [x] 1.2 Confirmar que não há escritor concorrente em `apps/statistics_reports/presentation.py`, `daily_report.html` e `export.py` (changes ativos sem implementação pendente nesses arquivos).

## 2. SLICE-LSPA-S1 — Linhas nominais clicáveis

- [x] 2.1 Adicionar testes RED da resolução prontuário → paciente na projeção (exatamente um candidato resolve; nenhum candidato não resolve; mais de um candidato entre sistemas de origem distintos não resolve e não escolhe arbitrariamente; prontuário vazio) e do render da página (link para internações quando resolvido, fallback de busca quando não resolvido ou ambíguo, texto simples sem prontuário, listas do setor não identificado cobertas); atualizar as asserções existentes afetadas (ordenação natural independente de tag; orçamento de queries da projeção de 3 para 4, mantida a invariância por volume); adicionar regressão XLSX (colunas, seções e valores inalterados; nenhuma coluna ou valor derivado da resolução); verificar a falha focada antes da implementação.
- [x] 2.2 Implementar a resolução em tempo de leitura em `presentation.py` (uma query `patient_source_key__in`; política de candidato único; `PatientRow` frozen attribute-compatível com o exportador; `EventRow.patient_id`) e os links no template conforme o padrão de `/beds/`; verificar GREEN nos testes focados.
- [x] 2.3 Executar `./scripts/test-in-container.sh check`, `./scripts/test-in-container.sh integration`, lint/typecheck oficiais em container e `openspec validate link-statistics-patients-to-admissions --strict`; gerar `/tmp/sirhosp-slice-LSPA-S1-report.md` com RED/GREEN e snippets antes/depois.
- [x] 2.4 Obter revisão independente do slice e corrigir apenas achados P0/P1 antes de marcar o slice concluído.

## 3. Gate final do change

- [x] 3.1 Executar `./scripts/test-in-container.sh quality-gate`, `./scripts/test-in-container.sh integration` (o quality-gate do container não inclui a suíte de integração) e `./scripts/markdown-lint.sh`, além de `openspec validate link-statistics-patients-to-admissions --strict`; registrar contagens e resultados no relatório final.
- [x] 3.2 Verificar diff completo: sem migrations, sem PHI/credenciais, sem mudança em materialização/XLSX/permissões além do contrato de regressão; atualizar a spec canônica no arquivamento.
