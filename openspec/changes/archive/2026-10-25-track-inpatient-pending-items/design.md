# Design

## Context

A motivação e os limites de produto estão em `proposal.md`; os requisitos estão nas duas delta specs desta change. Este documento é uma proposta técnica para revisão, não autorização para implementar.

Constatações no checkout:

- `apps/patients/models.py`: `Admission` já é a identidade canônica do episódio, com aliases e `merged_into`; seu manager padrão oculta registros unificados.
- `apps/patients/views.py` e `templates/patients/admission_list.html` dentro do app: a tela seleciona explicitamente uma internação e pode mostrar episódios antigos.
- `apps/services_portal/views.py::_build_censo_context`: a lista atual usa o maior `captured_at` de `CensusSnapshot` e leitos ocupados. A escolha atual da internação mais recente serve à apresentação do censo, mas não constitui autorização segura para escrever pendências quando houver ambiguidade.
- `apps/census/models.py` e `apps/census/services.py::upsert_patient_movements`: movimentações possuem vínculo opcional à internação, data com precisão de dia e captura incremental; o primeiro registro não garante o primeiro setor real.
- Saídas canônicas são aplicadas por `apps/patients/reconciliation.py::apply_discharge_exit`, pelo snapshot de internações em `apps/ingestion/services.py::upsert_admission_snapshot` e por `apps/patients/admission_merge.py::merge_admissions`. Reconciliação e merge já possuem transação/locks; o snapshot atualmente processa itens em autocommit, sem lock próprio de Admission, e precisa receber a fronteira transacional por item descrita em D5.
- O registro de relações do merge recusa novas FKs não classificadas. A rotina legada `_consolidate_period_duplicates` ainda pode excluir internações e não transfere genericamente suas relações.
- `process_discharges` e helpers PDF legados ainda existem, mas o caminho operacional PDF está desativado por contrato; não são nova evidência confiável para esta feature.
- `openpyxl`, Playwright/Chromium, HTMX e Bootstrap já existem. O shell referencia Bootstrap/HTMX via CDN; a imagem de testes já instala Chromium.

Referências de compatibilidade: `openspec/specs/patient-admission-mirror/spec.md`, `admission-duplicate-resolution/spec.md`, `admission-exit-reconciliation/spec.md`, `patient-movement-model/spec.md`, `censo-current-list-export/spec.md` e `docs/dev-verification.md`.

## Goals / Non-Goals

**Goals:** manter o domínio testável fora de views, preservar histórico e episódio, compartilhar consultas entre os modos do agregado e o XLSX e integrar saídas sem outro worker ou scheduler.

**Non-Goals:** alterar o algoritmo canônico de identidade/saída, corrigir globalmente movimentações históricas, substituir toda a consolidação legada ou transformar pendências em mecanismo de decisão clínica. Não ativar a suíte do portal dev implantado nem alargar seus allowlists.

## Decisions

### D1 — Domínio próprio e três tabelas pequenas

Criar `apps/pending_items/` com models, services, queries, forms, views, URLs, admin e templates específicos. Registrar o app em `config/settings.py` e suas rotas em `config/urls.py`.

