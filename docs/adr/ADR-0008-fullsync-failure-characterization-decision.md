# ADR-0008 — Decisão de correção da coorte fail-only de full-sync

## Status

Accepted

## Contexto

Preenchimento no slice CFC-S4 do change
`characterize-fullsync-chronic-failures`, a partir de três fontes de
evidência (somente agregados):

1. **Produção (coleta read-only do operador em 2026-08-28, registrada no
   proposal do change):** coorte fail-only de 19 pacientes (7,5% de 252
   com atividade na semana), 588 tentativas terminais esgotadas na janela
   de 7 dias, reasons `timeout`=372 e `invalid_payload`=216; contraste:
   233/252 (92,5%) com full-sync bem-sucedido na semana e ~700 evoluções
   novas por dia fluindo.
2. **Laboratório sintético (`verdicts.json`, executado em CFC-S4):**
   hipóteses H1 e H2 reproduzidas contra o código real de extração e
   classificação, com fixtures 100% sintéticas versionadas no repositório
   (nenhum dado real, nenhuma rede, nenhum browser).
3. **Execução do command read-only em ambiente controlado (CFC-S4):** exit
   0, contagens de models antes/depois idênticas e saída estritamente
   agregada (relatório de caracterização com as cinco seções fixas).
4. **One-shot em produção (`v0.1.0-rc.14`, 2026-08-29, janela 7d):** coorte
   fail-only de **23 pacientes**, 453 runs falhos, mediana de 15 tentativas
   por paciente (máximo 112), reasons `timeout`=382 (84%) e
   `invalid_payload`=71 (16%); **estágio terminal falho =
   `evolution_extraction` em 100% dos 453 runs**; perfis por estágio:
   `evolution_extraction` mediana 43,6s / p90 124,0s contra
   `admissions_capture` 9,6s / 14,1s; histograma horário achatado (sem
   pico); contraste fail-then-ok na mesma janela: 1.477 falhas recuperadas
   (`timeout`=883, `invalid_payload`=594). ADR validada dentro do container
   de produção (`decision ADR valid`).

Regra não negociável: este documento contém somente agregados. Nenhum
identificador de paciente, run, parâmetro, texto clínico, URL ou erro
bruto.

## Hipóteses e vereditos

| Hipótese | Veredito | Evidência |
| --- | --- | --- |
| H1 — timeout por volume/deadline | confirmed | `verdicts.json` H1-timeout-by-volume-deadline: lista longa sintética com deadline curto → reason `timeout` com duração medida ~1.2s, deadline real governando o download; controle com deadline folgado sem falha. Produção: `timeout`=372/588 tentativas da coorte (proposal, 2026-08-28). |
| H2 — invalid_payload por conteúdo | confirmed | `verdicts.json` H2-invalid-payload-content: 6 fixtures sintéticas inválidas → reason `invalid_payload` via classificador real, com a validação disparada identificada em cada uma; controle válido sem falha. Produção: `invalid_payload`=216/588 tentativas da coorte (proposal, 2026-08-28). |

## Causa comprovada

- **H1 confirmada:** o fluxo real de extração de evoluções limita o
  download por um deadline monotônico compartilhado; listas longas de
  evoluções estouram o deadline e a falha tipada mapeia para `timeout`
  (372 de 588 tentativas da coorte em produção).
- **H2 confirmada:** conteúdos que violam validações conhecidas (raiz não
  lista, container ausente, atributo de PDF vazio, assinatura de resposta
  inválida) mapeiam para `invalid_payload` pelo classificador real (216 de
  588 tentativas da coorte em produção).
- As duas causas coexistem na coorte; o esgotamento de todas as 588
  tentativas em 7 dias indica uma política de retry única que não
  distingue falha determinística de payload de falha transitória de
  deadline.

## Correção recomendada

Abrir o change OpenSpec `fix-fullsync-failure-exhaustion`
(proposal/design/specs/tasks apenas; nenhuma implementação neste change,
que é diagnóstico) com:

1. deadline progressivo por volume — ou paginação limitada com
   continuação — no fluxo de extração de evoluções, endereçando H1;
2. política de retry diferenciada por classe de falha: `invalid_payload`
   por validação determinística não deve esgotar tentativas (fail-fast
   com alerta), enquanto `timeout` mantém retry com backoff —
   endereçando o esgotamento das 588 tentativas da coorte;
3. revisão das validações disparadas para distinguir conteúdo
   genuinamente inválido de lacuna de parsing (ex.: atributo de PDF
   vazio), endereçando H2 sem relaxar a taxonomia.

Rastreabilidade: ADR-0008 (este documento) e o change
`characterize-fullsync-chronic-failures` (evidência agregada e vereditos).

## Alternativas rejeitadas

1. Aumentar o deadline global por precaução — rejeitada: correção por
   suposição (anti-pattern proibido pelo RPAP); não distingue as duas
   causas e não endereça o esgotamento de tentativas.
2. Reabrir ou reenfileirar runs históricos da coorte — rejeitada:
   mutação de produção fora do escopo diagnóstico e não endereça a causa.
3. Investigação paciente a paciente em produção — rejeitada: viola a
   política de privacidade do projeto e não isola variáveis.

## Consequências

### Positivas

- Causa decidida por evidência (laboratório sobre código real + agregados
  de produção) em vez de suposição.
- A correção futura tem alvo claro: deadline por volume e retry por classe
  de falha.
- Redução esperada de carga no sistema legado com fail-fast de falhas
  determinísticas (588 tentativas por semana apenas da coorte).

### Negativas / Trade-offs

- Fixtures sintéticas não reproduzem integralmente o ambiente legado; a
  distribuição exata entre as duas causas por paciente permanece
  hipótese residual (o one-shot de produção agregou a coorte, sem
  identificação individual por causa).
- Deadline progressivo pode aumentar o tempo de extração por run em listas
  longas legítimas (mediana atual de 43,6s por `evolution_extraction`).

## Validação

Após preenchimento, este documento deve passar em:

```bash
uv run --no-sync python manage.py generate_fullsync_failure_report \
  --input /tmp/cfc-characterization.txt \
  --output /tmp/cfc-characterization-report.md \
  --check-adr docs/adr/ADR-0008-fullsync-failure-characterization-decision.md
```

Regras objetivas do validador: veredito com evidência, recomendação
presente (correção quando houver hipótese confirmada, próximo experimento
quando nenhuma for confirmada) e zero identidade/conteúdo clínico.

## Referências

- Change OpenSpec `characterize-fullsync-chronic-failures` (proposal,
  design, specs delta, tasks e relatórios CFC-S1 a CFC-S4).
- Relatório de caracterização (gerado por
  `generate_fullsync_failure_report`) e `verdicts.json` do laboratório
  sintético (`automation/lab/playwright_experiments/fullsync_failure_lab.py`).
- Change de correção proposto: `fix-fullsync-failure-exhaustion`
  (proposal/design/specs/tasks, sem implementação).
