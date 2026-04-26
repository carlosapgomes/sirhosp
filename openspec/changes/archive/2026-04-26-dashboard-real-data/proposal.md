# dashboard-real-data

## Why

O dashboard e a página de censo exibem dados hardcoded/demo desde a implementação do portal.
Com o pipeline censo→pacientes→admissões em produção, já existe base de dados real suficiente
para substituir os stubs e entregar valor operacional imediato para diretoria e qualidade.

## What Changes

- **Dashboard**: substituir cards `internados`, `cadastrados`, `altas_24h` por queries reais
  contra `CensusSnapshot`, `Patient` e `Admission`
- **Dashboard**: substituir "Status da Coleta" (setores monitorados, última varredura) por
  dados reais do `CensusSnapshot` mais recente
- **Dashboard**: adicionar card "Leitos Vagas" com link para `/beds/`
- **Censo Hospitalar** (`/censo/`): substituir 8 pacientes demo e lista hardcoded de setores
  por query no `CensusSnapshot` mais recente (somente leitos ocupados)
- **Leitos** (`/beds/`): adicionar totalização no topo da página (cards de resumo:
  ocupados, vagos, manutenção, reservados, isolamento, total)
- **Leitos** (`/beds/`): converter layout de tabela para lista de cards (mobile-friendly),
  mantendo o expand/collapse de detalhes de cada setor
- **Sidebar**: adicionar link `Leitos` no menu de navegação

## Capabilities

### New Capabilities

- `dashboard-real-stats`: queries reais para indicadores do dashboard (internados,
  cadastrados, altas 24h, status da coleta) substituindo dados hardcoded
- `censo-real-data`: query no CensusSnapshot para alimentar a página de censo hospitalar
  com dados reais em vez de pacientes demo
- `bed-cards-with-totals`: conversão da página `/beds/` de tabela para cards com
  totalização no topo e link na sidebar

### Modified Capabilities

Nenhuma — os specs existentes de `services-portal-navigation` cobrem a estrutura do portal,
e este change apenas troca a fonte de dados (de stub para query), sem alterar os requisitos
de navegação ou comportamento especificado.

## Impact

- `apps/services_portal/views.py` — substituir dados demo por queries reais
- `apps/services_portal/templates/services_portal/dashboard.html` — adicionar card "Leitos Vagas"
- `apps/services_portal/templates/services_portal/censo.html` — remover fallback demo, usar dados reais
- `apps/census/views.py` — adicionar totais agregados ao contexto
- `apps/census/templates/census/bed_status.html` — reescrever com layout de cards + totalização
- `templates/includes/sidebar.html` — adicionar link "Leitos"
- Testes unitários: novos testes para cada query/view que substitui dados demo
- Testes de integração: verificar que páginas renderizam com dados reais do CensusSnapshot
