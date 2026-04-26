# dashboard-real-data

## Context

O portal SIRHOSP foi implementado com dados demo/stub nas páginas de dashboard e censo
porque o pipeline de ingestão ainda não estava operacional. Agora que `censo-inpatient-sync`
está completo e produzindo `CensusSnapshot`, `Patient` e `Admission` reais, os dados demo
podem ser substituídos.

Estado atual:

- `CensusSnapshot`: contém o censo hospitalar completo (todos os leitos, todos os status)
- `Patient`: pacientes identificados via `patient_source_key` (prontuário)
- `Admission`: internações com `discharge_date` (null = ainda internado)

A página `/beds/` (Slice S6) já existe e funciona com dados reais, mas usa layout de
tabela, não tem totalização no topo e não aparece na sidebar nem no dashboard.

## Goals / Non-Goals

**Goals:**

1. Dashboard exibir número real de internados (CensusSnapshot ocupados), pacientes
   cadastrados (Patient.objects.count()) e altas nas últimas 24h (Admission com
   discharge_date nas últimas 24h)
2. Status da coleta refletir dados reais: setores distintos no CensusSnapshot mais
   recente e timestamp da última captura
3. Dashboard ganhar card "Leitos Vagas" com link para `/beds/`
4. Página `/censo/` exibir pacientes internados reais (CensusSnapshot ocupados) com
   filtro por setor real e busca textual
5. Página `/beds/` ganhar totalização agregada no topo (cards de resumo) e layout
   mobile-friendly (cards que expandem em vez de tabela)
6. Sidebar ganhar link "Leitos" apontando para `/beds/`

**Non-Goals:**

- Não alterar a estrutura de navegação do portal além de adicionar "Leitos"
- Não modificar modelos nem banco de dados
- Não introduzir cache ou otimização de performance (queries são diretas e leves)
- Não alterar o Monitor de Risco (já usa dados reais com fallback demo)
- Não implementar agendamento systemd/cron (outro change)
- Não alterar a página de busca JSON

## Decisions

### D1: Queries diretas no Django ORM, sem nova camada de serviço

**Decisão**: As views farão queries diretas via Django ORM (`.aggregate()`, `.count()`,
`.filter()`) em vez de criar services dedicados.

**Alternativa considerada**: Criar `DashboardService` e `CensoService` em `apps/services_portal/services.py`.
**Por que não**: As queries são simples (1-2 linhas cada), não há lógica de negócio
complexa, e criar services para queries triviais adiciona indireção desnecessária na fase 1.
Se as queries crescerem em complexidade, extrair para service depois.

### D2: Cards com collapse no /beds/ em vez de tabela

**Decisão**: Converter `/beds/` de `<table>` para `<div>` cards Bootstrap com
`data-bs-toggle="collapse"` para expandir detalhes dos leitos de cada setor.

**Alternativa considerada**: Manter tabela e adicionar só totalização.
**Por que não**: O usuário explicitamente pediu cards por serem mobile-friendly. Bootstrap
já dá suporte nativo a collapse. Cards com collapse mantêm a mesma funcionalidade
(linha clicável expande detalhes) com layout responsivo melhor.

### D3: Totalização no topo do /beds/ via agregação simples

**Decisão**: Os totais (ocupados, vagos, manutenção, reservados, isolamento) vêm de um
`.values("bed_status").annotate(count=Count("id"))` adicional na view, exibidos como
cards horizontais no topo da página.

### D4: Página /censo/ usa apenas leitos ocupados

**Decisão**: A página de censo hospitalar mostra apenas os leitos com `bed_status="occupied"`
do CensusSnapshot mais recente. Leitos vagos, manutenção etc. ficam só na página `/beds/`.

**Alternativa considerada**: Mostrar todos os leitos como a página /beds/.
**Por que não**: O propósito do censo é "quem está internado", não "estado dos leitos".
Manter separação clara entre as duas páginas.

### D5: Filtro de setor no /censo/ dinâmico

**Decisão**: A lista de setores no dropdown de filtro do `/censo/` será gerada
dinamicamente a partir dos setores distintos com leitos ocupados no CensusSnapshot
mais recente (em vez da lista hardcoded atual).

## Risks / Trade-offs

- **CensusSnapshot vazio**: Se não houver captura de censo, dashboard e censo mostrarão
  zeros/mensagem informativa. Já existe fallback no `/beds/` ("Nenhum dado de censo disponível").
  → Mitigação: replicar esse padrão de fallback para dashboard e censo.
- **Performance com muitos leitos**: Um hospital grande pode ter 500+ leitos; queries de
  agregação são O(n) no banco mas triviais para PostgreSQL.
  → Mitigação: sem risco real na fase 1; reavaliar se houver lentidão observada.
- **Perda do collapse no mobile com cards**: O collapse do Bootstrap funciona bem em mobile
  se o `data-bs-target` estiver correto.
  → Mitigação: testar em viewport mobile (responsivo) como parte dos testes.
