# API de leitura upstream do SIRHOSP

Contrato de consumo dos dois endpoints de leitura que o SIRHOSP expõe para
sistemas internos: a foto atual dos pacientes internados e a demografia por
prontuário. Os dois endpoints são `GET`, somente leitura, autenticados por
Bearer token estático e servidos apenas em rede interna.

O modelo de consumo é **polling com deduplicação pelo par (`captured_at`,
`cycle_seq`)**: não há webhook, push, cursor, paginação por lotes ou histórico
de fotos.

Este documento é a referência do time consumidor e do operador do SIRHOSP.
Ele não contém credenciais, endereços reais nem nomes de sistemas da origem; o
token é entregue por canal privado do operador, nunca por este arquivo.

## 1. Visão geral e escopo de uso

| Item         | Valor                                                                  |
| ------------ | ---------------------------------------------------------------------- |
| Endpoints    | `GET /api/v1/inpatients/current` e `GET /api/v1/patients/{prontuario}` |
| Autenticação | `Authorization: Bearer <token>`                                        |
| Formato      | `application/json; charset=utf-8`                                      |
| Cache        | `Cache-Control: no-store` em toda resposta                             |
| Modelo       | polling (sugestão: a cada 2 h)                                         |
| Escrita      | nenhuma: os endpoints nunca criam, alteram ou removem dados            |
| Rede         | interna apenas; sem CORS público                                       |

O caso de uso previsto é acompanhar **pacientes internados há mais de 4–6 h**
(gestão, qualidade, jurídico, gestão de prontuários). Consequências aceitas por
design:

- internações mais curtas que o intervalo de polling podem nunca aparecer em
  uma foto;
- não há backfill: uma foto não lida durante uma indisponibilidade do
  consumidor se perde (a foto seguinte já é outra);
- a origem roda ciclos sequenciais, sem horário fixo (12–14 ciclos a cada 24 h),
  então o intervalo entre fotos novas varia.

## 2. Autenticação

Toda chamada precisa de `Authorization: Bearer <token>`. O token é estático,
aleatório, com no mínimo 32 bytes, e é comparado pelo servidor em tempo
constante.

| Situação                                                               | Resposta                                                                   |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Cabeçalho ausente, esquema diferente de `Bearer` ou token desconhecido | `401` com código `unauthorized`                                            |
| Token do servidor não configurado no deploy (falha fechada)            | `500` com código `internal_error`, com precedência sobre os casos de `401` |
| Token válido                                                           | prossegue para o recurso pedido                                            |

Regras para o consumidor:

- envie o token **apenas** no cabeçalho `Authorization`; nunca em query string,
  corpo ou parâmetro de URL;
- não registre o token em log da aplicação consumidora nem em arquivos
  versionados;
- trate `401` como falha de configuração do seu lado (token revogado, ausente
  ou errado): não faça retry em laço, acione o operador;
- trate `500` como indisponibilidade temporária: faça backoff e tente na
  próxima janela de polling.

## 3. Preparação do cliente

O operador entrega o token por canal privado. Grave-o em um arquivo privado do
usuário que executará o polling (permissão `600`), por exemplo em
`$HOME/.config/sirhosp/upstream-token`, e não em variável de ambiente
exportada em arquivo de perfil compartilhado.

Crie o diretório com permissão restrita:

```bash
mkdir -p "$HOME/.config/sirhosp" && chmod 700 "$HOME/.config/sirhosp"
```

Salve o token recebido em `$HOME/.config/sirhosp/upstream-token` com permissão
`600`. Depois, no shell que fará as chamadas, carregue o token e o endereço
interno do SIRHOSP:

```bash
export SIRHOSP_UPSTREAM_TOKEN="$(cat "$HOME/.config/sirhosp/upstream-token")"
export BASE_URL="http://127.0.0.1:8000"
```

O valor acima é um exemplo local. Em produção, `BASE_URL` deve ser o endereço
interno entregue pelo operador (sem barra final).

## 4. Foto atual dos internados

`GET /api/v1/inpatients/current` devolve a última foto de censo **concluída**
do SIRHOSP:

- a foto corresponde integralmente a um ciclo concluído; ciclos em andamento,
  falhos ou enfileirados nunca aparecem, e duas fotos nunca são misturadas;
- todas as linhas de uma foto compartilham o mesmo `captured_at`;
- cada foto traz `cycle_seq`, o número de sequência do ciclo servido (inteiro,
  estritamente crescente); o par (`captured_at`, `cycle_seq`) identifica a foto
  sem depender de relógio;
