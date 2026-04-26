# Setores e Busca de Paciente

Aqui está o blueprint ajustado, mantendo a navegação lateral, a barra superior e focando na tabela de resultados:

```text
+--------------------------------------------------------------------------------------+
| [ SIRHOSP ] |  Censo Hospitalar (Pacientes Internados)   [ Sincronizado: 12:45 ]   |
+------------------+-------------------------------------------------------------------+
|                  |                                                                   |
|  MENU            |   FILTRAR CENSO ATUAL                                             |
|  --------------  |   +------------------------------------------------------------+  |
|  [🏠] Dashboard  |   | [ Nome/Registro...     ] [ Setor (Todos) v ] [ BUSCAR ]    |  |
|                  |   +------------------------------------------------------------+  |
|  [🏥] Censo      |                                                                   |
|       (Ativo)    |   PACIENTES ATUALMENTE NO LEITO                                   |
|                  |   +------------------------------------------------------------+  |
|  [📂] Histórico  |   | LEITO | PACIENTE             | REGISTRO | ADMISSÃO         |  |
|                  |   |-------|----------------------|----------|------------------|  |
|  [⚠️] Monitor de |   | 202-A | FULANO DE TAL        | 00123    | 20/01/2026       |  |
|       Risco      |   | UTI-05| BELTRANO DE SOUZA    | 00456    | 22/01/2026       |  |
|                  |   +------------------------------------------------------------+  |
+------------------+-------------------------------------------------------------------+
```

## Detalhes Estruturais

1. **Dropdown de Setores:** No Bootstrap 5.3.3, esse `<select>` pode conter todos os seus 20 setores. Ao selecionar um (ex: "UTI Adulto") e clicar em buscar, a tabela abaixo é recarregada apenas com os pacientes daquele local.
2. **Tabela Unificada:** A tabela serve tanto para a busca global quanto para a navegação por setor. Isso simplifica o código e a experiência do usuário.
3. **Paginação/Resumo:** Adicionei uma linha ao final da tabela mostrando o total de internados. Isso ajuda o usuário a ter noção da carga de trabalho do hospital sem precisar voltar ao Dashboard.
4. **Ação de Clique:** Cada linha da tabela é um link. O usuário clica em qualquer lugar da linha do "Fulano de Tal" para ser levado à página de detalhes/timeline dele.

### Sugestão para o Dropdown

Para facilitar ainda mais a vida do usuário com 20 setores, você pode usar um componente de busca dentro do próprio dropdown (como o _Select2_ ou _Datalist_ do HTML5), permitindo que ele digite "UTI" e o filtro já apareça, sem precisar rolar a lista toda.
