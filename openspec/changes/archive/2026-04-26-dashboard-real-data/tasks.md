# Tasks: dashboard-real-data

## 1. Slice S1 — Dashboard com indicadores reais

**Arquivos (4)**: `apps/services_portal/views.py`, `apps/services_portal/templates/services_portal/dashboard.html`, `tests/unit/test_services_portal_dashboard.py` (novo), `tests/unit/conftest.py` (fixtures)

TDD: RED → testa que dashboard retorna 0 quando não há dados; GREEN → implementa queries reais.

- [x] 1.1 Criar fixtures de teste: `Patient`, `Admission` com/sem `discharge_date`, `CensusSnapshot` ocupado/vago
- [x] 1.2 Teste unitário: `dashboard()` retorna `internados=0`, `cadastrados=0`, `altas_24h=0` quando BD vazio
- [x] 1.3 Teste unitário: `dashboard()` retorna contagens corretas com dados populados
- [x] 1.4 Teste unitário: `dashboard()` mostra "Nenhum dado de coleta" quando sem CensusSnapshot
- [x] 1.5 Teste unitário: `dashboard()` mostra setores e última varredura corretos com CensusSnapshot
- [x] 1.6 Substituir `stats` hardcoded por queries: `CensusSnapshot.objects.filter(bed_status="occupied", captured_at=latest).count()`, `Patient.objects.count()`, `Admission.objects.filter(discharge_date__gte=now-24h).count()`
- [x] 1.7 Substituir `coleta` hardcoded por queries: setores distintos no último snapshot, `captured_at` formatado
- [x] 1.8 Adicionar card "Leitos" no dashboard (seção quick actions) com link `/beds/`
- [x] 1.9 Rodar `./scripts/test-in-container.sh unit` e `lint` — confirmar verde

## 2. Slice S2 — Censo Hospitalar com dados reais

**Arquivos (3)**: `apps/services_portal/views.py`, `apps/services_portal/templates/services_portal/censo.html`, `tests/unit/test_services_portal_censo.py` (novo)

TDD: RED → testa que censo retorna lista vazia quando sem dados; GREEN → implementa query real.

- [x] 2.1 Teste unitário: `censo()` retorna lista vazia e mensagem quando sem CensusSnapshot
- [x] 2.2 Teste unitário: `censo()` retorna pacientes ocupados do snapshot mais recente
- [x] 2.3 Teste unitário: `censo()` filtra por setor e busca textual corretamente
- [x] 2.4 Teste unitário: dropdown de setores é populado com setores reais do snapshot
- [x] 2.5 Substituir `pacientes_demo` e `setores_demo` por query no CensusSnapshot (apenas ocupados, mais recente)
- [x] 2.6 Substituir filtro manual de dicts por `.filter()` no QuerySet do CensusSnapshot
- [x] 2.7 Ajustar template se necessário — preservar layout responsivo existente (tabela desktop + cards mobile)
- [x] 2.8 Rodar `./scripts/test-in-container.sh unit` e `lint` — confirmar verde

## 3. Slice S3 — /beds/ com cards, totalização e link na sidebar

**Arquivos (4)**: `apps/census/views.py`, `apps/census/templates/census/bed_status.html`, `templates/includes/sidebar.html`, `tests/unit/test_census_bed_views.py` (modificar existente ou novo)

TDD: RED → testa que contexto inclui totais e lista de setores; GREEN → implementa cards + totais.

- [x] 3.1 Teste unitário: `bed_status_view()` inclui `totals` no contexto com chaves: `occupied`, `empty`, `maintenance`, `reserved`, `isolation`, `total`
- [x] 3.2 Teste unitário: totais agregados somam corretamente através de todos os setores
- [x] 3.3 Teste unitário: sidebar renderizada inclui link "Leitos" com href `/beds/`
- [x] 3.4 Adicionar agregação de totais globais na view `bed_status_view()` (`.values("bed_status").annotate(count=Count("id"))` adicional)
- [x] 3.5 Reescrever `census/bed_status.html`: cards no topo com totais + lista de cards de setor com collapse (substituir `<table>` por `<div>` Bootstrap)
- [x] 3.6 Adicionar item "Leitos" na sidebar (`templates/includes/sidebar.html`) com ícone e link `/beds/`
- [x] 3.7 Rodar `./scripts/test-in-container.sh unit` e `lint` — confirmar verde

## 4. Validação final

- [x] 4.1 Rodar `./scripts/test-in-container.sh quality-gate` e garantir tudo verde
- [x] 4.2 Rodar `markdownlint-cli2` nos arquivos .md alterados/criados
- [x] 4.3 Verificar visualmente (screenshot ou descrição) que dashboard, censo e /beds/ renderizam com dados reais