- apenas linhas de paciente são listadas (`prontuario` não vazio);
- a ordem é estável entre polls (setor, código de setor, leito, prontuário),
  então o mesmo estado de banco devolve payload idêntico;
- `row_count` é igual ao tamanho de `patients`.

### 4.1 Forma da resposta

```json
{
  "captured_at": "2026-09-06T13:00:00+00:00",
  "cycle_seq": 414,
  "row_count": 3,
  "patients": [
    {
      "setor_codigo": "640",
      "setor": "CLINICA MEDICA",
      "leito": "I10CA",
      "prontuario": "0000001",
      "nome": "PACIENTE EXEMPLO",
      "bed_status": "occupied",
      "especialidade": "CIV",
      "source_admission_at": "2026-09-05T17:30:00+00:00",
      "source_movement_at": null
    }
  ]
}
```

O exemplo acima usa dados sintéticos. Uma foto com vários pacientes repete o
objeto de `patients` uma vez por linha. O offset exibido é o que a stack atual
emite (`+00:00`); o fuso do consumidor é aplicado no lado dele.

Campos de topo, além de `patients`:

| Campo         | Tipo     | Regra                                                           |
| ------------- | -------- | --------------------------------------------------------------- |
| `captured_at` | ISO 8601 | início do ciclo capturado; identidade de relógio da foto        |
| `cycle_seq`   | inteiro  | sequência do ciclo servido; estritamente crescente entre ciclos |
| `row_count`   | inteiro  | igual ao tamanho de `patients`                                  |

`cycle_seq` nunca é derivado de timestamp: ele é a sequência do próprio ciclo
servido, então ordene e deduplique pelo par (`captured_at`, `cycle_seq`). Ele é
opaco — não deduza dele nada além da ordem entre ciclos servidos.

### 4.2 Campos de cada linha

Todos os campos vêm do registro de censo sem transformação de negócio; a
normalização de valores é responsabilidade do consumidor.

| Campo                 | Tipo               | Regra                                                                           |
| --------------------- | ------------------ | ------------------------------------------------------------------------------- |
| `setor_codigo`        | string             | código do setor; **repete entre setores distintos**                             |
| `setor`               | string             | descrição do setor; **identidade de setor é o par (`setor_codigo`, `setor`)**   |
| `leito`               | string             | identificador do leito; pode ser vazio (a origem lista pacientes sem leito)     |
| `prontuario`          | string             | chave do paciente; nunca vazio nas linhas devolvidas                            |
| `nome`                | string             | nome do paciente; nunca vazio nas linhas devolvidas                             |
| `bed_status`          | enum               | `occupied`, `empty`, `maintenance`, `reserved` ou `isolation`                   |
| `especialidade`       | string             | informativa; pode ser vazia                                                     |
| `source_admission_at` | ISO 8601 ou `null` | início da internação na origem; `null` quando a origem informou apenas a data   |
| `source_movement_at`  | ISO 8601 ou `null` | última movimentação na origem; `null` quando não há hora ou não há movimentação |

Todo timestamp vem com offset explícito (`Z` ou `±HH:MM`); na stack atual o
servidor emite `+00:00`, então converta para o fuso local ao exibir. Nunca há
timestamp sem fuso.

Regras obrigatórias que o consumidor pode assumir:

- **nunca há meia-noite fabricada**: se a origem informou apenas a data de
  internação, `source_admission_at` é `null`; nunca `00:00` sintético;
- setores que reaproveitam o mesmo `setor_codigo` permanecem distinguíveis pelo
  par com `setor`; não colapse setores por código isolado;
- uma linha de paciente sem nome faz o servidor recusar a foto inteira com
  `500 internal_error`; o servidor nunca omite a linha nem inventa um nome.

### 4.3 Chamadas de exemplo

Código de status e cabeçalhos:

```bash
curl -sS -D - -o /dev/null \
  -H "Authorization: Bearer $SIRHOSP_UPSTREAM_TOKEN" \
  "$BASE_URL/api/v1/inpatients/current"
```

Corpo completo, formatado (útil para inspeção manual):

```bash
curl -sS \
  -H "Authorization: Bearer $SIRHOSP_UPSTREAM_TOKEN" \
  "$BASE_URL/api/v1/inpatients/current" \
  | python3 -m json.tool | sed -n '1,40p'
```

