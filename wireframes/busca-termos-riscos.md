# Busca de Termos - Monitor de Riscos

Esta é a página que você descreveu como a ferramenta de "vigilância clínica". Ela precisa ser visualmente organizada para que o usuário não se perca em meio a centenas de registros, permitindo identificar rapidamente quais pacientes estão em maior risco.

Aqui está o blueprint final para o **Monitor de Risco (Busca por Palavras-Chave)**:

```text
+--------------------------------------------------------------------------------------+
| [ SIRHOSP ] |  Monitor de Risco e Vigilância            [ Sincronizado: 12:45 ]   |
+------------------+-------------------------------------------------------------------+
|                  |                                                                   |
|  MENU            |   PESQUISAR TERMOS EM TODAS AS EVOLUÇÕES RECENTES                 |
|  --------------  |   +------------------------------------------------------------+  |
|  [🏠] Dashboard  |   | [ "queda", "lesão", "febre"    ] [ Últimas 48h v ] [BUSCAR] |  |
|                  |   +------------------------------------------------------------+  |
|  [🏥] Censo      |                                                                   |
|                  |   PACIENTES COM OCORRÊNCIAS DOS TERMOS                            |
|  [📂] Histórico  |   +------------------------------------------------------------+  |
|                  |   | [v] FULANO DE TAL (202-A) - 2 correspondências             |  |
|  [⚠️] Monitor de |   |     > "Risco de queda alto..." (23/01 10:00)               |  |
|       Risco      |   | [>] BELTRANO DE SOUZA (UTI-05) - 1 correspondência         |  |
|       (Ativo)    |   +------------------------------------------------------------+  |
+------------------+-------------------------------------------------------------------+
```

## Detalhes Estruturais desta Página

1. **Sidebar (Navegação Persistente):** O item **Monitor de Risco** está realçado como o local atual.
2. **Motor de Busca (Filtros):**
    - **Input de Termos:** Permite múltiplos termos (ex: separados por vírgula).
    - **Filtro Temporal:** Um dropdown rápido (Últimas 24h, 48h, 7 dias) para focar no que é recente.
3. **Resultados em Accordion (Bootstrap `.accordion`):**
    - **Cabeçalho do Card:** Mostra o nome do paciente e o **contador de ocorrências**. Isso permite que o usuário foque primeiro em quem tem mais alertas (ex: João dos Santos com 5 ocorrências).
    - **Corpo do Card (Expandido):** Mostra os _snippets_ (trechos) do texto com a data e a palavra-chave em destaque.
4. **Links de Navegação Interna:** Dentro de cada card expandido, há um botão "Ver Prontuário Completo", que levaria o usuário direto para a **Página de Detalhes do Paciente (Timeline)** que desenhamos antes.

### Por que apresentar isso à diretoria?

Destaque que este monitor transforma o sistema de um simples visualizador em uma **ferramenta de segurança do paciente**. Em vez de abrir prontuário por prontuário para saber quem teve febre ou caiu, o sistema entrega essa lista pronta, economizando horas de auditoria e permitindo intervenções rápidas.

Com esses quatro Blueprints (Dashboard, Busca/Censo, Detalhes/Timeline e Monitor de Risco), você tem o **esqueleto completo do sistema** para sua apresentação.