| Entidade              | Conteúdo e invariantes                                                                                                                                                                                |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PendingItemType`     | Nome único e identificação estável de `Outro`; catálogo administrado no Django admin. Tipos referenciados não são excluídos e `Outro` não pode ser removido ou transformado em outro conceito.        |
| `PendingItem`         | FK protegida para `Admission`, tipo, descrição, status, criação/atualização, autoria humana ou Sistema, versão atual e horário de finalização derivado da transição. Sem FK redundante para paciente. |
| `PendingItemRevision` | FK protegida para a pendência, número de versão, ação, horário, autoria, snapshot de tipo/nome/descrição/status e anotação opcional. Sem segunda FK mutável para Admission.                           |

A versão inicial representa a criação. A unicidade `(pending_item, version)` impede versões duplicadas; constraints impõem o conjunto de status e a consistência de finalização. Não adicionar unicidade de tipo por internação. O horário de finalização é produzido pela transição, sem entrada retrospectiva manual; não é um novo campo operacional a preencher.

Usar FKs opcionais para usuários com `SET_NULL` e rótulos de autoria preservados nos snapshots para que renomeação/exclusão de conta não destrua a rastreabilidade. Uma autoria `system` explícita distingue Sistema de uma conta humana indisponível. Preservar também o criador original e a última atualização humana nas versões quando o último autor atual for Sistema.

A anotação de finalização pertence à versão da alteração; não criar outra tabela de acompanhamentos nem justificativa obrigatória redundante. A descrição atual continua obrigatória e pode permanecer inalterada numa finalização sem anotação.

Alternativas rejeitadas: JSON acumulado na linha principal, pela dificuldade de impor unicidade/append e consultar versões; event sourcing genérico, pelo custo sem necessidade; FK independente para paciente, pelo risco de divergência do episódio.

### D2 — Grupo explícito, sem bypass de superusuário

Criar o grupo `Desospitalização` idempotentemente em migration de dados, sem adicionar usuários. Para escrita humana, a política canônica verifica `is_authenticated` e associação efetiva ao grupo, não `is_staff`, `is_superuser` ou apenas `has_perm`, cujo comportamento padrão permite bypass por superusuário.

A mesma política protege view e serviço de escrita e é revalidada no POST. Todas as leituras, versões e XLSX usam autenticação sem exigir grupo. O administrador mantém o catálogo e associa usuários ao grupo; isso não concede, por si só, escrita em pendências.

Não expor CRUD direto de pendências/versões no admin: eventual registro desses modelos é somente leitura, sem delete action. A operação automática tem entrada interna dedicada e autoria Sistema; o cliente nunca escolhe uma identidade/flag para impersonar Sistema. Escritas HTTP exigem POST e CSRF.

### D3 — Episódio atual e primeira unidade sem inferência entre internações

Um único resolver compartilhado por elegibilidade de escrita, agregado, indicadores e XLSX obtém uma referência de censo: maior `captured_at`, somente leitos ocupados, mesma definição da tela atual. Resolver paciente pelo identificador e sistema fonte pertinentes. A internação atual precisa ser canônica, aberta e única para o paciente; não usar `.first()` para resolver múltiplas candidatas. O endpoint também confere o relacionamento paciente/internação recebido.

Repetições equivalentes da mesma ocupação contam uma única vez. Quando o mesmo paciente aparece em ocupações conflitantes na foto, a identidade do paciente é ambígua ou existem duas internações abertas canônicas, o resolver não escolhe arbitrariamente: exclui o caso do agregado, dos indicadores e do XLSX e bloqueia escrita humana. Usar as mesmas fixtures para provar essa paridade; não calcular indicadores por um caminho menos conservador que a lista.

Para uma escrita, o paciente precisa constar nessa foto e a internação solicitada precisa ser aquela identificada. Em ausência/ambiguidade, apresentar a mensagem de PI-03 e contato com administrador. Não disparar ingestão, criar episódio temporário ou mover o usuário silenciosamente de uma internação selecionada para outra. Ausência do censo bloqueia escrita humana, mas não finaliza registros.

Na consulta histórica autenticada, a internação explicitamente selecionada continua consultável, inclusive nos casos excluídos do agregado por ambiguidade. No recorte atual compartilhado, excluir conteúdo de episódios anteriores, duplicatas ocultas e pacientes fora da foto. Uma saída já confirmada prevalece sobre presença residual no censo.

Para primeira unidade, considerar movimentações do mesmo paciente atribuíveis ao episódio e ordenar por data, sequência e PK como desempate. Validar o intervalo local da internação para não aceitar FK best-effort evidentemente incompatível. Movimentações sem FK só podem ser aproveitadas quando o intervalo identifica inequivocamente o episódio; sobreposição de datas, reinternação no mesmo dia ou falta de limites não autoriza adivinhação. Não corrigir vínculos de movimentações nesta change. Sem candidato confiável, mostrar `Primeira unidade não identificada`.

O texto visível será `Primeira unidade de internação`, mas ajuda discreta esclarecerá que é o primeiro setor registrado disponível. Pronto-socorro não recebe exclusão especial. Unidade/leito atuais e especialidade vêm da foto atual; rótulos de especialidade reutilizam catálogo e fallback existentes, sem mudar o censo.

### D4 — FSM, concorrência e snapshots atômicos

```text
Ativa --> Resolvida
Ativa --> Encerrada sem resolucao
```

Estados finais não têm transições de saída nem correções de campos. Desabilitar ações na interface é apenas apresentação: serviços e POST precisam rejeitá-las. Não oferecer exclusão física; erro de cadastro termina como Encerrada sem resolução, com anotação opcional.

Executar cada escrita em transação, com ordem de lock `Admission` antes de `PendingItem`. Revalidar internação, status e autorização antes de mutar. O formulário envia a versão observada; divergência causa conflito explícito, sem sobrescrever conteúdo. Incrementar a versão e gravar a revisão na mesma transação; erro na revisão desfaz a alteração. Um envio sem mudança efetiva não cria versão artificial.

A revisão guarda o snapshot resultante; a revisão anterior fornece o antes. Os rótulos de tipo e autoria são capturados na época, sem duplicar nome/registro do paciente. Timestamps são timezone-aware; apresentação usa o timezone institucional. GETs de detalhe, histórico, agregado e exportação são somente leitura.

Alternativas rejeitadas: last-write-wins, pois perde alterações da equipe; confiar só no lock da pendência, pois não serializa criação com saída; signals genéricos de `Admission.save`, pois também capturariam restaurações/manutenção sem contexto de evidência.

### D5 — Encerramento como parte das saídas já confirmadas

Um serviço idempotente `close_pending_items_for_confirmed_exit` recebe a internação bloqueada e referência estrutural à origem confiável. Somente nos caminhos válidos/reconciliáveis abaixo, após estabelecer o estado canônico resultante, `discharge_date` não nulo determina o encerramento de todas as pendências ainda ativas. Não exigir uma nova mudança de nulo para preenchido nem que a evidência recebida agora contenha o fim: o episódio pode já estar fechado por evidência anterior.

Dentro da transação explícita do writer, selecionar pendências ativas em ordem de PK, finalizar como `closed_unresolved`, gravar revisão com Sistema e motivo `confirmed_exit`, e preservar as já finalizadas. O horário da alteração é o do processamento; a data efetiva de saída permanece na internação/evidência e não é inventada como data de uma anotação humana.

Integrar os caminhos conhecidos, sem mudar seus critérios de confirmação:

| Caminho existente           | Integração necessária                                                                                                                                                                                                                                                                                                                                                                           |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apply_discharge_exit`      | Nos resultados `reconciled` e `already_reconciled`, usar o estado fechado sob lock e encerrar ativas residuais na mesma transação da saída e da auditoria de reconciliação aplicável. Isso inclui evidência repetida sobre fechamento anterior aos hooks. Não criar finalização extra para estados já finais nem alterar as regras existentes de auditoria da evidência.                        |
| `upsert_admission_snapshot` | Criar uma transação por item/internação, revalidar a identidade canônica sob lock, persistir os campos e encerrar ativas sempre que o estado resultante estiver fechado, mesmo se `admission_end` estiver ausente no item e o fechamento já existir. Alias e consolidação daquele item pertencem à mesma transação. A fronteira compartilhada cobre os dois workers sem hooks duplicados neles. |
| `merge_admissions`          | Após transferir relações e combinar o período, consultar o estado resultante da canônica sob a transação do merge. Se fechado, encerrar ativas transferidas e preexistentes, inclusive quando o fim já estava na canônica ou veio da duplicata e `confirmation.episodes[0].admission_end` é nulo.                                                                                               |

