## Context

Ver `proposal.md` para a motivação. O change anterior entregou dois units de
estatísticas desabilitados e um runbook que bloqueia sua instalação enquanto
eles não forem assets da release. O workflow atual já cria um draft completo
antes de publicar a imagem e distribui o scheduler e seis units das cadências de
saída, mas não inclui o novo par nem um verificador de ativação.

O host hospitalar opera a partir de `/srv/apps/prisma`, release imutável, Compose
standalone e systemd. O scheduler já emite marcadores agregados
`mode=<modo> result=<estado>`; seu sucesso D-1 significa que o comando canônico
de quatro extratores terminou com código zero. Logs completos não podem virar
artefato porque podem conter identidade clínica.

## Goals / Non-Goals

**Goals:**

- publicar preflight e units de estatísticas no draft da mesma tag validada;
- provar procedência local, fronteira futura e frescor das cadências sem mutar o
  host;
- fornecer saída pequena, agregada e apta a revisão humana;
- manter instalação, evidência e ativação como checkpoints independentes.

**Non-Goals:**

- habilitar ou iniciar qualquer unit automaticamente;
- executar extração, materialização, backfill ou consulta clínica;
- criar uma nova plataforma de observabilidade ou persistir evidência no banco;
- mudar calendários, locks ou contratos das cadências existentes;
- contornar falha de evidência por override operacional.

## Decisions

### 1. Publicar o conjunto completo no draft imutável

O array de assets do workflow incluirá:

- `deploy/daily-statistics-activation-preflight.sh`;
- `deploy/systemd/sirhosp-daily-statistics.service`;
- `deploy/systemd/sirhosp-daily-statistics.timer`.

A validação `test -f` ocorrerá antes de `gh release create`, junto aos assets já
existentes. Todos serão anexados na única criação do draft; nenhum passo editará
assets depois da publicação.

**Alternativa descartada:** orientar download do Git em produção. Isso rompe o
modelo sem checkout e perde a correspondência verificável entre imagem, Compose
e runtime.

### 2. Usar preflight host-level em shell, somente leitura

O preflight rodará no host porque precisa consultar arquivos instalados,
`systemctl` e `journalctl`. Ele receberá uma tag exata, consultará a release no
GitHub, exigirá o indicador de imutabilidade, baixará os assets para diretório
temporário e comparará bytes com:

- scheduler e preflight sob `/srv/apps/prisma/deploy/`;
- services e timers relevantes sob `/etc/systemd/system/`.

Também exigirá `SIRHOSP_VERSION` igual à tag informada. Arquivos temporários
serão removidos por `trap`. Dependências host explícitas serão `bash`, `curl`,
`python3`, `cmp`, `systemctl` e `journalctl`.

**Alternativa descartada:** management command Django. Um container não observa
o systemd do host sem mounts/privilegios adicionais e acoplaria evidência de
host ao banco clínico.

### 3. Ler somente chaves allowlisted do `.env`

O script não fará `source` do `.env`. Ele extrairá apenas `SIRHOSP_VERSION` e
`STATISTICS_ACTIVATION_DATE`, recusará duplicidade ou sintaxe ambígua e nunca
imprimirá outras variáveis. A data será comparada com o dia corrente por
`TZ=America/Bahia` e deverá ser estritamente futura.

**Alternativa descartada:** carregar o arquivo inteiro no processo. Isso expõe
credenciais a expansão shell e aumenta o risco de vazamento acidental.

### 4. Provar cadências por configuração idêntica e marcador recente

O preflight exigirá que os timers upstream estejam `enabled` e `active`, que os
calendários instalados correspondam aos units da release e que existam os
marcadores exatos:

- `mode=hourly-discharges result=success` nas últimas duas horas;
- `mode=d1-recovery result=success` nas últimas trinta horas.

Consultas ao journal serão silenciosas e usadas somente como predicado. A saída
normalizada informará `PASS`/`FAIL`, modo e janela; não copiará `MESSAGE` nem
linhas brutas. A correspondência da imagem, scheduler e units à mesma release
liga o sucesso D-1 ao runtime canônico de `discharges`, `admissions`, `deaths` e
`official_census`.

**Alternativas descartadas:** aceitar apenas `active` do timer, que não prova
execução bem-sucedida; ou anexar trechos de journal, que pode persistir PHI.

### 5. Fazer o preflight falhar fechado e permanecer inerte

Qualquer dependência, asset, configuração, calendário, estado ou evidência
ausente produzirá código não zero e motivo técnico enumerado. O script não terá
comandos `enable`, `start`, `restart`, Docker ou Django. Ele exigirá que o timer
de estatísticas ainda esteja desabilitado e inativo para representar de fato um
checkpoint pré-ativação.

Testes executarão o script com diretórios e binários sintéticos controlados,
sem rede, Docker, systemd ou journal reais. Um teste estático bloqueará verbos
mutáveis e saída de conteúdo bruto.

**Alternativa descartada:** tentar corrigir automaticamente a falha. Remediação
automática confundiria diagnóstico com mudança de estado e eliminaria o gate
humano.

### 6. Registrar aceite humano fora do banco clínico

O runbook definirá uma saída agregada que o operador pode anexar ao ticket ou
registro de mudança da organização. O repositório não armazenará evidência real
do hospital. A ativação continuará sendo um comando manual posterior, somente
com preflight recém-aprovado; se a janela expirar, ele deverá ser repetido.

**Alternativa descartada:** criar modelo Django de aprovação. Isso adicionaria
persistência e UI sem necessidade para um checkpoint operacional raro.

## Risks / Trade-offs

- **Retenção curta do journal causa falso negativo** → falhar fechado e aguardar
  nova execução normal; nunca disparar extração apenas para satisfazer o gate.
- **Relógio incorreto invalida frescor** → usar timestamps do journal/systemd e
  documentar sincronização de hora como pré-condição.
- **GitHub indisponível bloqueia o preflight** → aceitar o bloqueio; cópia local
  não substitui prova de release imutável.
- **Contrato D-1 muda no futuro** → testes de integração continuam fixando os
  quatro extratores e o preflight exige runtime da mesma tag.
- **Comparação byte a byte reprova ajuste local legítimo** → alterações locais
  não são legítimas para runtime imutável; publicar nova tag.
- **Shell é menos estruturado que Python** → manter funções pequenas, saída
  allowlisted, `set -euo pipefail`, ShellCheck quando disponível e testes com
  doubles determinísticos.
- **As janelas de duas e trinta horas são conservadoras** → aumentam falso
  negativo, mas impedem ativação com evidência obsoleta.

## Migration Plan

1. Implementar e validar o preflight apenas com fixtures e command doubles.
2. Atualizar o workflow para anexar preflight e units ao draft e testar a
   atomicidade da publicação.
3. Atualizar o runbook com download pela tag exata, instalação desabilitada,
   preflight, aceite humano, ativação, observação e rollback.
4. Publicar uma nova tag pelo workflow existente; nenhuma release já publicada
   será alterada.
5. No hospital, baixar os assets da tag, instalar mantendo o timer desabilitado
   e executar o preflight.
6. Somente após aceite humano, habilitar o timer com data futura.
7. Em rollback, desabilitar/remover apenas os dois units de estatísticas; manter
   projeções, fontes clínicas e cadências upstream.