Leitura com Python padrão (sem dependências externas):

```bash
python3 - <<'PY'
import json
import os
import urllib.error
import urllib.request

request = urllib.request.Request(
    f"{os.environ['BASE_URL']}/api/v1/inpatients/current",
    headers={"Authorization": f"Bearer {os.environ['SIRHOSP_UPSTREAM_TOKEN']}"},
)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        photo = json.load(response)
except urllib.error.HTTPError as error:
    if error.code != 404:
        raise
    print("sem foto concluída ainda (404 no_snapshot)")
    raise SystemExit(0)

print("captured_at:", photo["captured_at"])
print("cycle_seq:", photo["cycle_seq"])
print("row_count:", photo["row_count"])
if photo["patients"]:
    print("primeira linha:", json.dumps(photo["patients"][0], ensure_ascii=False))
else:
    print("primeira linha: nenhuma (censo concluído sem pacientes)")
PY
```

## 5. Demografia por prontuário

`GET /api/v1/patients/{prontuario}` devolve o registro demográfico do paciente
cujo prontuário é `patient_source_key` na origem oficial do pipeline. A
resolução é restrita a essa origem: um prontuário que exista apenas em outra
origem não é servido.

- o `prontuario` consultado é ecoado no corpo;
- escalares são espelhados literalmente: string vazia continua string vazia e
  `null` permanece `null`;
- campos aninhados: `phones` e `address`;
- `gender` chega como texto livre em português, conforme o banco;
- `updated_at` permite decidir se vale atualizar a cópia local;
- prontuário inexistente responde `404` com código `patient_not_found`.

A resposta contém **exatamente** estas 19 chaves de topo: `prontuario`,
`name`, `social_name`, `date_of_birth`, `gender`, `gender_identity`,
`mother_name`, `father_name`, `race_color`, `birthplace`, `nationality`,
`marital_status`, `education_level`, `profession`, `cns`, `cpf`, `phones`,
`address`, `updated_at`. Nenhum campo interno do modelo é exposto.

O corpo tem esta forma (dados sintéticos):

```json
{
  "prontuario": "0000001",
  "name": "PACIENTE EXEMPLO",
  "social_name": "NOME SOCIAL EXEMPLO",
  "date_of_birth": "1980-03-17",
  "gender": "Masculino",
  "gender_identity": "Cisgenero",
  "mother_name": "MAE EXEMPLO",
  "father_name": "PAI EXEMPLO",
  "race_color": "Parda",
  "birthplace": "Salvador",
  "nationality": "Brasileira",
  "marital_status": "Solteiro",
  "education_level": "Superior completo",
  "profession": "Analista",
  "cns": "898000000000000",
  "cpf": "00000000000",
  "phones": {
    "home": "7133334444",
    "cellular": "71999998888",
    "contact": "7132221111"
  },
  "address": {
    "street": "RUA EXEMPLO",
    "number": "100",
    "complement": "APTO 12",
    "neighborhood": "CENTRO",
    "city": "SALVADOR",
    "state": "BA",
    "postal_code": "40000000"
  },
  "updated_at": "2026-09-06T13:00:00+00:00"
}
```

`date_of_birth` é data civil (`YYYY-MM-DD`) ou `null`; `updated_at` é ISO 8601
com offset explícito (`+00:00` na stack atual).

### 5.1 Chamadas de exemplo

```bash
curl -sS \
  -H "Authorization: Bearer $SIRHOSP_UPSTREAM_TOKEN" \
  "$BASE_URL/api/v1/patients/0000001" \
  | python3 -m json.tool
```

Verificação do key-set exato com Python padrão:

```bash
python3 - <<'PY'
import json
import os
import urllib.request

request = urllib.request.Request(
    f"{os.environ['BASE_URL']}/api/v1/patients/0000001",
    headers={"Authorization": f"Bearer {os.environ['SIRHOSP_UPSTREAM_TOKEN']}"},
)
with urllib.request.urlopen(request, timeout=30) as response:
    record = json.load(response)

print("total de chaves:", len(record))
print("chaves:", ",".join(sorted(record)))
print("date_of_birth:", record["date_of_birth"])
print("updated_at:", record["updated_at"])
PY
```

Prontuário inexistente (código de status e corpo do erro):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $SIRHOSP_UPSTREAM_TOKEN" \
  "$BASE_URL/api/v1/patients/0999999"
