# Busca Histórica

A **Busca Histórica** é o que chamamos de "Rede de Segurança": se o paciente está no banco local, você o exibe; se não está (mas existiu no EHR original), o seu sistema funciona como um _proxy_ que vai lá buscar, indexar e salvar.

Aqui está o **Blueprint: Busca Histórica**, adaptado com a Sidebar e com essa funcionalidade de "Scrape sob demanda":

```text
+--------------------------------------------------------------------------------------+
| [ SIRHOSP ] |  Busca Histórica (Arquivo e On-Demand)    [ Sincronizado: 12:45 ]   |
+------------------+-------------------------------------------------------------------+
|                  |                                                                   |
|  MENU PRINCIPAL  |   PESQUISAR PACIENTES (INTERNADOS OU ALTAS)                       |
|  --------------  |   +------------------------------------------------------------+  |
|  [🏠] Dashboard  |   | [ Nome do Paciente ou Registro...                ] [BUSCAR] |  |
|                  |   +------------------------------------------------------------+  |
|  [🏥] Censo      |                                                                   |
|                  |   RESULTADOS DA BUSCA NO BANCO LOCAL E EHR ORIGINAL               |
|  [📂] Histórico  |   +------------------------------------------------------------+  |
|       (Ativo)    |   | REGISTRO | PACIENTE           | ÚLTIMA ALTA  | FONTE       |  |
|                  |   |----------|--------------------|--------------|-------------|  |
|  [⚠️] Monitor de |   | 00987    | MARIA OLIVEIRA     | 15/12/2025   | Local       |  |
|       Risco      |   | 00554    | JOSE FERREIRA      | 10/01/2026   | Local       |  |
|                  |   | 00332    | ANA PAULA REIS     | 05/02/2026   | EHR (Sync)  |  |
|  --------------  |   +------------------------------------------------------------+  |
|                  |                                                                   |
|  [⚙️] Configs    |   [!] Dica: Se o paciente não for encontrado localmente, o        |
|  [🚪] Sair       |       sistema realizará uma busca direta no EHR original.         |
+------------------+-------------------------------------------------------------------+
```

## Detalhes Estratégicos para sua Apresentação

1. **A Coluna "Fonte" (Diferencial Técnico):**
   - Mostre para a diretoria que o sistema é capaz de distinguir o que já está "em casa" (**Local**) do que ele precisa "ir buscar" (**EHR Sync**). Isso demonstra a inteligência da ferramenta em não duplicar trabalho, mas ser completa quando necessário.

2. **O Fluxo "On-Demand":**
   - Se o usuário clica no paciente que está com a fonte "EHR (Sync)", você pode explicar que o sistema abrirá uma barra de progresso rápida: _"Coletando dados históricos do sistema original... 40%"_. Assim que terminar, ele cai na **Página de Timeline** que já desenhamos.

3. **Utilidade para o Setor de Qualidade:**
   - Destaque que a Qualidade pode auditar eventos adversos mesmo meses após a alta, sem a lentidão ou as limitações de busca do sistema original. O seu sistema permite buscas que o EHR padrão muitas vezes não faz (como buscar por um registro antigo e já consolidar todas as passagens dele).

### Resumo da Navegação Final para a Diretoria

- **Dashboard:** Visão macro do agora.
- **Censo:** Gestão do leito e quem está "dentro" hoje.
- **Histórico:** O "Google" do hospital. Busca tudo, o que passou e o que está no banco, trazendo para a luz dados antigos.
- **Monitor de Risco:** A inteligência sobre o texto (palavras-chave).

Com isso, fechamos o ciclo de wireframes. Essa estrutura é robusta, coerente e resolve as dores de cabeça tanto da assistência (Censo/Risco) quanto do administrativo/qualidade (Histórico).
