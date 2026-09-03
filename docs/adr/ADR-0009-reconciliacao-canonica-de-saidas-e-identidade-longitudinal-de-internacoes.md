# ADR-0009: Reconciliação canônica de saídas e identidade longitudinal de internações

- **Status:** Proposta
- **Data:** 2026-09-03
- **Decisores:** Equipe SirHosp
- **Consultados:** Operação hospitalar, engenharia e segurança clínica
- **Informados:** Administradores e revisores clínicos autorizados

## Contexto

A ingestão histórica persiste registros de alta, mas hoje não garante que a
internação canônica seja encerrada. Em paralelo, a chave externa de internação
pode mudar entre consultas ao sistema legado. Tratar essa chave como identidade
clínica absoluta permite manter uma internação aberta residual e criar outra
fechada para o mesmo episódio.

A ausência no censo atual é um sinal operacional útil, mas não informa data ou
hora de saída e pode decorrer de extração incompleta. Os campos do relatório de
alta também têm significados distintos: `saida_em` representa a saída efetiva,
enquanto `alta_em` representa o registro do sumário médico.

A inspeção operacional também confirmou que os units de alta três vezes ao dia
existem somente no repositório: não estão instalados no servidor hospitalar. O
runtime ativo executa o orquestrador de censo e workers em
`/srv/apps/prisma/compose.hospital.yml`; a recuperação histórica tem sido manual.
O comando `process_discharge_pdf` não possui chamador programado e fabrica um
horário ausente da fonte.

A correção afeta identidade longitudinal, datas clínicas, indicadores e dados
históricos. Ela exige decisão arquitetural explícita, comportamento fail-closed,
auditoria permanente e operação reversível. O desenho detalhado está em
`openspec/changes/reconcile-patient-exits-and-stale-admissions/` e complementa a
ADR-0002 sem alterar sua decisão sobre eventos clínicos canônicos.

## Decisão

Adotar um reconciliador canônico de saídas e uma identidade longitudinal de
internação composta pelas seguintes regras:

1. `Admission.discharge_date` representa exclusivamente a saída efetiva.
   `DischargeRecord.saida_em`, fim confirmado no catálogo de internações ou
   óbito com data e hora completas podem encerrá-la. `alta_em`, data do PDF e
   ausência no censo nunca encerram diretamente uma internação.
2. A correspondência de episódio ocorre, em ordem, por chave externa atual,
   alias histórico, paciente com início exato e paciente com data local de
   início quando existe um único candidato. Ambiguidade não é resolvida por
   heurística.
3. Toda chave externa observada é preservada como alias da internação canônica.
   Uma fotografia fechada com chave alterada atualiza a internação aberta
   compatível quando a correspondência é única.
4. Duplicatas só são mescladas automaticamente após fotografia recente da fonte
   confirmar um único episódio. O registro mais antigo permanece canônico; o
   outro recebe `merged_into`, não é apagado e deixa de aparecer em consultas
   clínicas normais.
5. Reconciliações e merges são transacionais, idempotentes, auditados por tempo
   indeterminado e reversíveis quando o estado posterior ainda corresponde ao
   limite registrado pela operação.
6. Ausência em dois censos completos consecutivos, com intervalo mínimo de 30
   minutos, apenas cria trabalho de confirmação `admissions_only`. Reaparecimento
   cancela suspeita baseada somente no censo.
7. Filas, deduplicação e locks continuam no PostgreSQL; execução periódica usa
   management commands e systemd, sem cron paralelo. Não serão introduzidos
   Celery, Redis ou novo serviço.
8. Um timer systemd executa às 05:00 em `America/Bahia` a recuperação de D-1 com
   seleção explícita de `discharges`, `admissions`, `deaths` e
   `official_census`. Toda execução programada de automação da fonte usa o
   runner one-shot `historical_recovery` do Compose hospitalar, isolado por
   profile e nunca o serviço `web`. O timer é entregue desabilitado; runner,
   script e units acompanham a release imutável da mesma tag, porque o servidor
   hospitalar não possui clone do repositório.
9. Execuções programadas verificam fila de ingestão e lote de censo aberto
   antes de iniciar Playwright e saem com código fixo 75 indicando ocupação
   temporária; apenas esse código é retentado, a cada 10 minutos e no máximo
   seis vezes. Falha final de extrator não é retentada pelo agendador.
10. `process_discharge_pdf` fica inativo e falha antes de ler arquivo ou produzir
    efeitos. O comando e seu helper dedicado são candidatos a remoção após um
    ciclo de release sem chamadores estáticos ou operacionais.
