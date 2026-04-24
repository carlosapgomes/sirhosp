# Setores e Busca de Paciente

Aqui está o blueprint ajustado, mantendo a navegação lateral, a barra superior e focando na tabela de resultados:

```text
+--------------------------------------------------------------------------------------+
| [ EHR MIRROR ] |  Busca de Pacientes / Censo               [ Sincronizado: 12:45 ]   |
+------------------+-------------------------------------------------------------------+
|                  |                                                                   |
|  MENU PRINCIPAL  |   FILTROS DE PESQUISA E FILTRAGEM POR SETOR                       |
|  --------------  |   +------------------------------------------------------------+  |
|  [🏠] Dashboard  |   | [ Nome... ] [ Registro ] [ Selecione o Setor v ] [BUSCAR]  |  |
|                  |   +------------------------------------------------------------+  |
|  [🏥] Setores    |                                                                   |
|       (Ativo)    |   RESULTADOS (TODOS OS PACIENTES OU FILTRADOS POR SETOR)          |
|                  |   +------------------------------------------------------------+  |
|  [🔍] Pacientes  |   | REGISTRO | PACIENTE           | SETOR / LEITO | ADMISSÃO   |  |
|                  |   |----------|--------------------|---------------|------------|  |
|  [⚠️] Monitor de |   | 00123    | FULANO DE TAL      | UTI - 02      | 20/01/2026 |  |
|       Risco      |   | 00456    | BELTRANO DE SOUZA  | ENF A - 105   | 22/01/2026 |  |
|                  |   | 00789    | CICRANO DE OLIVEIRA| ENF B - 202   | 23/01/2026 |  |
|  --------------  |   | 01011    | MARIA DA SILVA     | PED - 04      | 24/01/2026 |  |
|                  |   | 01213    | JOÃO DOS SANTOS    | CC - SALA 01  | 24/01/2026 |  |
|  [⚙️] Configs    |   | ...      | ...                | ...           | ...        |  |
|                  |   +------------------------------------------------------------+  |
|  [🚪] Sair       |   | Exibindo 50 de 142 pacientes internados        [ < 1 2 3 > ]  |
+------------------+---+------------------------------------------------------------+--+
```

### Detalhes Estruturais:

1.  **Dropdown de Setores:** No Bootstrap 5.3.3, esse `<select>` pode conter todos os seus 20 setores. Ao selecionar um (ex: "UTI Adulto") e clicar em buscar, a tabela abaixo é recarregada apenas com os pacientes daquele local.
2.  **Tabela Unificada:** A tabela serve tanto para a busca global quanto para a navegação por setor. Isso simplifica o código e a experiência do usuário.
3.  **Paginação/Resumo:** Adicionei uma linha ao final da tabela mostrando o total de internados. Isso ajuda o usuário a ter noção da carga de trabalho do hospital sem precisar voltar ao Dashboard.
4.  **Ação de Clique:** Cada linha da tabela é um link. O usuário clica em qualquer lugar da linha do "Fulano de Tal" para ser levado à página de detalhes/timeline dele.

### Sugestão para o Dropdown:
Para facilitar ainda mais a vida do usuário com 20 setores, você pode usar um componente de busca dentro do próprio dropdown (como o *Select2* ou *Datalist* do HTML5), permitindo que ele digite "UTI" e o filtro já apareça, sem precisar rolar a lista toda.