O snapshot não possui hoje a transação pressuposta por um serviço atômico: S2 precisa adicioná-la por internação/item, e não envolvendo a lista inteira. Para episódio existente, depois de resolver a identidade, adquirir o lock de Admission e revalidar a mesma identidade/paciente/período antes de escrever; uma resolução que mudou/foi unificada não autoriza gravar pelo objeto obsoleto. Preservar a ordem Admission → PendingItem. Criar uma internação nova, quando já autorizado pelo resolvedor existente, também ocorre dentro da transação daquele item.

Se qualquer gravação do item, alias, etapa de consolidação ou revisão falhar, desfazer todas as alterações daquele item e propagar a falha ao chamador; itens anteriores já confirmados permanecem persistidos, e itens seguintes não são processados naquela chamada. Não introduzir atomicidade de snapshot inteiro, supressão de erro como sucesso, auditoria de reconciliação fictícia no snapshot ou nova política de retry. Na reconciliação/merge, preservar o rollback da operação inteira e de sua auditoria existente.

A matriz de testes inclui explicitamente: merge fechado pelos três caminhos de combinação do período, `already_reconciled` com ativas residuais, snapshot com item anterior válido e falha de revisão no seguinte, e snapshot concorrendo tanto com edição quanto com cadastro. Repetição/correção de horário não gera revisão extra para estados finais. Desaparecimento do censo, `alta_em` sem saída, evidência ambígua/conflitante e helpers PDF inativos não disparam o serviço.

