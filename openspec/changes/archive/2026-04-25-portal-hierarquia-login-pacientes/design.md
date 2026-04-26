# Design: portal-hierarquia-login-pacientes

## Context

Estado atual relevante:

- `/` exibe página institucional básica.
- `/ingestao/*` já existe e exige login.
- `/patients/<id>/admissions/` e `/admissions/<id>/timeline/` existem, mas faltam hierarquia principal e entrada por lista.
- Busca clínica já existe apenas como JSON em `/search/clinical-events/`.

Objetivo deste change: criar trilha de navegação mínima, previsível e autenticada, sem ampliar escopo para frontend complexo.

## Design Goals

1. Navegação simples e direta para operador.
2. Implementação incremental por slices verticais com baixo risco.
3. Alterar o mínimo de arquivos por slice para evitar drift.
4. Preservar stack atual (Django templates + bootstrap).
5. TDD sempre que fizer sentido (views/services/templates com teste de comportamento).

## Decisions

### 1) Fluxo de entrada autenticado padrão

- Landing pública mantém papel institucional.
- Login explícito via rota dedicada (`/login/`) e template próprio simples.
- Pós-login redireciona para `/patients/`.

### 2) Lista de pacientes como hub principal

- Nova página `/patients/` para listagem.
- Filtro textual único `q` com busca em:
  - `Patient.name`
  - `Patient.patient_source_key` (registro).
- Paginação simples para evitar página gigante e queries pesadas.

### 3) Hierarquia e ações contextuais

- `/patients/` -> abre admissões.
- `/patients/<id>/admissions/` -> abre timeline.
- Em admissões/timeline:
  - ação "Nova extração" (com pré-preenchimento de registro quando possível);
  - ação "Busca JSON" (link para endpoint JSON existente).

### 4) Busca continua JSON-only neste ciclo

- Sem nova tela HTML para busca.
- Apenas enlaces contextuais ao endpoint já implementado.

### 5) Controle de acesso

- Páginas de portal operacional devem exigir autenticação.
- Exceções públicas: `/` e `/health/`.

## Risks and Mitigations

### Risco: drift por tocar muitos templates de uma vez

Mitigação: slices pequenos, com limite estrito de arquivos e gates por slice.

### Risco: quebra de testes existentes ao endurecer autenticação

Mitigação: incluir ajuste de testes no mesmo slice que introduzir `login_required` (TDD red -> green).

### Risco: escopo subir para "novo frontend"

Mitigação: proibir HTMX avançado/SPA/DRF neste change; usar apenas templates e forms GET simples.

## Validation Strategy

- Unit/integration tests focados em:
  - redirecionamento de login;
  - listagem/filtragem de pacientes;
  - navegação hierárquica;
  - presença de ações contextuais;
  - proteção por autenticação.
- Gates mínimos por slice + gate final completo.

## Slice Strategy (overview)

- **S1**: entrada (landing + login + redirect pós-login).
- **S2**: hub `/patients/` com busca por nome/registro.
- **S3**: ações contextuais e pré-preenchimento de extração.
- **S4**: hardening de autenticação nas rotas de portal + regressão final.