11. Usuário e senha do sistema legado são transportados aos subprocessos apenas
    por ambiente escopado ao processo filho, nunca em argv; mensagens de erro
    nunca ecoam credenciais.
12. Backfill é dry-run por padrão, limitado, precedido por backup e benchmark e
    executado somente em operação posterior expressamente autorizada. Cada item
    recebe um UUID de operação e cada apply um UUID de lote; rollback de lote é
    atômico e validado integralmente antes de qualquer mutação.
13. `DailyDischargeCount` é derivado exclusivamente da saída efetiva canônica e
    tem o refresh de agregado como único escritor; a persistência de evidência
    de alta não escreve contagem nem `raw_data` com registros de pacientes.
14. Indicadores de saída usam `saida_em` em `America/Bahia`; indicadores de
    sumário permanecem separados e usam `alta_em`. Óbitos não são contados como
    altas hospitalares.
15. Identidade de paciente pode aparecer apenas em telas e CSV efêmero
    protegidos por permissão específica. Logs e métricas permanecem agregados.

## Consequências

### Positivas

- Uma única semântica passa a determinar o encerramento efetivo da internação.
- Mudanças de chave no legado deixam de produzir automaticamente episódios
  duplicados.
- O saneamento histórico pode reutilizar as mesmas regras idempotentes do fluxo
  online e passa a ter recuperação D-1 diária dos quatro extratores.
- O fluxo PDF inseguro deixa de concorrer com as fontes canônicas.
- Registros mesclados e valores anteriores permanecem rastreáveis e passíveis de
  reversão controlada.
- O censo ajuda a detectar lacunas sem se tornar fonte indevida de data clínica.
- Métricas operacionais distinguem saída física de criação do sumário médico.

### Negativas

- Serão necessários novos modelos, constraints, migrações e revisão dos pontos
  de consulta de Admission.
- A auditoria indefinida aumenta armazenamento e manutenção de índices.
- Casos ambíguos e óbitos sem hora permanecem pendentes para sincronização ou
  revisão manual.
- A ativação horária depende de benchmark e aumenta a disciplina operacional de
  timers, cooldowns e monitoramento.
- Credenciais deixam de ser auditáveis por argv e passam a exigir controle do
  ambiente do runner; inspeção de processo deixa de revelar segredos.
- A release imutável precisa empacotar Compose, script, units e runbook juntos,
  o que amplia o contrato de publicação.

### Riscos

- Uma relação não inventariada pode ficar ligada ao registro mesclado. Mitigação:
  inventário obrigatório, testes por relação e bloqueio do merge se houver tipo
  não suportado.
- Correspondência incorreta pode alterar data clínica. Mitigação: ordem fixa,
  unicidade, locks e comportamento fail-closed.
- Acesso excessivo ao legado pode degradar a fonte. Mitigação: benchmarks
  independentes para execução horária e catch-up de sete datas, cooldown,
  deduplicação, limite de 100 pacientes e timers inicialmente desabilitados.
- Sobreposição de execuções programadas pode competir por Playwright e pela
  fonte. Mitigação: locks distintos por job, verificação de fila/lote, código 75
  com retentativa limitada e defasagem entre timers; sobreposição manual
  residual permanece monitorada.
- Rollback após mutações posteriores pode ser inseguro. Mitigação: validar o
  estado posterior integral e falhar sem mutação.

## Alternativas consideradas

### Encerrar pela ausência no censo

Rejeitada porque o censo pode estar incompleto e não contém data e hora
confiáveis da saída.

### Usar `alta_em` como fallback

Rejeitada porque o registro do sumário médico e a saída efetiva são eventos
independentes.

### Manter a chave externa como identidade única do episódio

Rejeitada porque a fonte pode trocar essa chave no mesmo episódio, fato que
produz internações residuais.

### Apagar internações duplicadas

Rejeitada porque elimina rastreabilidade, dificulta a migração de relações e
fragiliza rollback.

### Manter o PDF como sinal complementar

Rejeitada porque o fluxo não possui agendamento ativo, imprime identidade e
fabrica um horário que não existe na fonte. XLS, catálogo de internações, óbitos
e suspeitas do censo fornecem cobertura em camadas sem essa ambiguidade.

### Introduzir fila externa

Rejeitada porque PostgreSQL, management commands e systemd atendem ao volume e
às restrições arquiteturais da fase atual.

## Referências

- [ADR-0002](ADR-0002-modelagem-canonica-eventos-clinicos-e-reconciliacao.md)
- [OpenSpec proposal](../../openspec/changes/reconcile-patient-exits-and-stale-admissions/proposal.md)
- [OpenSpec design](../../openspec/changes/reconcile-patient-exits-and-stale-admissions/design.md)
