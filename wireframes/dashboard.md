# Dashboard

```text
+--------------------------------------------------------------------------------------+
| [ LOGO SISTEMA ] |  Painel de Controle Principal           [ Sincronizado: 12:45 ]   |
+------------------+-------------------------------------------------------------------+
|                  |                                                                   |
|  MENU PRINCIPAL  |   INDICADORES GERAIS (TEMPO REAL)                                 |
|  --------------  |                                                                   |
|  [🏠] Dashboard  |   +------------------+    +------------------+    +------------------+ |
|                  |   | INTERNADOS       |    | CADASTRADOS      |    | ALTAS (24h)      | |
|  [🏥] Setores    |   |       142        |    |      5.230       |    |       12         | |
|                  |   | [Icon: Leito]    |    | [Icon: Pessoas]  |    | [Icon: Saída]    | |
|  [🔍] Pacientes  |   +------------------+    +------------------+    +------------------+ |
|                  |                                                                   |
|  [⚠️] Monitor de |   +--------------------------------------------------------------+    |
|       Risco      |   | ATIVIDADE RECENTE DO SCRAPER                                 |    |
|                  |   | > Setor UTI: Atualizado há 2 min                             |    |
|  --------------  |   | > Setor Pediatria: Atualizado há 5 min                       |    |
|                  |   | > Setor Cirurgia: Sincronizando agora... [|||||     ] 60%    |    |
|  [⚙️] Configs    |   +--------------------------------------------------------------+    |
|  [🚪] Sair       |                                                                   |
+------------------+-------------------------------------------------------------------+
```

### Detalhes Funcionais da Interface:

1.  **Sidebar (Navegação Esquerda):**
    * **Dashboard:** Retorna à tela de indicadores gerais.
    * **Setores:** Abre a lista de enfermarias para navegação por "mapa".
    * **Pacientes:** Direciona para a página de busca por nome/registro/leito.
    * **Monitor de Risco:** Abre a busca por palavras-chave (o coração do seu sistema).

2.  **Área de Conteúdo (Direita):**
    * Observe que a barra superior agora serve para mostrar o título da página e o **Status do Scraper**. Em um sistema que extrai dados de outro, essa informação visual é vital para o usuário saber se os dados que ele está vendo são os mais recentes do EHR original.

3.  **Sugestão de Estilo (Bootstrap 5.3.3):**
    * A Sidebar pode ser configurada como um elemento `sticky-top` (que fica preso enquanto o conteúdo rola).
    * O uso de ícones do **Bootstrap Icons** (como `bi-house`, `bi-hospital`, `bi-search` e `bi-exclamation-triangle`) ajuda na leitura rápida sem precisar ler o texto do menu.