```

```bash
curl -sS \
  -H "Authorization: Bearer $SIRHOSP_UPSTREAM_TOKEN" \
  "$BASE_URL/api/v1/patients/0999999"
```

## 6. Algoritmo de polling e deduplicação

O par (`captured_at`, `cycle_seq`) é a **identidade da foto**. O algoritmo de
referência é:

1. faça `GET /api/v1/inpatients/current` na janela de polling (sugestão: 2 h);
2. guarde o último par (`captured_at`, `cycle_seq`) processado e o conjunto de
   prontuários daquela foto, de forma persistente no seu lado;
3. se o par recebido for igual ao último processado, não faça nada
   (**no-op**: é a mesma foto);
4. se for diferente, publique a nova presença e derive chegadas e partidas
   comparando com o conjunto anterior;
5. grave o novo par e o novo conjunto somente depois de processar a foto com
   sucesso, para não perder uma foto em caso de falha local.

Regras associadas:

- **desempate por `cycle_seq`**: o servidor nunca mistura duas fotos. Se dois
  ciclos distintos compartilharem o mesmo `captured_at` (evento teórico), cada
  um tem `cycle_seq` próprio, e o mais recente é o de maior `cycle_seq`.
  Comparar apenas `captured_at` descarta essa segunda foto; comparar o par não;
- **`cycle_seq` é opaco e crescente**: ele nunca reusa valor e nunca volta
  atrás. Não deduza dele nada além da ordem entre ciclos servidos;
- **`404 no_snapshot`**: significa "ainda não existe ciclo concluído com
  linhas", não "censo vazio". Trate como ausência de dado (tente no próximo
  poll) e alerte se persistir por muitas horas;
- **foto vazia** é válida: `200` com `patients: []` e `row_count: 0` significa
  "ciclo concluído, nenhum paciente internado";
- **staleness**: `now - captured_at` grande indica origem sem ciclo novo; não é
  erro do endpoint.

Implementação de referência do polling com deduplicação, em Python padrão:

```bash
python3 - <<'PY'
import json
import os
import pathlib
import urllib.error
import urllib.request

state_path = pathlib.Path("/tmp/sirhosp-upstream-photo.json")
request = urllib.request.Request(
    f"{os.environ['BASE_URL']}/api/v1/inpatients/current",
    headers={"Authorization": f"Bearer {os.environ['SIRHOSP_UPSTREAM_TOKEN']}"},
)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        photo = json.load(response)
except urllib.error.HTTPError as error:
    if error.code != 404:
        raise
    print("NO-OP: sem foto concluída ainda (404 no_snapshot)")
    raise SystemExit(0)


def processar_foto(captured_at, cycle_seq, prontuarios, anteriores):
    """Troque este corpo pelo processamento real da foto.

    A regra 4 vive aqui: publique a nova presença e derive chegadas e partidas
    comparando com o conjunto anterior. Se este passo levantar exceção, o
    estado não é gravado e a foto volta no próximo poll.
    """
    chegadas = sorted(set(prontuarios) - set(anteriores or []))
    partidas = sorted(set(anteriores or []) - set(prontuarios))
    print(
        "PROCESSADA:",
        captured_at,
        "ciclo",
        cycle_seq,
        "chegadas",
        chegadas,
        "partidas",
        partidas,
    )


seen = json.loads(state_path.read_text()) if state_path.exists() else None
captured_at = photo["captured_at"]
cycle_seq = photo["cycle_seq"]
# Estado gravado por uma versão anterior deste guia não tem `cycle_seq`: nesse
# caso a primeira execução reprocessa a foto uma vez e regrava o par completo.
identidade_vista = None if seen is None else (seen["captured_at"], seen.get("cycle_seq"))

if identidade_vista == (captured_at, cycle_seq):
    print(
        "NO-OP: foto já processada",
        captured_at,
        "ciclo",
        cycle_seq,
        "linhas",
        len(seen["prontuarios"]),
    )
else:
    prontuarios = sorted(row["prontuario"] for row in photo["patients"])
    anteriores = seen["prontuarios"] if seen is not None else None
    processar_foto(captured_at, cycle_seq, prontuarios, anteriores)
    # regra 5: só depois do processamento bem-sucedido o novo estado é gravado
    state_path.write_text(
        json.dumps(
            {
                "captured_at": captured_at,
                "cycle_seq": cycle_seq,
                "prontuarios": prontuarios,
            }
        )
    )
    primeiro = prontuarios[0] if prontuarios else "nenhum"
    print(
        "NOVA:",
        captured_at,
        "ciclo",
        cycle_seq,
        "linhas",
        len(prontuarios),
        "primeiro",
        primeiro,
    )
