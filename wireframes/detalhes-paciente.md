# Detalhes do Paciente

Aqui está o blueprint adaptado para a **Página de Detalhes do Paciente**:

```text
+--------------------------------------------------------------------------------------+
| [ EHR MIRROR ] |  Prontuário e Linha do Tempo              [ Sincronizado: 12:45 ]   |
+------------------+-------------------------------------------------------------------+
|                  |                                                                   |
|  MENU PRINCIPAL  |   [ BANNER DE IDENTIFICAÇÃO DO PACIENTE ]                         |
|  --------------  |   +------------------------------------------------------------+  |
|  [🏠] Dashboard  |   | NOME: FULANO DE TAL | REGISTRO: 00123 | IDADE: 45 anos (M) |  |
|                  |   | NASC: 15/05/1980    | LEITO ATUAL: UTI - BOX 02            |  |
|  [🏥] Setores    |   +------------------------------------------------------------+  |
|                  |                                                                   |
|  [🔍] Pacientes  |   COLUNA ESQUERDA (33%)         COLUNA DIREITA (66%)              |
|       (Ativo)    |   +-------------------------+   +------------------------------+  |
|  [⚠️] Monitor de |   | HISTÓRICO DE ESTADIAS   |   | PESQUISA NA EVOLUÇÃO         |  |
|       Risco      |   | [ Buscar data...     ]  |   | [ Digite termo... ] [BUSCAR] |  |
|                  |   |                         |   |                              |  |
|  --------------  |   | > Ativa: 20/01/2026     |   | TIMELINE DA INTERNAÇÃO       |  |
|                  |   | - Passada: 15/10/2025   |   | [ 24/01 08:00 ] ENFERMAGEM   |  |
|  [⚙️] Configs    |   | - Passada: 03/05/2024   |   | "Texto da evolução aqui..."  |  |
|                  |   |                         |   | ---------------------------- |  |
|  [🚪] Sair       |   |                         |   | [ 23/01 14:00 ] FISIO        |  |
|                  |   |                         |   | "Texto da evolução aqui..."  |  |
+------------------+---+-------------------------+---+------------------------------+--+
```

### Detalhes Estruturais desta Página:

1.  **Sidebar (Navegação Persistente):** O item **Pacientes** continua marcado como ativo, pois esta página é um desdobramento da busca.
2.  **Banner de Identidade (Bootstrap `.card`):** Um painel horizontal no topo do conteúdo que contém os dados demográficos essenciais. Isso garante que, independente de qual internação o usuário esteja olhando, ele sabe exatamente de quem é o dado.
3.  **Layout em Duas Colunas (Bootstrap `.row` e `.col-md-4` / `.col-md-8`):**
    * **Esquerda (Histórico):** Uma lista (`.list-group`) com todas as internações capturadas pelo sistema original. Clicar em uma data carrega os dados correspondentes na coluna da direita.
    * **Direita (Timeline):** * No topo, um campo de busca específico para filtrar palavras dentro das evoluções deste paciente.
        * Abaixo, os cartões de evolução em ordem cronológica (geralmente da mais recente para a mais antiga).
4.  **Ações Futuras (Resumo):** Conforme você mencionou, esse layout já deixa espaço dentro de cada item da timeline para botões de ação (como "Resumir com IA" ou "Marcar como Relevante").

### Sugestão de Usabilidade:
Para a diretoria, você pode destacar que o **Banner de Identidade** pode ter cores diferentes: Verde se o paciente estiver internado agora e Cinza se for um prontuário de alguém que já recebeu alta. Isso evita erros de interpretação clínica.
