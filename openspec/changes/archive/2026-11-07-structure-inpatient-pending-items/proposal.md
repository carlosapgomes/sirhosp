# Proposal

## Why

A demonstração do rastreador revelou que tipo e texto livre não bastam para
registrar os detalhes administrativos acompanhados pela Desospitalização e
pela diretoria. Um catálogo organizado e informações estruturadas permitirão
cadastro mais rápido, acompanhamento consistente e análise em XLSX sem
transformar o módulo em prontuário ou rastreador clínico.

## What Changes

- Estender `PendingItemType`, `PendingItem` e `PendingItemRevision`, sem
  substituir o rastreador, suas identidades ou integrações com internações.
- Introduzir categorias e o catálogo consolidado em [catalog.md](catalog.md),
  com quatro perfis fixos: agendamento, tratamento com período, registro
  simples e assinatura de documento. RNM terá contraste e sedação independentes.
- Oferecer cadastro individual com categoria, tipo e campos progressivos,
  busca contextualizada e ações Salvar / Salvar e adicionar outra.
- Tornar observações opcionais nos tipos definidos e obrigatórias nas opções
  genéricas Outro/Outros. Datas específicas serão opcionais; agendamento
  exigirá resposta explícita Sim/Não nos novos cadastros aplicáveis.
- Apresentar categoria e detalhes no contexto da internação, no dashboard,
  na edição rápida e no histórico; acrescentar filtro por categoria.
- **BREAKING**: ampliar o esquema de colunas XLSX e exportar datas como datas
  nativas, mantendo textos literais, uma linha por pendência e o mesmo recorte
  filtrado do painel. Consumidores dependentes das posições/tipos atuais de
  células precisarão se adaptar.
- Preservar finalizações humanas, estados finais imutáveis, permissões atuais
  e encerramento automático de ativas por saída hospitalar confirmada,
  incluindo óbito, como Encerrada sem resolução com autoria Sistema.

### Não objetivos

- Inferir risco, prioridade, prognóstico ou conduta clínica; nomes como Risco
  de óbito são apenas classificações administrativas informadas pela equipe.
- Finalizar por data agendada, previsão de término ou assinatura; integrar
  agenda, prescrições, exames ou assinatura a sistemas externos.
- Alterar grupos/permissões, regras de episódio atual, saídas ou reconciliação.
- Construir campos personalizados, formulário genérico configurável, EAV,
  novos serviços, workers, dependências ou infraestrutura.
- Excluir dados de produção. Os poucos registros de teste não justificam
  conversão textual complexa; eventual descarte exige autorização separada.

## Capabilities

### New Capabilities

Nenhuma. A mudança evolui as duas capacidades existentes.

### Modified Capabilities

- `inpatient-pending-items`: catálogo categorizado, campos tipados por perfil,
  observações condicionais, histórico completo e preservação não destrutiva.
- `pending-items-portal`: cadastro progressivo, apresentação e edição dos
  detalhes, filtro por categoria e XLSX estruturado.

## Impact

- `apps/pending_items/`: models, migrations, admin, services, forms, consultas,
  views, templates e exportação. Rotas existentes serão preservadas.
- Testes unitários e de integração existentes de pendências; jornadas
  Playwright com dados sintéticos e download real de XLSX.
- PostgreSQL: migrations aditivas, carga do catálogo e classificação
  conservadora dos tipos existentes; sem apagar itens ou revisões.
- Sem alterações em scraping, ingestão de dados clínicos ou agendamento de
  jobs. As integrações de saída e merge exigem regressão, não redesign.
- Riscos principais: interpretar ausência de informação como Não; perder
  detalhes ao trocar tipo; não versionar campos novos; divergência entre
  formulário, serviço, painel e planilha; colisões com catálogo administrativo
  já existente. O design e os cenários de aceitação tratam esses riscos.

## Estado

Planejamento para revisão humana. A criação desta change não autoriza sua
implementação, descarte de dados, deploy ou alteração de permissões.