Rollback autorizado de saída pode restaurar uma internação aberta; ele não apaga revisões nem reabre pendências. Caso volte a existir uma internação atual elegível, uma nova pendência poderá ser cadastrada pelo usuário conforme o contrato de recorrência. Não construir rollback de FSM nem novo processamento contínuo.

### D6 — Preservação em merge e contenção da exclusão legada

Desde S1, registrar `pending_items` na classificação de relações de `Admission` como conteúdo que segue a internação canônica. Revisões continuam ligadas à mesma pendência; a auditoria de merge já existente registra a transferência estrutural sem copiar descrições clínicas para seus manifestos/logs. Rollback restaura a propriedade das relações conforme o contrato existente, preservando as versões e estados finais.

No caso sequencial, a guarda evita que a ingestão dependa de uma falha de FK: na rotina `_consolidate_period_duplicates`, se qualquer candidata possuir pendências, não executar a consolidação destrutiva daquele conjunto. Preservar as candidatas e deixar a confirmação/unificação canônica existente tratar o caso. A guarda antecede transferências ou exclusões, dentro da fronteira transacional da consolidação. Conjuntos sem pendências mantêm comportamento legado; não redesenhar sua seleção nem ampliar o merge automático.

A guarda não promete eliminar a corrida com um cadastro que chega depois da verificação. Aceitar esse caso residual como falha conservadora: `ProtectedError`/`IntegrityError` na operação perdedora deve abortar sua transação, sem perda de pendência nem transferências parciais, e jamais ser convertido em sucesso. A criação mantém seu lock de Admission e a FK protegida; a consolidação mantém rollback de suas transferências, e, em S2, o erro do snapshot desfaz o item inteiro conforme D5. Não introduzir lock de todas as candidatas ou retry novo; uma repetição pelo fluxo existente passa novamente pela guarda e pelas regras de identidade.

Testes devem atualizar o inventário explícito e demonstrar transferência, consulta pela canônica, rollback estrutural, guarda sequencial e uma intercalação controlada entre guarda e exclusão que prove a falha conservadora/ausência de transferências parciais. Essa pequena expansão em ingestão é necessária já no slice que cria a nova FK, não uma melhoria adjacente.

### D7 — Portal e consultas compartilhadas

Rotas propostas, todas autenticadas:

- `/admissions/<admission_id>/pending-items/`: listagem contextual e cadastro humano elegível, acessível pelo período selecionado na tela de admissões.
- `/pendencias/`: agregado, `view=patients` por padrão e `view=items` como alternativa.
- `/pendencias/<id>/history/`: versões somente leitura, em fragmento recolhível.
- `/pendencias/<id>/edit/`: GET de formulário e POST de atualização/finalização.
- `/pendencias/export.xlsx`: resultado filtrado completo, sem paginação aplicada.

Nomes podem acompanhar convenções do app, mas relações e comportamento não mudam. Reusar o formulário contextual no modal de edição rápida, usando Bootstrap e HTMX já existentes. Exibir paciente, registro e período no formulário; preservar filtros/modo após sucesso. Após finalização, remover o item do recorte de ativas e retirar o grupo vazio, sem esconder falhas de servidor. Reconsultar os indicadores após escrita confirmada.

A camada de queries fornece uma seleção por pendência antes do agrupamento. Paginar por paciente na visão padrão, carregando todas as correspondências de cada paciente da página; por pendência na alternativa. Fazer seleção relacionada e prefetch em lote, sem queries no loop de templates e sem carregar todas as revisões de todos os pacientes para renderizar a página inicial. Histórico é carregado sob demanda, continuando autenticado.

Filtros canônicos: status (padrão active, alternativas resolved/closed_unresolved/all), unidade, leito, especialidade, tipo, criador, último atualizador e limites mínimo/máximo em dias de tempo em aberto. Comparar durações exatas, sem arredondar antes do filtro; após finalização usar o instante da transição. Mostrar unidade de medida nos controles e validar limites negativos/invertidos. Sistema é opção explícita de último atualizador. Não criar campo de responsável designado. Ordenar estavelmente por unidade/leito/paciente e criação/PK da pendência, permitindo ordem por tempo em aberto. Nome/registro e identificação do episódio continuam visíveis mesmo ao repetir paciente.

