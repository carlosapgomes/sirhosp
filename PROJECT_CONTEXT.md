# PROJECT_CONTEXT.md

## Propósito

Resumo executivo para retomada rápida do desenvolvimento do SIRHOSP e onboarding técnico da equipe.

## Fontes autoritativas

- `AGENTS.md`
- `README.md`
- `docs/architecture.md`
- `docs/adr/`
- `openspec/specs/`
- `openspec/changes/`
- Em caso de conflito, prevalece o artefato versionado mais recente e mais específico.

## Objetivo do sistema

### SIRHOSP - Sistema Interno de Relatórios Hospitalares - Extração Inteligente de Dados Clínicos

Sistema interno para extração automatizada de dados clínicos do sistema fonte
hospitalar, armazenamento em banco paralelo PostgreSQL e oferta de consulta
rápida, busca textual e resumos direcionados para gestão, qualidade, jurídico,
diretoria e gestão de prontuários.

## Escopo inicial

- foco em pacientes internados
- objetos prioritários: evoluções médicas, prescrições e pacientes internados atualmente
- primeiro serviço de alto valor: resumo de internação
- autenticação local simples com perfis `admin` e `user`
- execução programada de automações em horários específicos

## Arquitetura de alto nível

- **Portal web Django**: autenticação, dashboard, busca, serviços e administração.
- **Domínio clínico**: pacientes, internações, documentos clínicos, jobs e resumos.
- **Conectores de ingestão**: automações Playwright e parsers para extração do sistema fonte.
- **Coordenação operacional**: PostgreSQL + management commands + systemd timers/cron.
- **Processamento textual/LLM**: camada separada da captura, com resumos incrementais.

## Regras não negociáveis

- não versionar dados reais de pacientes, credenciais, PDFs reais ou artefatos
  sensíveis
- usar `uv` como padrão para setup e execução Python
- não introduzir Celery/Redis na fase 1 sem ADR explícita
- separar modo laboratório de scraping do modo produção
- usar PostgreSQL como base de persistência e coordenação operacional
- implementar por slices verticais, com escopo enxuto e baixo risco de drift
- manter um arquivo de prompt por slice com handoff de entrada para executor
  LLM em contexto zero
- aplicar TDD em cada slice (`red -> green -> refactor`)
- exigir relatório de execução por slice em
  `/tmp/sirhosp-slice-<ID>-report.md`, com evidência antes/depois
- registrar decisões estruturais em ADRs e mudanças relevantes em OpenSpec

## Quality bar

- quality gate oficial deve executar em container:
  `./scripts/test-in-container.sh quality-gate`
- sanity local adicional: `uv run python manage.py check` deve passar
- cada slice deve provar ciclo TDD (teste inicial falhando e depois passando)
- lint e type-check sem erros relevantes
- todo `.md` novo/alterado deve passar no markdown lint (`markdownlint-cli2`)
- alterações estruturais devem atualizar docs e artefatos OpenSpec
- cada slice deve entregar relatório técnico completo em `/tmp` com diffs de
  código antes/depois
