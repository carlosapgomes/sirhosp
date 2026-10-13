# Design

## Context

Motivação e escopo: [proposal.md](proposal.md). Contrato de comportamento:
[delta de daily-statistics-reporting](specs/daily-statistics-reporting/spec.md).

Reconhecimento realizado antes da decomposição:

- `apps/statistics_reports/templates/statistics_reports/daily_report.html`
  usa botões nativos e Bootstrap Collapse nos dois níveis. Ambos começam com
  `aria-expanded="false"` e têm alvos distintos; não há `data-bs-parent`.
- O cabeçalho do setor já tem `bi-chevron-right collapse-icon`. As categorias
  usam `btn btn-sm btn-light`, título e badge, mas não têm chevron.
- Não foi encontrada regra de rotação de `collapse-icon` no CSS do portal.
- `templates/base.html` carrega Bootstrap 5.3.3, Bootstrap Icons 1.11.3 e
  `static/css/sirhosp.css`, nessa ordem. A navegação lateral também possui
  collapsible, que não faz parte desta mudança.
- `apps/statistics_reports/presentation.py` já fornece listas, títulos,
  contadores e estados vazios. A seção condicional sem agrupamento usa o mesmo
  template, com listas e títulos próprios; não se deve forçá-la a ter quatro
  categorias.
- `tests/integration/test_daily_statistics_page.py` oferece fixtures sintéticas
  e testes de autorização, contagens, acessibilidade, ordenação e navegação.
  Eles não executam CSS nem o JavaScript de abertura no browser.

O design é necessário para fixar a fonte única de estado, o isolamento dos
estilos compartilhados e a verification de comportamento visual antes da
implementação.

## Goals / Non-Goals

**Goals:**

- Reutilizar os mecanismos existentes de abertura, ícones e tema.
- Concentrar alterações de produção no template estatístico e CSS delimitado.
- Demonstrar orientação, foco e layout com browser real, sem depender de um
  ambiente implantado ou de registros clínicos.

**Non-Goals:**

- Criar componente genérico de accordion, novo controlador JavaScript ou
  sistema de temas; ver demais limites em `proposal.md`.
- Transformar testes de browser em novo requisito dos gates globais ou
  ampliar a suíte de verification do portal implantado.

## Decisions

### D1 — Derivar o indicador do estado acessível do próprio botão

Manter Bootstrap Collapse como controlador único. Reutilizar o ícone
`bi-chevron-right`, decorativo com `aria-hidden="true"`, antes do título nos
dois níveis. CSS orientará o ícone em 0 graus quando
`aria-expanded="false"` e 90 graus quando `aria-expanded="true"`.

O seletor deve consultar o próprio botão, não um ancestral expandido: abrir
um setor não pode orientar para baixo os ícones das categorias ainda fechadas.
Usar classe explícita compartilhada pelos controles estatísticos e um
marcador de página para delimitar os estilos. Não depender da classe
`collapsed`, atualmente ausente na carga inicial do cabeçalho setorial.

Não é necessária animação. Se uma transição curta for usada, respeitar
`prefers-reduced-motion` e verificar o estado final após a transição.

Alternativas descartadas: trocar o ícone por handlers JavaScript duplicaria
estado; selecionar qualquer botão expansível globalmente atingiria a sidebar
ou outras páginas; ícone fixo não satisfaz o feedback de abertura.

### D2 — Usar affordance neutra e hierarquia existente

Categorias internas terão fundo neutro claro, borda sutil e texto escuro
compatíveis com o tema; o estado aberto terá fundo neutro ligeiramente mais
marcado. Reutilizar tokens neutros existentes do Bootstrap/tema em vez de
introduzir uma paleta por tipo de evento.

Preservar o cabeçalho setorial em destaque, o recuo proporcionado pelo
`card-body`, os badges e as sinalizações de qualidade existentes. Hover é
feedback adicional, não a única pista de interação. Foco por teclado deve
permanecer visível nos dois níveis, sem remover outline sem substituição.

Detalhe de apresentação assumido para tornar a proposta verificável: altura
mínima de 44 pixels CSS nos controles. É ajuste local, não alteração global
de `.btn-sm`. Valores exatos das tonalidades neutras podem usar os tokens já
existentes, desde que os estados sejam distinguíveis sem hover e o texto
continue legível.