PY
```

Execute o bloco acima duas vezes seguidas para observar `NOVA:` na primeira
execução e `NO-OP:` na segunda, sem mudança de estado no servidor.

## 7. Códigos de erro

Toda resposta de erro usa o envelope único:

```json
{
  "error": {
    "code": "unauthorized",
    "message": "Missing or invalid credentials."
  }
}
```

| Código              | HTTP | Quando acontece                                                                                             | O que fazer                                   |
| ------------------- | ---- | ----------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| `unauthorized`      | 401  | credencial ausente, esquema diferente de `Bearer` ou token desconhecido                                     | corrigir/renovar o token; não repetir em laço |
| `patient_not_found` | 404  | prontuário inexistente na origem oficial                                                                    | tratar como paciente não encontrado           |
| `no_snapshot`       | 404  | nenhum ciclo de censo concluído com linhas disponível                                                       | tentar no próximo poll                        |
| `bad_request`       | 400  | reservado para requisição inválida; na stack atual requisições malformadas são recusadas antes da aplicação | corrigir a chamada                            |
| `internal_error`    | 500  | falha interna, linha de paciente inválida na origem ou token não configurado no servidor                    | backoff; se persistir, acionar o operador     |

Garantias do envelope: corpo JSON com exatamente `code` e `message`, nenhum
stack trace, nenhum detalhe interno, e `Cache-Control: no-store` em toda
resposta (inclusive nos erros). O `500` de linha inválida é intencional: é
melhor falhar a foto inteira do que publicar um censo com paciente sem nome.

Chamada sem credencial (esperado `401`):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE_URL/api/v1/inpatients/current"
```

## 8. Contrato operacional

Esta seção registra o que o operador do SIRHOSP garante sobre exposição,
compatibilidade e limites. Ela vale para os dois composes suportados.

### 8.1 Rede interna e responsabilidade do proxy

- A API nunca deve ser exposta à internet nem a redes de terceiros. O acesso é
  restrito à rede interna onde o consumidor autorizado já opera.
- **Compose hospitalar** (`compose.hospital.yml`): a publicação da porta do
  serviço `web` usa `${SIRHOSP_BIND_ADDRESS}:${DJANGO_PORT}:8000`. O valor de
  `SIRHOSP_BIND_ADDRESS` deve ser restrito ao endereço da interface interna do
  servidor (ou `127.0.0.1` quando houver proxy local). O default `0.0.0.0`
  publica em todas as interfaces e só é aceitável atrás de firewall do
  operador.
- **Compose de produção genérico** (`compose.prod.yml`): a porta publicada não
  tem restrição de endereço própria. A restrição é responsabilidade do
  operador, via firewall do host ou reverse proxy com allowlist de origem.
- **Verificação por compose**: depois de qualquer mudança de exposição, o
  operador confirma (a) que a porta está publicada apenas no endereço
  pretendido e (b) que um cliente da rede autorizada recebe resposta da API
  (probe de alcance). Um cliente fora da rede autorizada deve receber conexão
  recusada ou timeout, nunca `401`.
- **Responsabilidade do proxy**, quando existir: terminar TLS, aplicar
  allowlist de origem, preservar o cabeçalho `Authorization`, não armazenar em
  cache (a API já responde `no-store`), aplicar timeouts de leitura compatíveis
  com o tamanho do payload e **não registrar** caminho completo, query string
  ou cabeçalho de autorização em log de acesso.
- A API em si não faz rate limit, allowlist de IP nem autenticação mútua nesta
  versão: essas barreiras pertencem ao perímetro acima.

### 8.2 Disciplina aditiva do contrato

- Campos novos **podem** aparecer em linhas, em objetos aninhados ou no corpo
  sem nova versão de endpoint. O consumidor deve ignorar chaves desconhecidas.
- Remoção, renomeação ou mudança de significado de campo existente exige nova
  change aprovada no SIRHOSP e comunicação prévia ao consumidor; isso não
  acontece silenciosamente.
- O key-set exato vale apenas para a demografia hoje: as 19 chaves listadas são
  o contrato atual, e qualquer ampliação segue a regra aditiva acima.
