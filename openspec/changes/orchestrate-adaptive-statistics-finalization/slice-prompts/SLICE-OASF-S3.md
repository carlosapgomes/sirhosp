# SLICE-OASF-S3 — Preflight reconhece o runtime adaptativo

## Handoff de entrada (contexto zero)

Comece somente após OASF-S2 aceito. Leia:

1. `AGENTS.md`;
2. `design.md`, decisões D6 e D7 deste change;
3. o MODIFIED requirement em
   `specs/daily-statistics-production-activation/spec.md`;
4. `deploy/daily-statistics-activation-preflight.sh` completo;
5. `tests/unit/test_daily_statistics_activation_preflight.py` completo;
6. `compose.hospital.yml`, apenas para conhecer o comando e nome do serviço.

Este slice não altera Django, Compose, units ou documentação operacional.

## Objetivo

Fazer o preflight read-only validar o Compose imutável, aceitar bootstrap na
data corrente antes das 20:00, exigir os timers hourly/D-1 legados
desabilitados e obter ambas as evidências naturais exclusivamente dos logs do
`census_orchestrator`, sem imprimir conteúdo bruto e sem permitir verbos Docker
mutáveis.

## Requisitos verificáveis

- **R1:** `compose.hospital.yml` integra a lista de assets baixados e comparados
  byte a byte com a tag imutável.
- **R2:** data futura passa; data corrente passa somente antes das 20:00 Bahia;
  corrente a partir de 20:00, passada, ausente e inválida falham fechado.
- **R3:** `sirhosp-discharges.timer`,
  `sirhosp-historical-recovery.timer` e `sirhosp-daily-statistics.timer` devem
  estar `disabled/inactive`.
- **R4:** os marcadores canônicos
  `mode=hourly-discharges result=success source=adaptive-orchestrator` em 2h e
  `mode=d1-recovery result=success source=adaptive-orchestrator` em 30h
  comprovam as cadências naturais.
- **R5:** durante a transição, somente sequências RC31 ordenadas e isoladas por
  bloco — start, dispatch do modo esperado, resumo sem falha e finish — também
  comprovam sucesso; D-1 exige os quatro extratores e 4/4.
- **R6:** finish isolado, ordem quebrada, blocos combinados, 3/4, `Failed > 0`,
  ausência de deaths no D-1, log indisponível ou apenas journal dos services
  manuais falham fechado.
- **R7:** Docker é invocado somente como `compose ps`/`compose logs` read-only;
  nenhum `exec`, `run`, `up`, `start`, `restart`, `stop`, `inspect` ou comando
  Django aparece em caminho executável.
- **R8:** conteúdo clínico sintético nos logs nunca aparece em stdout/stderr; a
  saída continua integralmente allowlisted.
- **R9:** execução bem-sucedida ou falha não altera nenhum arquivo/estado da
  fixture.

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1–R9 | preflight | command doubles e assertions em `test_daily_statistics_activation_preflight.py` |
| R7 | ambos | log de chamadas do shim Docker + scan estático de verbos |
| R8–R9 | teste | conteúdo sentinela e snapshot de fixture antes/depois |

## Escopo e blast radius

```yaml
expected_files:
  - deploy/daily-statistics-activation-preflight.sh
  - tests/unit/test_daily_statistics_activation_preflight.py
allowed_incidental_files: []
max_changed_files: 2
out_of_scope:
  - apps/**
  - compose.hospital.yml
  - deploy/systemd/**
  - deploy/README.md
  - docs/releases/**
```

Se a evidência exigir banco, comando Django, volume novo, alteração de logging
Docker ou terceiro arquivo, pare e escale.

## Restrições do parser transitório

Cada parser deve limitar a sequência entre o start e o finish do mesmo modo,
exigir ordem e cobertura canônica, e rejeitar qualquer bloco com falha. Não
basta procurar substrings independentes no arquivo inteiro nem combinar hourly
e D-1. Os marcadores canônicos novos são a fonte preferida; os parsers RC31 são
ponte explícita, não evidência genérica.

O arquivo temporário de logs deve estar sob o diretório temporário já removido
por `trap`. Nenhuma linha bruta é ecoada. A saída do preflight deve indicar
somente check, status, source enumerada e janela.

## Plano TDD

### RED

Amplie primeiro os shims sintéticos de release, `date` e Docker, depois escreva
os cenários R1–R9. Execute:

```bash
uv run pytest -q tests/unit/test_daily_statistics_activation_preflight.py
```

Falhas esperadas: Compose ausente da comparação, hoje recusado, timers hourly e
D-1 esperados ativos, ausência de consulta ao container e/ou aceitação
incorreta de sequências adversariais. O shim Docker não pode acessar o daemon
real.

### GREEN / refactor

Implemente o mínimo no shell:

- asset Compose;
- relógio Bahia com data e horário;
- estados inversos dos timers hourly e D-1;
- helper Docker fechado por subcomando;
- captura silenciosa e parsers estruturais separados por modo;
- códigos de falha enumerados.

Mantenha `set -euo pipefail`, cleanup e saída allowlisted. Reexecute o mesmo
teste até verde.

### Verificação local do slice

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate orchestrate-adaptive-statistics-finalization --strict
```

## Critérios de aceitação

- [ ] R1–R9 verdes com fixtures exclusivamente sintéticas.
- [ ] Nenhum acesso ao Docker/systemd/rede reais durante testes.
- [ ] Sequências RC31 não podem combinar pedaços de execuções ou modos
      diferentes.
- [ ] Markers manuais systemd não satisfazem hourly nem D-1.
- [ ] Saída não contém marker bruto, identidade ou segredo sentinela.
- [ ] Diff limitado aos dois arquivos.
- [ ] `/tmp/sirhosp-slice-OASF-S3-report.md` completo.

## Contrato de handoff

Não altere tasks, não commita e não atualize runbooks. Um parser mais permissivo
que os requisitos é P1. O reviewer deve inspecionar falsos positivos, comandos
Docker executáveis, cleanup, allowlist de saída, isolamento hourly/D-1 e
comportamento no boundary 19:59/20:00 Bahia.
