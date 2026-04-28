# SLICE-S6: Quality gate e validação final

## Handoff / Contexto de Entrada

**Change**: `discharge-daily-tracking` — COMPLETO em termos de código.

**Slice S5 concluído**:

- View `discharge_chart()` implementada com médias móveis
- Template Chart.js renderizado com bar + 3 linhas
- Seletor de período funcional
- 8 testes da view passando

**Todos os slices de implementação (S1-S5) estão prontos.**

**O que você vai fazer neste slice**:
Apenas validação. Nenhum código novo. Rodar todos os gates de qualidade
definidos no `AGENTS.md` e verificar se tudo passa. Se algo falhar, corrigir
**apenas** o mínimo necessário e documentar.

## Arquivos que você PODE tocar (limite: 0 novos, apenas correções)

| Situação | Ação permitida |
| --- | --- |
| Teste falha | Corrigir **apenas** o teste ou o código mínimo para passar |
| Lint falha | Corrigir formatação |
| Typecheck falha | Adicionar type annotation faltante |
| Markdown falha | Corrigir formatação `.md` |

**NÃO crie** novos arquivos de código. **NÃO adicione** funcionalidade nova.

## Procedimento de Validação (Executar em ordem)

### Gate 1: Django check

```bash
./scripts/test-in-container.sh check
```

**Esperado**: `System check identified no issues (0 silenced).`

### Gate 2: Testes unitários

```bash
./scripts/test-in-container.sh unit
```

**Esperado**: Todos os testes passando, com atenção especial a:

- `tests/unit/test_daily_discharge_model.py` — modelo
- `tests/unit/test_daily_discharge_count.py` — comando + hook
- `tests/unit/test_services_portal_dashboard.py` — dashboard + gráfico
- `tests/unit/test_discharge_service.py` — sem regressão

### Gate 3: Lint

```bash
./scripts/test-in-container.sh lint
```

**Esperado**: Zero erros de lint nos arquivos Python do projeto.
Se houver erros **pré-existentes** (não relacionados a este change),
documente mas não corrija.

### Gate 4: Typecheck

```bash
./scripts/test-in-container.sh typecheck
```

**Esperado**: Zero **novos** erros de type checking.
Se houver erros pré-existentes, documente.

### Gate 5: Markdown lint

```bash
./scripts/markdown-lint.sh
```

**Esperado**: Zero erros nos `.md` deste change:

- `openspec/changes/discharge-daily-tracking/proposal.md`
- `openspec/changes/discharge-daily-tracking/design.md`
- `openspec/changes/discharge-daily-tracking/tasks.md`
- `openspec/changes/discharge-daily-tracking/specs/**/*.md`
- `openspec/changes/discharge-daily-tracking/slice-prompts/*.md`

### Gate 6 (opcional): Testes de integração

```bash
./scripts/test-in-container.sh integration
```

**Esperado**: Sem regressões. Se falhar por timeout ou rede, documente
como "não relacionado a este change".

### Gate 7: Quality gate completo

```bash
./scripts/test-in-container.sh quality-gate
```

**Esperado**: TUDO verde.

## Checklist de Verificação Manual (não automatizável)

- [ ] `uv run python manage.py refresh_daily_discharge_counts` executa sem erro
- [ ] `uv run python manage.py extract_discharges --help` mostra o comando
  (verificação de que o hook não quebrou o parser de argumentos)
- [ ] Nenhum `print()` de debug deixado no código
- [ ] Nenhum comentário `# TODO` ou `# FIXME` sem dono
- [ ] Nenhum import não utilizado

## Critérios de Sucesso (Auto-Avaliação Obrigatória)

- [ ] `./scripts/test-in-container.sh check` — verde
- [ ] `./scripts/test-in-container.sh unit` — verde
- [ ] `./scripts/test-in-container.sh lint` — verde (zero novos erros)
- [ ] `./scripts/test-in-container.sh typecheck` — sem novos erros
- [ ] `./scripts/markdown-lint.sh` — verde nos arquivos do change
- [ ] `./scripts/test-in-container.sh quality-gate` — verde
- [ ] Management commands manuais executam sem erro

## Anti-Alucinação / Stop Rules

1. **NÃO implemente** nada novo. Este slice é só validação.
2. Se um gate falhar por motivo **pré-existente** (ex: lint em arquivo
   que você não tocou) → documente, não corrija.
3. Se um gate falhar por motivo **deste change** → corrija o mínimo
   necessário, documente a correção no relatório.
4. **Limite**: zero novos arquivos de código. Apenas correções pontuais.
5. Se não souber resolver uma falha em 20 minutos → documente o bloqueio
   e entregue o relatório.

## Relatório Obrigatório

Gere `/tmp/sirhosp-slice-S6-report.md`:

```markdown
# Slice S6 Report: Quality Gate Final

## Resumo
Validação final do change discharge-daily-tracking.

## Resultados dos Gates

### check
(Output do comando)

### unit
(Output resumido — total de testes, falhas se houver)

### lint
(Output — zero ou lista de erros)

### typecheck
(Output — zero novos erros ou lista)

### markdown-lint
(Output)

### quality-gate
(Output final)

## Correções Feitas (se houver)
(Listar correções pontuais com mini-snippets antes/depois)

## Verificações Manuais
- [ ] refresh_daily_discharge_counts executa
- [ ] extract_discharges --help OK
- [ ] Sem prints de debug
- [ ] Sem imports não usados

## Arquivos Alterados Neste Slice
(Nenhum ou lista dos que foram corrigidos)

## Status Final
- [ ] TUDO VERDE — change pronto para revisão
- [ ] BLOQUEIOS — (descrever se houver)

## Resumo do Change (todos os slices)
- S1: TIME_ZONE + DailyDischargeCount model
- S2: refresh_daily_discharge_counts command
- S3: Hook no extract_discharges
- S4: Dashboard query + template + URL
- S5: Gráfico view + Chart.js template
- S6: Quality gate (este slice)

Total de arquivos criados/modificados: ~XX (contar)
```

**Após gerar o relatório, PARE. O change está concluído.**