Alternativas descartadas: cores distintas poderiam sugerir significado
clínico; rótulos repetidos `Expandir/Recolher` e tooltips aumentariam ruído ou
continuariam dependendo de descoberta prévia.

### D3 — Separar o espaço do título do ícone e do contador

Manter botão ocupando a largura inteira. Ícone e badge não encolhem; o título
ocupa o espaço restante, é alinhado à esquerda e pode quebrar naturalmente.
Linhas adicionais do título começam após o espaço reservado ao ícone. O badge
permanece à direita sem sobreposição.

Não truncar nem renomear a categoria longa. Preservar alvos, atributos ARIA,
botões nativos, expansão independente, listas vazias e estado dos filhos ao
recolher e reabrir um setor. Não modificar dados da projeção para adequar o
layout.

### D4 — Combinar regressão de renderização com verification local pequena

Ampliar os testes existentes da página para demonstrar, em RED/GREEN, o
indicador decorativo em cada controle, os nomes acessíveis preservados, alvos
e contadores. Reutilizar os testes atuais para os contratos de dados e
permissões; não testar o CSS por busca textual como substituto do browser.

Adicionar somente `scripts/verify_statistics_collapses.py`: um cenário
Playwright específico, executado sob demanda, que renderiza o template real
com projeção inteiramente sintética em memória e contexto explícito, sem
request/context processors que consultem o banco. Não autentica no portal,
não chama views clínicas, não materializa relatórios e não cria registros.

O cenário deve carregar o CSS do repositório e Bootstrap/Icons nas versões do
`base.html`, incluindo a fonte dos ícones. Resolver estáticos localmente;
bloquear navegação para serviços clínicos, polling HTMX e origens não
necessárias. Não simular o JavaScript de collapse nem reproduzir o HTML do
componente manualmente.

Contrato mínimo do cenário:

- `--help` e `--output-dir`; sem opção de apontar para servidor implantado.
- Incluir ao menos dois setores sintéticos, as quatro categorias usuais,
  contagens zero e não zero e a seção condicional sem setor identificado.
- Exercitar desktop (1280 x 900) e mobile (375 x 812), clique na área livre do
  botão, Enter/Espaço, foco, abrir/recolher repetidamente e independência dos
  controles; recolher/reabrir pai com filho aberto.
- Aferir visibilidade do conteúdo, `aria-expanded`, orientação computada e
  carregamento efetivo do ícone; aferir fundo/borda sem hover, diferenciação
  neutra aberta, altura mínima e ausência de sobreposição/overflow dos
  cabeçalhos. Estado neutro não deve ser confundido com hover ou foco.
- Capturar screenshots sintéticas nos dois viewports e resultado estruturado
  com comandos, assertions, assets e status; salvar só no diretório de saída.
- Retornar 0 somente após todos os checks obrigatórios; falha comportamental
  retorna 1 e indisponibilidade de browser/assets retorna 2 (BLOCKED), nunca
  um sucesso por skip. Fechar o browser também em falha.

O mesmo cenário fornece failing-before e passing-after; deve ser construído
antes das alterações de produção. O isolamento em memória demonstra a UI,
não autorização nem persistência; estas continuam cobertas pela integração.
É um lever pequeno para este bug visual, não um framework genérico.

A suíte implantada documentada em `docs/dev-verification.md` continua
complementar e somente sob autorização específica. Criar ou implementar esta
change não autoriza executá-la.

## Risks / Trade-offs

- [CSS compartilhado] → Seletores sob marcador da página e classe dos próprios
  botões; conferir que navegação lateral e demais páginas não foram afetadas.
- [Estado visual divergente] → Orientação derivada de `aria-expanded`, exercitada
  por mouse e teclado, com ciclos completos nos dois níveis.
- [Título longo ou badge comprimido] → Espaço flexível só para texto e checks
  de geometria em mobile.
- [Browser ou CDN indisponível] → Status BLOCKED, sem declarar o slice aceito;
  não substituir Bootstrap por mocks para obter sucesso.
- [Verificação sintética limitada] → Combinar browser com integração; não
  afirmar que screenshots comprovam compreensão por toda a equipe hospitalar.

## Migration Plan

Não há migração, alteração clínica, de banco, scraping ou jobs. Publicar
estáticos pelo processo existente somente após autorização de deploy; não há
feature flag ou serviço novo. Rollback consiste em reverter os ajustes de
template/CSS, sem efeito sobre revisões estatísticas e exportações.
