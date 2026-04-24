# Busca de Termos - Monitor de Riscos

Esta é a página que você descreveu como a ferramenta de "vigilância clínica". Ela precisa ser visualmente organizada para que o usuário não se perca em meio a centenas de registros, permitindo identificar rapidamente quais pacientes estão em maior risco.

Aqui está o blueprint final para o **Monitor de Risco (Busca por Palavras-Chave)**:

```text
+--------------------------------------------------------------------------------------+
| [ EHR MIRROR ] |  Monitor de Risco: Busca de Termos        [ Sincronizado: 12:45 ]   |
+------------------+-------------------------------------------------------------------+
|                  |                                                                   |
|  MENU PRINCIPAL  |   MOTOR DE BUSCA CLÍNICA (Vigilância Ativa)                       |
|  --------------  |   +------------------------------------------------------------+  |
|  [🏠] Dashboard  |   | [ "queda", "febre", "sangramento" ]  [ 48h v ]  [ BUSCAR ]  |  |
|                  |   +------------------------------------------------------------+  |
|  [🏥] Setores    |                                                                   |
|                  |   RESULTADOS AGRUPADOS POR PACIENTE                               |
|  [🔍] Pacientes  |   +------------------------------------------------------------+  |
|                  |   | [v] PACIENTE: FULANO DE TAL (ID: 00123) - 3 Ocorrências    |  |
|  [⚠️] Monitor de |   |     Setor: UTI - Leito: 02                                 |  |
|       Risco      |   |     --------------------------------------------------     |  |
|       (Ativo)    |   |     [ 23/01 10:00 ] "...risco de QUEDA elevado..."         |  |
|  --------------  |   |     [ 22/01 14:00 ] "...episódio de QUEDA no leito..."     |  |
|                  |   |     [ Ver Prontuário Completo ]                            |  |
|  [⚙️] Configs    |   +------------------------------------------------------------+  |
|                  |   | [>] PACIENTE: MARIA SILVA (ID: 05542) - 1 Ocorrência       |  |
|  [🚪] Sair       |   +------------------------------------------------------------+  |
|                  |   | [>] PACIENTE: JOÃO DOS SANTOS (ID: 01213) - 5 Ocorrências  |  |
+------------------+---+------------------------------------------------------------+--+
```

### Detalhes Estruturais desta Página:

1.  **Sidebar (Navegação Persistente):** O item **Monitor de Risco** está realçado como o local atual.
2.  **Motor de Busca (Filtros):**
    * **Input de Termos:** Permite múltiplos termos (ex: separados por vírgula).
    * **Filtro Temporal:** Um dropdown rápido (Últimas 24h, 48h, 7 dias) para focar no que é recente.
3.  **Resultados em Accordion (Bootstrap `.accordion`):**
    * **Cabeçalho do Card:** Mostra o nome do paciente e o **contador de ocorrências**. Isso permite que o usuário foque primeiro em quem tem mais alertas (ex: João dos Santos com 5 ocorrências).
    * **Corpo do Card (Expandido):** Mostra os *snippets* (trechos) do texto com a data e a palavra-chave em destaque. 
4.  **Links de Navegação Interna:** Dentro de cada card expandido, há um botão "Ver Prontuário Completo", que levaria o usuário direto para a **Página de Detalhes do Paciente (Timeline)** que desenhamos antes.

### Por que apresentar isso à diretoria?
Destaque que este monitor transforma o sistema de um simples visualizador em uma **ferramenta de segurança do paciente**. Em vez de abrir prontuário por prontuário para saber quem teve febre ou caiu, o sistema entrega essa lista pronta, economizando horas de auditoria e permitindo intervenções rápidas.

Com esses quatro Blueprints (Dashboard, Busca/Censo, Detalhes/Timeline e Monitor de Risco), você tem o **esqueleto completo do sistema** para sua apresentação. 