As duas visualizações têm paridade de recorte, usam tabela/grupos em desktop e apresentação adequada a celular. Não extrair um framework genérico do grande módulo de censo: compartilhar apenas helpers realmente necessários à semântica do recorte/rótulos, preservando os testes e o XLSX atuais do censo.

### D8 — Indicadores globais e XLSX sem efeitos colaterais

Uma seleção base hospitalar de pendências ativas atuais alimenta `Count` distinto de pacientes, média e máximo de `now - created_at`. Capturar `now` uma vez por requisição; não calcular média das médias por paciente nem usar `updated_at`. Filtros da lista, status selecionado, modo e paginação não entram nessa consulta. Com zero ativas: contador zero, durações `—` e mensagem acessível de ausência de pendências ativas.

A exportação reutiliza os filtros e a ordenação da seleção por pendência, ignorando apenas modo/paginação. Usa `openpyxl` e `BytesIO`, sem arquivo temporário clínico. Colunas na ordem de PP-08; datas convertidas ao timezone institucional antes da representação compatível com Excel. Campos textuais são gravados explicitamente como texto literal, inclusive nomes, registros, rótulos e anotações que comecem com caracteres de fórmula; testar tipo da célula e conteúdo, não só abertura do workbook. Não exportar revisões nem concatenar várias pendências numa célula.

Usar escape de template e logs sem payload clínico/credenciais. Todas as respostas novas autenticadas com conteúdo clínico — HTML contextual/agregado, formulários, fragmentos de histórico e XLSX, inclusive reexibição de erros de formulário — devem conter `Cache-Control` com `private` e `no-store`; verificar essas diretivas em testes HTTP dos slices que introduzem cada superfície. Não presumir que autenticação torna seguro HTML não escapado ou fórmula em planilha. A proteção é restrita à feature nova, sem refatoração global de segurança.

### D9 — Evidência executável e quatro slices verticais

Sequência: S1 gestão contextual auditada; S2 integração de saída; S3 agregado; S4 XLSX. Schema, autorização e uma jornada contextual ficam juntos em S1; não há slice isolado de banco ou de template. Os contratos estão em `slices/` e o mapeamento em `tasks.md`.

TDD nos services, queries e fronteiras HTTP/persistência. Integração obrigatória para migrations, grupo, enum/constraints, inventário/merge, writers de saída e arquivo XLSX. Usar relógio controlado e somente fixtures sintéticas.

Para runtime de UI, usar a fixture `live_server` de pytest-django com acesso transacional ao banco PostgreSQL efêmero e a API de Playwright já instalada, dentro da suíte de integração. Não depender do portal dev implantado, suas contas reservadas ou sua allowlist read-only. A imagem do test-runner já contém Chromium. O mecanismo de assets será interceptar as URLs CDN do shell por `page.route`/`route.fulfill`, respondendo com arquivos reais versionados em `tests/fixtures/browser_assets/`, MIME correto e versões/licenças preservadas de Bootstrap/HTMX/CSS necessários ao roteiro. Cobrir dependências transitivas usadas pelo cenário e não permitir fallback silencioso para rede/CDN ou JS simulado. Não mudar o shell de produção nem introduzir biblioteca/runner genérico.

Em S1, primeiro comprovar o harness mínimo: servidor e PostgreSQL de testes, assets locais carregados e login real em uma página existente. Só então registrar RED da jornada contextual de pendências ausente e estendê-la até GREEN no mesmo slice. Falha de browser, assets, isolamento ou login é bloqueio de infraestrutura, não RED de produto. S3/S4 reutilizam esse harness para modal e download.

Login pelo formulário, contextos isolados, desktop e mobile; provar cadastro, histórico, resolução, leitura sem escrita, modal, filtros/modos e download conforme cada slice. Reportar browser ausente ou dependências indisponíveis como bloqueio, nunca como sucesso/skip que simule aceite. Casos de permissão e concorrência continuam cobertos por integração HTTP/transacional, não só por visibilidade de botão. Os testes concorrentes de S2 usam conexões separadas e sincronização controlada no PostgreSQL para incluir o writer de snapshot, sem depender de atrasos arbitrários.

Gates oficiais são os de `AGENTS.md`, com integração separada obrigatória; executar quality-gate completo no estado final. A suíte implantada de `docs/dev-verification.md` continua complementar e só pode ser acionada por autorização operacional específica. Esta change não a exige nem a executa.

