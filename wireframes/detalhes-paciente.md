# Detalhes do Paciente

Aqui está o blueprint adaptado para a **Página de Detalhes do Paciente**:

```text
+--------------------------------------------------------------------------------------+
| [ SIRHOSP ] |  Prontuário e Linha do Tempo              [ Sincronizado: 12:45 ]   |
+------------------+-------------------------------------------------------------------+
|                  |                                                                   |
|  MENU            |   [ BANNER: FULANO DE TAL | ID: 00123 | IDADE: 45 | LEITO: 202-A ]|
|  --------------  |                                                                   |
|  [🏠] Dashboard  |   COLUNA: INTERNAÇÕES           COLUNA: EVOLUÇÕES (TIMELINE)      |
|                  |   +-------------------------+   +------------------------------+  |
|  [🏥] Censo      |   | SELECIONE O PERÍODO     |   | [ Buscar termo...    ] [Q]   |  |
|                  |   |                         |   |                              |  |
|  [📂] Histórico  |   | > Atual (20/01/2026)    |   | [ 24/01 08:00 ] ENFERMAGEM   |  |
|                  |   | - Alta (15/10/2025)     |   | "Texto capturado via scrape" |  |
|  [⚠️] Monitor de |   | - Alta (03/05/2024)     |   | ---------------------------- |  |
|       Risco      |   |                         |   | [ 23/01 14:00 ] FISIO        |  |
|                  |   |                         |   | "Texto capturado via scrape" |  |
+------------------+---+-------------------------+---+------------------------------+--+
```

## Detalhes Estruturais desta Página

1. **Sidebar (Navegação Persistente):** O item **Pacientes** continua marcado como ativo, pois esta página é um desdobramento da busca.
2. **Banner de Identidade (Bootstrap `.card`):** Um painel horizontal no topo do conteúdo que contém os dados demográficos essenciais. Isso garante que, independente de qual internação o usuário esteja olhando, ele sabe exatamente de quem é o dado.
3. **Layout em Duas Colunas (Bootstrap `.row` e `.col-md-4` / `.col-md-8`):**
    - **Esquerda (Histórico):** Uma lista (`.list-group`) com todas as internações capturadas pelo sistema original. Clicar em uma data carrega os dados correspondentes na coluna da direita.
    - **Direita (Timeline):** \* No topo, um campo de busca específico para filtrar palavras dentro das evoluções deste paciente.
      - Abaixo, os cartões de evolução em ordem cronológica (geralmente da mais recente para a mais antiga).
4. **Ações Futuras (Resumo):** Conforme você mencionou, esse layout já deixa espaço dentro de cada item da timeline para botões de ação (como "Resumir com IA" ou "Marcar como Relevante").

## Sugestão de Usabilidade

Para a diretoria, você pode destacar que o **Banner de Identidade** pode ter cores diferentes: Verde se o paciente estiver internado agora e Cinza se for um prontuário de alguém que já recebeu alta. Isso evita erros de interpretação clínica.
