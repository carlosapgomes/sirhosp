# Quality Gate Executor (Python)

Script Python autônomo para executar pipeline de qualidade do projeto. Executa comandos de validação definidos no `AGENTS.md` ou usa padrões baseados na stack detectada.

## 🚀 Características

- **Autodetecta stack**: Python, JavaScript, ou outras
- **Lê AGENTS.md**: Usa comandos personalizados se disponíveis
- **Formatos de output**: Texto, JSON, Markdown
- **Timeout configurável**: Evita comandos travados
- **Relatório estruturado**: Resultados detalhados com métricas
- **Código de saída**: Útil para CI/CD (0 = sucesso, 1 = falha)

## Conceitos de comandos no AGENTS.md

- **Comandos de Validação**: gates de qualidade para aprovar mudança.
- **Comandos essenciais**: comandos operacionais do dia a dia do projeto.
- Formato canônico:
  - `## 2. Comandos de Validacao (Quality Gate)`
  - `## 3. Comandos Essenciais (Operacao Local)`
- Formatos legados continuam aceitos pelo parser.
- Em seções com blocos ```bash, cada linha executável vira um item do gate.

## 📦 Instalação

### Método 1: Script autônomo (recomendado)

```bash
# Copiar o script para seu projeto
cp quality_gate.py /caminho/do/seu/projeto/

# Tornar executável (opcional)
chmod +x quality_gate.py
```

### Método 2: Como módulo Python

```bash
# Instalar em virtualenv (opcional)
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# ou venv\Scripts\activate  # Windows

# Instalar dependências opcionais
pip install -r requirements.txt
```

## 🎯 Uso Básico

### Executar quality gate

```bash
# Na raiz do seu projeto
python3 quality_gate.py
```

### Exemplos

```bash
# Formato texto (padrão)
python3 quality_gate.py

# Formato JSON (para scripts/CI)
python3 quality_gate.py --format json

# Formato Markdown (para documentação)
python3 quality_gate.py --format markdown

# Timeout personalizado
python3 quality_gate.py --timeout 60

# Modo verboso
python3 quality_gate.py --verbose

# Apenas listar comandos (não executar)
python3 quality_gate.py --list
```

## 🔧 Configuração

### 1. Via AGENTS.md (recomendado)

Crie `AGENTS.md` na raiz do projeto com seção de comandos:

```markdown
## 2. Comandos de Validacao (Quality Gate)
- Testes: `pytest -q --tb=short`
- Lint: `ruff check .`
- Type check: `mypy .`
- Build: `python3 manage.py check`
```

O script detectará automaticamente e usará estes comandos.

### 2. Padrões automáticos

Se não houver `AGENTS.md`, o script usa padrões baseados na stack:

#### Python

- Testes: `pytest -q --tb=short`
- Lint: `ruff check .`
- Type check: `mypy .`
- Django check: `python3 manage.py check` (se existir manage.py)

#### JavaScript

- Testes: `npm test -- --passWithNoTests`
- Lint: `npm run lint` ou `eslint .`
- Type check: `npm run type-check` ou `tsc --noEmit`
- Build: `npm run build`

## 📊 Output

### Formato Texto (padrão)

```
============================================================
QUALITY GATE REPORT
============================================================
Data: 2026-03-02 21:15:30
Projeto: meu-projeto

[PASS] tests (4.2s)
test_auth.py ....
test_models.py ...

[FAIL] lint (1.8s): Exit code: 1
app/views.py:15:80: E501 line too long (85 > 79)

------------------------------------------------------------
RESUMO: 1/2 passaram, 1 falharam
STATUS: FAIL
============================================================
```

### Formato JSON

```json
{
  "timestamp": "2026-03-02T21:15:30.123456",
  "project": "meu-projeto",
  "branch": "main",
  "commit": "a1b2c3d",
  "results": [
    {
      "name": "tests",
      "command": "pytest -q --tb=short",
      "success": true,
      "skipped": false,
      "output": "...",
      "error": null,
      "duration": 4.2
    }
  ],
  "summary": {
    "total": 2,
    "passed": 1,
    "failed": 1,
    "skipped": 0,
    "total_duration": 6.0
  }
}
```

### Formato Markdown

```markdown
# Quality Gate Report

**Data:** 2026-03-02 21:15:30
**Projeto:** meu-projeto
**Branch:** main
**Commit:** a1b2c3d

## Resultados

### ✅ tests
**Comando:** `pytest -q --tb=short`
**Duração:** 4.2s
```

test_auth.py ....
test_models.py ...

```

### ❌ lint
**Comando:** `ruff check .`
**Duração:** 1.8s
**Erro:** Exit code: 1
```

app/views.py:15:80: E501 line too long (85 > 79)

```

## Resumo

- **Total:** 2 comandos
- **✅ Passaram:** 1
- **❌ Falharam:** 1
- **⚪ Skipped:** 0
- **⏱️  Duração total:** 6.0s

**Status geral:** ❌ FAIL
```

## 🔌 Integração

### Com Pi.dev

```bash
# No Pi.dev, use o skill:
/skill:quality-gate-executor

# Ou execute diretamente:
!python3 quality_gate.py --format json
```

### Com Git hooks

```bash
# .git/hooks/pre-commit
#!/bin/bash
python3 quality_gate.py --timeout 30
if [ $? -ne 0 ]; then
  echo "❌ Quality gate falhou - commit bloqueado"
  exit 1
fi
```

### Com CI/CD (GitHub Actions)

```yaml
# .github/workflows/quality-gate.yml
name: Quality Gate
on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Run Quality Gate
      run: |
        python3 quality_gate.py --format json
      continue-on-error: false
```

## 🐍 API Python

Use como módulo em seus scripts:

```python3 from quality_gate import run_quality_gate, get_commands_to_run

# Executar quality gate programaticamente
results = run_quality_gate()

# Ou usar funções individuais
commands = get_commands_to_run()
for name, cmd in commands:
    print(f"Comando: {name} -> {cmd}")

# Verificar se passou
passed = all(r["success"] for r in results if not r["skipped"])
print(f"Quality gate: {'PASS' if passed else 'FAIL'}")
```

## ⚙️ Opções Avançadas

### Timeout por comando

```bash
# 60 segundos por comando (padrão: 300)
python3 quality_gate.py --timeout 60
```

### Dependências opcionais

```bash
# Instalar para funcionalidades extras
pip install radon bandit safety rich

# Agora inclui análise de complexidade e segurança
python3 quality_gate.py
```

### Variáveis de ambiente

```bash
# Modo debug (mostra tracebacks)
DEBUG=1 python3 quality_gate.py

# Ignorar comandos específicos
SKIP_TESTS=1 python3 quality_gate.py
```

## 🐛 Solução de Problemas

### "Nenhum comando encontrado"

1. Verifique se está na raiz do projeto
2. Crie `AGENTS.md` com comandos ou
3. Use uma stack suportada (Python/JavaScript)

### "Timeout expired"

1. Aumente timeout: `--timeout 600`
2. Ou corrija comandos lentos

### "Command not found"

1. Instale as ferramentas necessárias
2. Ou ajuste comandos no `AGENTS.md`

## 📄 Licença

MIT - veja [LICENSE](LICENSE)

## 🤝 Contribuição

1. Fork o repositório
2. Crie uma branch: `git checkout -b minha-feature`
3. Commit: `git commit -am 'Add feature'`
4. Push: `git push origin minha-feature`
5. Abra um Pull Request

## 📞 Suporte

- Issues: Reporte bugs ou sugestões
- Documentação: Consulte `SKILL.md` para uso no Pi.dev
- Exemplos: Veja os exemplos no código
