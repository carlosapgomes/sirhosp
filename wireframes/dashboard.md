# Dashboard

```text
+--------------------------------------------------------------------------------------+
| [ SIRHOSP ] |  Painel de Controle Principal           [ Sincronizado: 12:45 ]   |
+------------------+-------------------------------------------------------------------+
|                  |                                                                   |
|  MENU            |   RESUMO OPERACIONAL (HOJE)                                       |
|  --------------  |                                                                   |
|  [🏠] Dashboard  |   +------------------+    +------------------+    +------------------+ |
|       (Ativo)    |   | INTERNADOS       |    | CADASTRADOS      |    | ALTAS (24h)      | |
|                  |   |       142        |    |      5.230       |    |       12         | |
|  [🏥] Censo      |   | [Icon: Leito]    |    | [Icon: Pessoas]  |    | [Icon: Saída]    | |
|                  |   +------------------+    +------------------+    +------------------+ |
|  [📂] Histórico  |                                                                   |
|                  |   +--------------------------------------------------------------+    |
|  [⚠️] Monitor de |   | STATUS DA COLETA DE DADOS (WEB SCRAPING)                     |    |
|       Risco      |   | > Monitorando 18 setores em tempo real                       |    |
|                  |   | > Última varredura completa: há 4 minutos                    |    |
|  --------------  |   +--------------------------------------------------------------+    |
|                  |                                                                   |
+------------------+-------------------------------------------------------------------+
```

## Detalhes Funcionais da Interface

1. **Sidebar (Navegação Esquerda):**
   - **Dashboard:** Retorna à tela de indicadores gerais.
   - **Censo:** Abre a lista de enfermarias para navegação por "mapa", busca por nome/registro.
   - **Histórico:** Direciona para a página de busca por nome/registro.
   - **Monitor de Risco:** Abre a busca por palavras-chave (o coração do seu sistema).

2. **Área de Conteúdo (Direita):**
   - Observe que a barra superior agora serve para mostrar o título da página e o **Status do Scraper**. Em um sistema que extrai dados de outro, essa informação visual é vital para o usuário saber se os dados que ele está vendo são os mais recentes do EHR original.

3. **Sugestão de Estilo (Bootstrap 5.3.3):**
   - A Sidebar pode ser configurada como um elemento `sticky-top` (que fica preso enquanto o conteúdo rola).
   - O uso de ícones do **Bootstrap Icons** (como `bi-house`, `bi-hospital`, `bi-search` e `bi-exclamation-triangle`) ajuda na leitura rápida sem precisar ler o texto do menu.
