# Change Proposal: sirhosp-upstream-api-v1

## Why

O projeto hgproxy (espelho hospitalar com API de leitura autenticada) precisa da
lista de pacientes internados e da demografia, dados que o sirhosp já extrai do
sistema legado de forma contínua (ciclos sequenciais, 12–14 a cada 24 h). Hoje o
hgproxy lê a tela de censo da origem diretamente, duplicando scraping contra um
sistema lento e frágil. Expor esses dados via API autenticada elimina a
duplicação, reduz carga na origem e entrega ao consumidor dados já normalizados
e auditados pelo pipeline do sirhosp. Valor operacional: gestão, qualidade,
jurídico e gestão de prontuários passam a ter um segundo consumidor
institucional dos mesmos dados clínicos já governados, sem nenhuma nova
extração do legado e sem ampliar a superfície de scraping.

## What Changes

- Criar um app Django isolado que expõe 2 endpoints GET read-only sob
  `/api/v1/`: foto atual dos internados e demografia por prontuário.
- Autenticar com `Authorization: Bearer <token>` (token estático via env,
  ligado aos composes de produção); sem token ou token inválido responde
  `401`, e sem setting configurado tudo responde `500` (fail-closed com
  precedência). Isentar `/api/v1/` dos middlewares orientados a browser
  (CSRF e troca forçada de senha).
- Servir a foto a partir do último ciclo de censo concluído
  (`status = succeeded`), nunca de ciclo parcial ou falho.
- Expor `cycle_seq` monotônico na foto (v1.1, aditivo, a pedido do
  consumidor hgproxy como chave de dedupe independente de relógio).
- Espelhar `CensusSnapshot` e `Patient` 1:1 no JSON, sem transformar valores
  de negócio (normalizações ficam no consumidor).
- Padronizar erros (`401`/`404`/`400`/`500`), timestamps ISO 8601 com offset
  e `Cache-Control: no-store`.
- Sanitizar logs para nunca registrar nome ou prontuário (R8, opção 1:
  enforcement no logging, não só documentação).
- Entregar testes automatizados e documentação com exemplos para o time
  consumidor.

## Non-Goals

- Nenhum endpoint de escrita; o consumidor só faz `GET`.
- Nenhum webhook/push; o modelo é polling.
- Nenhum dado de laboratório/exames (canal próprio do consumidor).
- Nenhum histórico ou backfill de fotos (só a foto atual; `captured_at` é a
  identidade para deduplicação).
- Nenhum mapa de leitos vazios (`?include_empty_beds` fica como extensão
  futura).
- Nenhum rate limit, allowlist de IP ou autenticação assimétrica no v1.
- Nenhuma mudança na extração, nos modelos existentes, no comportamento
  do portal ou no desenho da infra (adições limitadas: 1 allowlist, 1 env
  var por compose, 1 logger; sem migration, sem DRF/ninja, sem Celery/Redis).

## Capabilities

### New Capabilities

- `upstream-read-api`: API JSON read-only autenticada que expõe a foto atual
  dos internados e a demografia por prontuário para sistemas consumidores
  internos, com erros padronizados e logs sem dado clínico.

### Modified Capabilities

Nenhuma. Nenhum requisito de spec existente muda; extração, persistência e
portal seguem intactos.

## Impact

- Código novo isolado em um app; nenhuma alteração em extração, modelos
  existentes, comportamento do portal ou workers.
- Nova variável operacional (`SIRHOSP_UPSTREAM_API_TOKEN`) com entrega do
  token por canal privado; ausência do setting falha fechado.
- Carga trivial (polling a cada 2 h + dezenas de demografias/dia); sem
  impacto em banco ou workers.
- Superfície de PHI passa a incluir um segundo sistema consumidor, mitigada
  por rede interna, Bearer token e logs sanitizados.

## Risks

- **Exposição de PHI a outro sistema**: dados nominais passam a trafegar para
  o hgproxy. Mitigação: rede interna apenas, token longo, `no-store`,
  sanitização de logs e contrato aditivo (nunca ampliar campos sem change).
- **Staleness e invisibilidade de internações curtas**: polling a cada 2 h
  perde estadias mais curtas e fotos durante indisponibilidade do consumidor.
  Aceito por design para o caso de uso (pacientes há mais de 4–6 h).
- **Colisão teórica de `captured_at` entre runs**: faria o consumidor pular
  uma foto no dedup. Aceito como desprezível (timestamp com microssegundos
  e ciclos de horas); tie-break determinístico documentado em D3.
- **Vazamento de token ou log com PHI**: mitigado por fail-closed sem setting,
  comparação em tempo constante e logger sanitizado com teste dedicado.