- Valores de negócio não são normalizados pelo SIRHOSP. Enum de gênero, listas
  de telefone e mapeamento de ausência são responsabilidade do consumidor.

### 8.3 Escopo temporal e lacunas aceitas

- Caso de uso suportado: pacientes internados há mais de 4–6 h; polling
  sugerido de 2 h.
- Lacunas aceitas por design: internações mais curtas que o intervalo de
  polling, fotos perdidas durante indisponibilidade do consumidor e ausência de
  backfill histórico.
- Não há garantia de horário fixo de ciclo: a origem roda 12–14 ciclos por dia,
  sequenciais.

## 9. Runbook do operador: token, go-live e rotação

### 9.1 Gerar o token

Gere um token aleatório com no mínimo 32 bytes (o comando abaixo gera 48 bytes
em base64 URL-safe):

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Grave o valor em `SIRHOSP_UPSTREAM_API_TOKEN` no arquivo de ambiente do deploy
(permissão `600`) e entregue ao consumidor por canal privado. Não versione o
valor, não o envie por e-mail comum e não o registre em ticket.

### 9.2 Go-live

1. grave `SIRHOSP_UPSTREAM_API_TOKEN` no ambiente do serviço `web` do deploy e
   recrie/religue esse serviço conforme o runbook de deploy;
2. confirme `401` sem credencial (probe abaixo);
3. confirme `200` com o token correto;
4. confirme a exposição de rede conforme a seção 8.1.

### 9.3 Verificação pós-deploy

Sem credencial (esperado `401`):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE_URL/api/v1/inpatients/current"
```

Com o token entregue (esperado `200`):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $SIRHOSP_UPSTREAM_TOKEN" \
  "$BASE_URL/api/v1/inpatients/current"
```

### 9.4 Rotação

A rotação não tem janela de dois tokens: o token novo substitui o anterior.

1. gere o token novo (seção 9.1) e grave-o no ambiente do `web`;
2. recrie/religue o serviço `web` conforme o runbook de deploy;
3. confirme `200` com o token novo (seção 9.3);
4. confirme `401` com o token anterior (comando abaixo) e comunique formalmente
   o horário da rotação ao consumidor;
5. remova o token anterior de qualquer cópia local sua.

Token revogado (esperado `401`):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer token-revogado" \
  "$BASE_URL/api/v1/inpatients/current"
```

### 9.5 Rollback

Remover `SIRHOSP_UPSTREAM_API_TOKEN` do ambiente e religar o `web` desliga a
API de forma fechada: toda chamada responde `500 internal_error`, nunca `200`
sem autenticação. Não existe migração de dados em nenhuma direção.

## 10. Privacidade e logs

- O log de acesso do servidor registra, para `/api/v1/`, apenas método, rota
  normalizada (`/api/v1/inpatients/current` ou
  `/api/v1/patients/<prontuario>`) e código de status. Query strings, caminhos
  desconhecidos e identificadores não são registrados; erros internos saem como
  registro genérico ou não saem.
- Erros internos nunca devolvem stack trace, caminho de arquivo ou detalhe de
  banco no corpo da resposta.
- `Cache-Control: no-store` impede cache intermediário de dado clínico.
- O consumidor deve aplicar a mesma disciplina: não registrar payload, nome ou
  prontuário em log de aplicação, e não persistir a foto além do necessário
  para o processamento.

## 11. Fora de escopo nesta versão

Nada desta seção está disponível hoje; não implemente dependência sobre estes
itens:

- `?include_empty_beds`: mapa de leitos vazios (extensão futura, sem data);
- histórico ou backfill de fotos, cursor e paginação;
- webhook/push: o modelo é polling;
- qualquer escrita: não há `POST`, `PUT`, `PATCH` ou `DELETE`;
- rate limit, allowlist de IP e autenticação assimétrica/mútua no endpoint;
- histórico de internações e enriquecimento de identidade de episódio (v2);
- dados de laboratório/exames (canal próprio do consumidor).

## 12. Referências de implementação

- Código: `apps/upstream_api/` (`urls.py`, `views.py`, `auth.py`, `errors.py`,
  `photo.py`, `demographics.py`, `access_log.py`).
- Configuração: `SIRHOSP_UPSTREAM_API_TOKEN` em `config/settings.py` e nos
  composes de produção/hospitalar.
- Contrato verificado por testes: `tests/unit/test_upstream_api_*.py` e
  `tests/integration/test_upstream_api_*.py`.
