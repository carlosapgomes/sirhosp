# Template de relatório de slice (obrigatório)

Use este template para gerar `/tmp/sirhosp-slice-DWI-SX-report.md`.

## 1) Resumo executivo do slice

- objetivo planejado;
- resultado entregue;
- status final: `completo` | `parcial` | `bloqueado`.

## 2) Checklist de aceite

- [ ] Item 1
- [ ] Item 2
- [ ] Item 3

## 3) Arquivos alterados

Liste caminhos absolutos.

## 4) Snippets before/after por arquivo

Para cada arquivo alterado, incluir:

### `<path-do-arquivo>`

#### Antes

```text
# trecho anterior
```

#### Depois

```text
# trecho atualizado
```

## 5) Testes e validações executadas

Para cada comando:

- comando;
- exit code;
- resumo do resultado.

## 6) Autoavaliação do executor

- O slice respeitou escopo e limite de arquivos?
- O slice manteve TDD (red/green/refactor)?
- Há débito técnico assumido?

## 7) Riscos, pendências e próximo passo

- riscos;
- pendências;
- próximo slice sugerido.

## 8) Conformidade

- [ ] sem dados reais/sensíveis no diff e no relatório
- [ ] markdown lint do relatório passou

### Validação local obrigatória do relatório

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-DWI-SX-report.md
```