## Risks / Trade-offs

- [Primeiro setor observado pode ser incompleto] → Rótulo com ajuda, recorte por episódio e fallback explícito; sem prometer reconstrução do percurso real.
- [Censo e catálogo de internações defasados] → Bloquear escrita sem episódio único e não confundir ausência com saída confirmada; contato com administrador.
- [Superusuário contorna permissões comuns] → Verificação estrutural de grupo, testes de endpoints e admin sem CRUD de pendências/versões.
- [Concorrência edição/saída e perda de versão] → Ordem de locks, token de versão, snapshots na mesma transação e testes PostgreSQL.
- [Consolidação legada concorre com cadastro] → Guarda sequencial antes de alterações e FKs protegidas; corrida residual pode abortar a operação perdedora, com propagação da falha e rollback sem perda ou transferências parciais. Provar intercalação em S1 e atomicidade por item do snapshot em S2.
- [Histórico contém conteúdo clínico sensível] → Banco autenticado, escaping/cache adequados, nenhum payload em logs/evidências, XLSX efêmero e somente dados sintéticos em desenvolvimento.
- [Lista cresce e causa N+1] → Queries em lote, paginação por unidade de visualização e histórico sob demanda; testes comparativos de orçamento de consultas.
- [Cópias de assets de teste envelhecem] → Fixar as mesmas versões do shell, preservar licença e limitar seu uso aos cenários reais da feature.

## Migration Plan

1. Criar migrations aditivas das três tabelas e bootstrap idempotente de Outro/grupo; sem semear pendências de pacientes nem associar usuários.
2. Instalar código compatível com o novo inventário de relações e guarda legada junto com o schema. Não publicar slices intermediários: todos os fluxos de saída devem estar integrados antes de habilitar o uso operacional.
3. Administrador associa usuários ao grupo e cadastra tipos pelo admin depois da publicação autorizada; nenhuma conta real ou dado operacional é necessário para implementar/verificar a change.
4. Rollback de código exige desabilitar acesso à feature e preservar as novas tabelas e histórico; não recomendar unapply destrutivo de migrations depois que houver dados. Um rollback operacional com escrita já ocorrida requer decisão explícita, não exclusão automática de evidência.
5. O planejamento não executa migrations, deploy, mudanças de grupo no banco ativo, archive ou publicação.

## Revisão incorporada

Correções autorizadas após a revisão independente de Muse Wonder/max. O relatório original é `/tmp/sirhosp-pending-items-muse-wonder-review-max.md`; os contratos abaixo permanecem reconstruíveis sem depender desse arquivo temporário.

| Finding | Tratamento no plano                                                                                                                                                              |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P1-1    | D5 e PI-07: estado fechado resultante, incluindo canônica já fechada, fim da duplicata e ativas residuais em `already_reconciled`; evidências em S2.                             |
| P1-2    | D5 e PI-07: snapshot atômico por item, identidade revalidada sob lock, falha propagada com itens anteriores preservados; evidências em S2.                                       |
| P2-1    | D3/PP-02: resolver conservador único para leitura atual, métricas, XLSX e escrita; duplicidade equivalente sem contagem dupla e conflitos excluídos.                             |
| P2-2    | PI-02/S1: proteger Outro de rename/delete, inclusive sem referências, e testar tipos em uso.                                                                                     |
| P2-3    | D6/S1: corrida residual documentada como falha conservadora e coberta por intercalação/rollback, sem prometer serialização inexistente.                                          |
| P2-4    | D8/PP-09/S1/S3/S4: diretivas de cache explícitas e assertions HTTP.                                                                                                              |
| P2-5    | D9/S1: harness mínimo antes do RED de produto, com interceptação CDN para assets reais locais versionados.                                                                       |
| P2-6    | Task 5.1: falha global de Markdown continua impedindo aceite; separar evidência focada do baseline, sem flexibilizar `AGENTS.md` ou alterar entradas do usuário sem autorização. |

Esta atualização não representa nova revisão independente nem aprovação dos slices para implementação.

## Estado de aprovação

Requisitos de produto consolidados das respostas do usuário; proposta técnica e slices ainda sujeitos à revisão/aprovação. Não há pergunta de produto bloqueadora pendente. Detalhes de apresentação que não alterem os contratos podem ser refinados na implementação; mudanças de comportamento, persistência ou escopo exigem escalada conforme `AGENTS.md`.
