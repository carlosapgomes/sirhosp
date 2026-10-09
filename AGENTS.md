# AGENTS.md

## 1. Stack e versões

- Python: 3.12
- Gerenciamento Python: `uv`
- Backend: Django 5.x
- Banco principal: PostgreSQL
- Frontend inicial: Django Templates + HTMX + Bootstrap
- Automação de browser: Playwright + Python
- Extração de PDF: PyMuPDF
- Especificação e memória de mudanças: OpenSpec
- Execução agentic: Pi + pi-subagents
- Metodologia auxiliar de engenharia: pstack, usada conforme a política deste
  arquivo
- Execução programada: `systemd services` e `timers`
  - ver `deploy/README.md`
  - ver `deploy/systemd/`
- Agendamento de censo: orquestrador adaptativo via
  `run_adaptive_census_cycles --loop`
- Worker contínuo:
  `process_ingestion_runs --loop --sleep-seconds 5`
- Processamento assíncrono fase 1:
  **sem Celery/Redis**; coordenação via PostgreSQL

---

## 2. Autoridade e responsabilidades do workflow

Cada ferramenta possui uma responsabilidade distinta.

Não ativar dois controllers para a mesma fase do trabalho.

### OpenSpec

OpenSpec é a fonte de verdade para:

- problema e motivação;
- requisitos;
- comportamento esperado;
- decisões de design aprovadas;
- tarefas;
- histórico da mudança.

Uma change OpenSpec aprovada é o **contrato de produto e design** da
implementação.

Durante a implementação, não reinterpretar, ampliar ou substituir
silenciosamente requisitos ou decisões aprovadas.

Se a implementação revelar que uma decisão aprovada é inviável, incorreta ou
incompatível com o código real:

1. parar antes de assumir uma nova decisão;
2. registrar evidências;
3. reportar `NEEDS_HUMAN_DECISION`;
4. alterar o OpenSpec somente após decisão explícita.

### Skills autorais de slicing

As skills de slicing transformam uma change já suficientemente definida em
unidades de implementação executáveis e verificáveis.

Elas não devem:

- redesenhar silenciosamente a change;
- controlar agentes;
- escolher modelos;
- atualizar progresso de execução;
- criar commits;
- fazer push.

### `/slice-loop`

`/slice-loop` é o controller para **exatamente um slice aprovado**.

Ele:

- executa um worker fresh;
- executa um reviewer fresh e independente;
- coordena correções limitadas;
- aceita ou escala o slice;
- atualiza estado somente após aceite;
- para após o slice.

### `/change-loop`

`/change-loop` é o controller padrão para executar **uma change aprovada
inteira**.

A invocação de `/change-loop` autoriza o controller a:

- executar sequencialmente todos os slices já aprovados;
- avançar automaticamente após cada slice aceito;
- atualizar tarefas;
- criar commits atômicos conforme a política do projeto;
- executar o gate final.

Não pedir autorização entre slices normais.

Parar somente quando houver condição de escalonamento definida neste arquivo.

### OpenSpec apply

Não executar o workflow de implementação do OpenSpec como segundo controller
quando `/slice-loop` ou `/change-loop` estiver ativo.

Comandos OpenSpec continuam permitidos para:

- contexto;
- status;
- inspeção;
- validação;
- sincronização;
- encerramento e archive quando autorizado.

### pstack

O pstack possui duas formas de uso distintas.

Antes da aprovação de design, podem ser usados workflows amplos, incluindo:

- `poteto-mode`;
- `how`;
- `why`;
- `architect`;
- `arena`;
- outras ferramentas investigativas apropriadas.

Depois que uma change ou slice estiver aprovado, **não usar `poteto-mode`
completo como controller de implementação**.

Durante execução aprovada, podem ser utilizadas disciplinas estreitas do
pstack quando úteis, por exemplo:

- TDD;
- prove-it-works;
- test-behavior-not-implementation;
- laziness/smallest-correct-change;
- model-the-domain;
- build-the-lever;
- verification específica do projeto.

Não permitir que essas disciplinas reabram design já aprovado sem um bloqueio
concreto.

---

## 3. Política de agentes e modelos

### Autoridade dos modelos

`pi-subagents` é a autoridade para seleção de modelos durante execução
OpenSpec.

Por padrão, controllers e skills **não devem passar `model` explicitamente**
nas chamadas de agentes.

Devem prevalecer:

- configuração do agente;
- overrides do projeto;
- profiles do pi-subagents;
- política central de modelos.

Exceções devem ser deliberadas e registradas.

O mapa de modelos do pstack pode ser utilizado em workflows pstack
independentes de investigação, mas não substitui automaticamente a política
do pi-subagents para execução de slices.

### Papéis

Uso recomendado:

- `scout`: reconhecimento de código e blast radius;
- `researcher`: pesquisa externa quando necessária;
- `evidence-auditor`: confirmação independente de evidências importantes;
- `oracle`: desafio de arquitetura ou decisão;
- `worker`: implementação;
- `reviewer`: revisão independente;
- `delegate`: uso geral somente quando o papel especializado não for adequado.

### Contexto

Por padrão:

- worker: fresh context;
- reviewer: fresh context;
- scout: fresh context;
- researcher: fresh context;
- evidence-auditor: fresh context.

O contexto necessário deve ser reconstruível a partir de arquivos e
referências explícitas do repositório.

"Fresh context" não significa copiar toda a documentação para o prompt.

Significa que o agente não depende da conversa anterior para reconstruir o
trabalho.

### Reviewer

O reviewer do projeto deve ser configurado como **read-only**.

O reviewer:

- não implementa;
- não corrige código;
- não modifica arquivos;
- não atualiza OpenSpec;
- não cria commits;
- não faz push.

Ele confronta independentemente:

- contrato do slice;
- requisitos relevantes;
- código;
- diff;
- testes;
- evidências de verificação.

O relatório do worker é evidência auxiliar, não fonte de verdade para o
reviewer.

---

## 4. Comandos de validação — Quality Gate

### Caminho oficial

- Django check:

```bash
./scripts/test-in-container.sh check
```

- Testes unitários:

```bash
./scripts/test-in-container.sh unit
```

- Testes de integração:

```bash
./scripts/test-in-container.sh integration
```

- Lint:

```bash
./scripts/test-in-container.sh lint
```

- Type check:

```bash
./scripts/test-in-container.sh typecheck
```

- Gate completo:

```bash
./scripts/test-in-container.sh quality-gate
```

### Ferramentas auxiliares

- Instalar dependências locais:

```bash
uv sync
```

- Markdown autofix:

```bash
./scripts/markdown-format.sh
```

- Markdown lint:

```bash
./scripts/markdown-lint.sh
```

### Regra operacional

Execução host-only, como:

```bash
uv run pytest ...
```

é diagnóstico local, não gate oficial.

Motivo: `POSTGRES_HOST=db` resolve apenas na rede Docker Compose e pode falhar
no host com:

```text
failed to resolve host 'db'
```

### Markdown

Todo arquivo `.md` criado ou alterado deve passar sem erros por:

```bash
./scripts/markdown-lint.sh
```

O projeto usa `.markdownlint-cli2.yaml`.

É proibido mascarar erros com:

```html
<!-- markdownlint-disable ... -->
```

Corrigir a causa raiz.

Se uma regra do projeto realmente precisar ser alterada, fazer a mudança em
`.markdownlint-cli2.yaml` com justificativa documentada.

Usar:

```bash
./scripts/markdown-format.sh
```

para autofix quando aplicável.

---

## 5. Comandos essenciais de operação local

### Setup

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
```

### Rodar local

```bash
uv run python manage.py migrate
uv run python manage.py runserver
```

### Testes rápidos

```bash
./scripts/test-in-container.sh unit
```

### Testes host-only — somente diagnóstico

```bash
uv run pytest -q tests/unit
```

### Jobs e automações

Comandos manuais:

```bash
uv run python manage.py extract_census
uv run python manage.py process_census_snapshot
uv run python manage.py process_ingestion_runs
uv run python manage.py run_due_jobs
uv run python manage.py sync_current_inpatients
uv run python manage.py extract_medical_evolutions
uv run python manage.py extract_prescriptions
uv run python manage.py refresh_admission_summaries
uv run python manage.py process_summary_runs --pipeline
uv run python manage.py run_adaptive_census_cycles
```

Agendamento automático:

- configurar o orquestrador adaptativo de censo e worker contínuo conforme
  `deploy/README.md`;
- `run_adaptive_census_cycles --loop` dispara ciclos quando a fila de ingestão
  estiver drenada;
- `process_ingestion_runs --loop` processa runs enfileirados;
- para sumários, o padrão operacional é
  `process_summary_runs --pipeline --loop`.

### Hooks

```bash
git config core.hooksPath .githooks
```

---

## 6. Arquitetura e constraints

- Manter o projeto como **monólito modular Django** na fase 1.
- Não introduzir Celery, Redis ou microserviços sem decisão explícita em
  ADR/OpenSpec.
- Usar PostgreSQL tanto para persistência clínica quanto para coordenação
  operacional básica de jobs.
- Separar claramente código de **modo laboratório** e **modo produção** nas
  automações Playwright.
- Não versionar dados reais de pacientes, PDFs reais, dumps reais ou
  credenciais.
- Tratar o MVP `resumo-evolucoes-clinicas` como fonte de reaproveitamento
  técnico, não como arquitetura final.
- Preservar separação entre:
  - portal web;
  - domínio clínico;
  - conectores de ingestão.
- Mudanças que afetem comportamento clínico, auditabilidade, segurança,
  privacidade ou integridade de dados devem ser explícitas no OpenSpec.
- Não criar abstrações, dependências ou infraestrutura para necessidades
  hipotéticas.
- Preferir a menor mudança correta compatível com o design aprovado.

---

## 7. Engineering policies

Estas políticas são globais para implementação.

Não devem ser copiadas integralmente para cada slice.

Os slices devem referenciar este arquivo e acrescentar apenas restrições ou
exceções específicas da mudança.

### 7.1 Smallest correct change

Implementar a menor mudança que satisfaça corretamente o contrato aprovado.

Evitar:

- ampliar escopo para melhorias adjacentes;
- refatorar áreas não relacionadas;
- introduzir abstrações apenas porque seriam "mais elegantes";
- resolver antecipadamente problemas que não fazem parte da change atual.

Mudanças adicionais são aceitáveis quando forem necessárias para manter
correção, segurança, consistência ou verificabilidade.

Quando o blast radius crescer materialmente, justificar ou escalar.

### 7.2 YAGNI

Não implementar antecipadamente:

- extensibilidade hipotética;
- opções de configuração sem consumidor atual;
- generalizações para casos ainda inexistentes;
- infraestrutura sem necessidade presente;
- abstrações criadas apenas para suportar um futuro imaginado.

Quando o problema atual puder ser resolvido corretamente de maneira simples,
preferir a solução simples.

YAGNI não proíbe preparação necessária para um requisito já aprovado.

### 7.3 DRY

Evitar duplicação de **conhecimento, regra ou comportamento**.

Não aplicar DRY mecanicamente apenas porque linhas de código são parecidas.

Duas implementações semelhantes podem representar conceitos diferentes.

Evitar abstrações prematuras criadas somente para reduzir poucas linhas
duplicadas.

Preferir pequena duplicação explícita a uma abstração errada.

Extrair quando houver:

- conceito realmente compartilhado;
- regra que precise permanecer consistente;
- padrão repetido cuja divergência seria problemática;
- benefício claro para leitura, manutenção ou segurança.

### 7.4 Clean Code

Priorizar:

- nomes que expressem intenção;
- funções e módulos com responsabilidade clara;
- fluxo de controle simples;
- dependências explícitas;
- baixo acoplamento;
- coesão;
- interfaces pequenas e compreensíveis;
- código fácil de testar e verificar;
- comentários que expliquem **por quê**, quando o porquê não estiver evidente.

Evitar:

- funções excessivamente grandes;
- abstrações sem propósito claro;
- magic behavior;
- side effects inesperados;
- comentários que apenas repetem o código;
- refactoring cosmético fora do escopo.

Legibilidade deve ser avaliada do ponto de vista do próximo mantenedor humano
ou agente que chegar com contexto fresh.

### 7.5 Preserve project conventions

Antes de criar um novo padrão:

1. procurar como o projeto já resolve problemas semelhantes;
2. reutilizar convenções adequadas;
3. introduzir um novo padrão somente quando houver benefício concreto.

Se a mudança de padrão for estruturalmente relevante, registrá-la no artefato
apropriado.

Não introduzir uma segunda maneira de resolver o mesmo problema sem motivo
claro.

### 7.6 Test behavior, not implementation

Testes devem preferencialmente verificar:

- comportamento observável;
- contratos;
- invariantes;
- resultados;
- efeitos relevantes.

Evitar testes excessivamente acoplados a:

- ordem interna de chamadas;
- detalhes privados de implementação;
- estrutura que pode mudar em um refactor seguro.

Mocks devem ser usados quando ajudam a isolar um contrato real, não para
reproduzir internamente toda a implementação.

### 7.7 Build the Lever

Quando uma operação importante, erro recorrente ou regra de engenharia puder
ser transformado em uma restrição automática e reproduzível, preferir
construir essa restrição em vez de depender permanentemente de memória,
prompts ou revisão humana.

Preferir, conforme o problema:

- linters;
- type checkers;
- formatters;
- architectural checks;
- regras de imports e dependências;
- schema validation;
- database constraints;
- model constraints;
- framework/system checks;
- security scanners;
- pre-commit hooks;
- CI quality gates;
- testes automatizados;
- CLIs pequenas;
- scripts determinísticos;
- fixtures;
- helpers;
- ferramentas de verification reutilizáveis.

A melhor solução para uma classe recorrente de erro frequentemente não é
lembrar o agente de não cometê-la.

É tornar o erro:

- impossível;
- detectável imediatamente;
- ou caro demais para passar pelo quality gate.

Quando um reviewer encontrar repetidamente a mesma classe de problema,
considerar transformá-la em:

- lint;
- type rule;
- architecture check;
- teste;
- constraint;
- system check;
- verification automatizada.

Exemplos de regras potencialmente automatizáveis neste projeto incluem:

- impedir dependências proibidas entre camadas;
- impedir código de laboratório de entrar no caminho de produção;
- impedir acesso indevido do domínio a detalhes de Playwright;
- detectar ausência de metadata ou rastreabilidade obrigatória;
- garantir constraints importantes no banco;
- validar contratos estruturados;
- impedir padrões de código já identificados como fonte recorrente de bugs.

Não construir tooling preventivamente para problemas puramente hipotéticos.

Construir o lever quando houver:

- repetição;
- risco relevante;
- alto custo de detecção manual;
- benefício claro de reprodutibilidade;
- regra arquitetural importante que possa ser imposta mecanicamente.

### 7.8 Prefer structural enforcement

Quando uma regra importante puder ser expressa de forma confiável em:

- código;
- tipos;
- schemas;
- constraints;
- linters;
- checks;
- interfaces;
- configuração;
- testes automatizados;

preferir enforcement estrutural à dependência exclusiva de documentação ou
instruções para agentes.

Usar documentação para explicar intenção.

Usar tooling para impor mecanicamente o que puder ser imposto mecanicamente.

Exemplo conceitual:

Em vez de apenas documentar:

```text
Views não devem conter regra clínica.
```

quando viável, criar fronteiras e checks que dificultem ou impeçam dependências
incorretas entre a camada web e o domínio.

### 7.9 Make the correct path the easy path

APIs internas, helpers, CLIs e abstrações devem favorecer o uso correto.

Quando possível:

- oferecer uma forma canônica simples de realizar uma operação;
- evitar APIs que facilitem estados inválidos;
- fornecer mensagens de erro úteis;
- validar inputs cedo;
- usar tipos e schemas para reduzir ambiguidade;
- expor defaults seguros;
- tornar operações comuns fáceis de compor;
- tornar operações destrutivas explícitas.

Ferramentas destinadas a agentes devem, quando apropriado:

- possuir `--help` útil;
- produzir erros acionáveis;
- oferecer saída estruturada;
- evitar interação humana desnecessária;
- suportar `--dry-run` para operações potencialmente destrutivas.

### 7.10 Encode lessons in structure

Se uma mesma instrução precisar aparecer repetidamente em:

- prompts;
- reviews;
- slices;
- comentários;
- documentação operacional;

avaliar se a lição deveria ser codificada em:

- estrutura de diretórios;
- API;
- lint;
- teste;
- type system;
- constraint;
- helper;
- ferramenta;
- configuração central;
- documentação canônica única.

Evitar repetir regras globais em todos os prompts.

Cada regra deve possuir uma fonte canônica sempre que possível.

### 7.11 Refactoring discipline

Refactoring deve:

- preservar comportamento salvo quando a change explicitamente o altera;
- permanecer proporcional ao objetivo da change;
- possuir evidência apropriada de segurança;
- reduzir complexidade real;
- não ser usado como justificativa para redesenhar áreas não relacionadas.

Antes de refatorar, determinar qual comportamento precisa permanecer estável.

Refactors amplos não devem ser introduzidos incidentalmente dentro de slices
pequenos.

### 7.12 Tooling versus YAGNI

`Build the Lever` e YAGNI são complementares.

Use esta heurística:

```text
problema isolado
    -> resolva diretamente

problema reaparece
    -> observe o padrão

problema recorrente, arriscado ou caro de revisar
    -> considere construir o lever
```

Não tratar essa sequência como contagem rígida.

Um risco suficientemente alto pode justificar enforcement estrutural na
primeira ocorrência.

---

## 8. Política de testes e failing-before evidence

### Princípio geral

Toda mudança de comportamento deve possuir **evidência reproduzível de falha
antes da implementação**, quando isso for tecnicamente possível e
proporcional.

TDD é o método preferencial quando existe um seam de teste apropriado.

Fluxo:

```text
RED -> GREEN -> REFACTOR
```

### TDD obrigatório quando houver seam prática

Usar TDD especialmente para:

- regras de negócio;
- parsers;
- services;
- transformações;
- validações;
- queries;
- persistência;
- bugs com reprodução automatizável;
- contratos internos determinísticos.

Priorizar testes unitários para regras de negócio e parsers.

Usar testes de integração para:

- management commands;
- queries;
- persistência;
- fronteiras entre componentes.

### Quando um teste RED tradicional for inadequado

Não criar teste artificial, frágil ou desproporcional apenas para cumprir a
forma do TDD.

Se um teste automatizado prévio exigir infraestrutura muito maior que a
mudança ou não representar adequadamente a falha, usar a forma executável mais
próxima de failing-before evidence, por exemplo:

- cenário Playwright;
- reprodução por CLI;
- script de reprodução;
- integration check;
- snapshot;
- LLM eval;
- verification específica do produto.

A ausência de um teste RED tradicional deve ser explicitamente justificada no
relatório do slice.

Não é permitido simplesmente omitir evidência prévia da falha sem
justificativa.

### Bugs

Ao corrigir bug, adicionar teste de regressão ou caracterização sempre que
houver seam prática e estável.

### Dados

Usar somente fixtures:

- sintéticas;
- anônimas;
- adequadas ao ambiente de desenvolvimento.

Não usar dados clínicos reais para testes, screenshots, traces, relatórios ou
evidências de desenvolvimento.

---

## 9. Tests versus Verification

Testes e verification possuem funções relacionadas, mas diferentes.

### Tests

Provam componentes e contratos internos, por exemplo:

- parser produz resultado esperado;
- service aplica regra corretamente;
- query ordena corretamente;
- estado persiste;
- endpoint retorna contrato válido.

### Verification

Prova que os acceptance criteria da mudança funcionam na superfície realista
do produto.

Pode envolver:

- aplicação em execução;
- browser;
- Playwright;
- banco;
- jobs;
- integração entre componentes;
- CLI de verificação;
- screenshots;
- traces;
- comportamento de LLM;
- cenários end-to-end.

Testes passando não são, sozinhos, prova de que uma feature está pronta quando
os acceptance criteria exigem comportamento de runtime.

A infraestrutura de verification deve crescer incrementalmente junto com as
features.

Não construir framework genérico sem necessidade concreta.

A suíte de verificação do portal implantado (sessões efêmeras + smoke por
browser + skill MCP) é uma camada complementar sob demanda, documentada em
`docs/dev-verification.md`: nunca roda automaticamente, nunca é exigida
pelos gates oficiais e só executa em janela dev autorizada com dataset
fictício confirmado e workers parados.

---

## 10. Política de slices

### Localização

Para novas changes, usar:

```text
openspec/changes/<change>/slices/
```

com nomes descritivos, por exemplo:

```text
slice-001-import-report.md
slice-002-process-report.md
```

Changes legadas podem manter layout anterior.

Não migrar arquivos antigos somente para uniformizar estrutura.

`tasks.md` deve apontar explicitamente para o contrato de slice correspondente
quando aplicável.

### Conteúdo

Um slice deve definir pelo menos:

- objetivo;
- requisitos cobertos;
- referências necessárias;
- acceptance criteria;
- expected blast radius;
- estratégia de teste/verification;
- comandos obrigatórios específicos quando existirem;
- condições de bloqueio relevantes.

Não repetir integralmente as Engineering Policies neste arquivo.

Referenciar `AGENTS.md`.

### Contexto fresh

O slice deve permitir que um worker com contexto fresh reconstrua a tarefa por
referências.

Evitar copiar grandes blocos de:

- proposal;
- design;
- specs;
- código;
- políticas globais.

Referenciar a fonte canônica.

### Blast radius

O slice descreve um **expected blast radius**, não uma lista rígida e
imutável de arquivos.

Se for necessário tocar arquivo adicional:

- fazê-lo somente quando necessário;
- justificar no relatório;
- manter a mudança mínima.

Se a expansão indicar:

- nova arquitetura;
- novo requisito;
- mudança material de escopo;
- risco não previsto;

não continuar silenciosamente.

Escalar.

---

## 11. Protocolo de execução de um slice

### Worker

O worker:

1. recebe fresh context;
2. lê `AGENTS.md`;
3. lê as referências explícitas do slice;
4. valida que o contrato ainda corresponde ao código real;
5. produz failing-before evidence quando aplicável;
6. implementa a menor mudança correta;
7. executa testes e validações relevantes;
8. executa verification apropriada;
9. produz o relatório obrigatório;
10. retorna `READY_FOR_REVIEW`.

O worker não:

- marca `tasks.md` como concluído;
- cria commit;
- faz push;
- arquiva change;
- altera silenciosamente requisitos aprovados;
- inicia nested orchestration por conta própria.

Se uma decisão nova for necessária, retorna:

```text
BLOCKED_NEEDS_DECISION
```

### Revisão independente do slice

O reviewer fresh e read-only:

1. lê o contrato do slice;
2. lê as referências relevantes;
3. inspeciona o código e diff independentemente;
4. confronta implementação com acceptance criteria;
5. avalia testes e evidências;
6. verifica aderência às Engineering Policies quando relevante;
7. classifica findings.

Severidades:

- P0: bloqueador crítico;
- P1: deve ser corrigido antes do aceite;
- P2: melhoria não bloqueadora.

Quando identificar uma classe de problema recorrente, o reviewer deve
considerar sugerir um **lever estrutural**, como lint, check, constraint, teste
ou ferramenta reutilizável.

Essa sugestão não autoriza automaticamente construir o lever dentro do slice
atual se estiver fora do escopo.

### Correções

O loop pode executar correções limitadas conforme definido pelo controller.

Não reiniciar indefinidamente.

Se o limite for excedido, escalar.

### Aceite

Um slice pode ser aceito quando:

- não há P0 não resolvido;
- não há P1 não resolvido;
- validations obrigatórias passam;
- acceptance criteria estão demonstrados;
- não há decisão humana pendente.

P2 isolado não reabre automaticamente o loop.

Após aceite, o controller:

- atualiza o estado da tarefa;
- registra evidências necessárias;
- cria commit quando previsto.

---

## 12. Autonomia do `/change-loop`

Ao iniciar `/change-loop` para uma change aprovada, considera-se autorizada a
progressão automática por todos os slices aprovados.

Fluxo normal:

```text
slice
-> worker
-> reviewer
-> corrections when needed
-> ACCEPTED
-> update tasks
-> atomic commit
-> next slice
```

Não pedir confirmação entre slices normais.

### Parar e escalar somente quando houver

- requisito ambíguo que afete comportamento;
- nova decisão de produto;
- nova decisão arquitetural material;
- incompatibilidade real entre design aprovado e código;
- aumento material de escopo;
- alteração de compatibilidade não prevista;
- migração/persistência não aprovada;
- risco novo de segurança, privacidade ou integridade;
- implicação clínica não coberta pelo contrato;
- falha persistente após limite de correções;
- limite de revisão excedido;
- falha de infraestrutura que impeça verification confiável;
- necessidade de ação destrutiva não previamente autorizada.

Estado de saída:

```text
NEEDS_HUMAN_DECISION
```

com:

- problema;
- evidência;
- opções;
- impacto;
- decisão necessária.

### Gate final

Após todos os slices:

```bash
./scripts/test-in-container.sh quality-gate
```

é obrigatório. Esse comando executa check, testes unitários, lint e typecheck;
não inclui testes de integração. Quando exigidos pela change ou pelas
fronteiras afetadas, executar separadamente:

```bash
./scripts/test-in-container.sh integration
```

Se houver impossibilidade técnica de executar o gate com evidência confiável,
reportar `NEEDS_HUMAN_DECISION`, sem declarar a change pronta.

Se o gate final falhar:

1. identificar a menor área responsável;
2. fazer uma tentativa de reparo direcionada;
3. executar fresh review read-only do reparo;
4. repetir os checks focados afetados e, após reparo de código, sempre executar
   novamente o gate final completo no estado reparado, incluindo integração e
   verification obrigatórias separadas;
5. somente após review e gates aprovados, o controller registra a evidência,
   atualiza tarefas aplicáveis e cria commit atômico do reparo quando previsto.

Resultados anteriores a uma nova alteração de código não comprovam o estado
final da change.

Se a falha persistir ou exigir redesign:

```text
NEEDS_HUMAN_DECISION
```

Não reiniciar toda a change automaticamente.

---

## 13. Relatório obrigatório do slice

Cada slice deve gerar:

```text
/tmp/sirhosp-slice-<ID>-report.md
```

O relatório deve conter:

### Status

- `READY_FOR_REVIEW`;
- `BLOCKED_NEEDS_DECISION`;
- ou status final registrado pelo controller.

### Requirements -> Evidence

Para cada requisito relevante:

- requisito;
- evidência;
- resultado.

### Arquivos alterados

Listar arquivos alterados e motivo.

Não repetir todo o Git diff no relatório.

### Failing-before evidence

Registrar:

- teste inicialmente falhando; ou
- reprodução executável equivalente;
- ou justificativa explícita quando não aplicável.

### Passing-after evidence

Registrar a evidência após a implementação.

### Comandos

Registrar:

- comandos relevantes executados;
- resultado;
- exit status quando útil.

### Evidência de verification

Registrar evidência de produto/runtime quando aplicável, como:

- scenario;
- screenshot;
- trace;
- Playwright;
- CLI;
- LLM eval.

### Scope deviations

Registrar qualquer arquivo ou área tocada fora do expected blast radius e a
justificativa.

### Levers identificados

Quando surgir uma classe de erro repetida ou uma regra importante que possa ser
automatizada, registrar brevemente:

- problema;
- possível enforcement;
- se pertence ou não ao escopo atual.

Não implementar automaticamente tooling fora do escopo apenas por identificá-lo.

### Riscos e pendências

Registrar somente riscos e pendências reais.

Não incluir dados reais ou sensíveis.

Não é obrigatório incluir fragments de código antes/depois.

O Git diff é a fonte canônica para mudanças de código.

Antes/depois deve preferencialmente descrever **comportamento observável**.

---

## 14. Git e publicação

### Worker e reviewer

Worker e reviewer não devem:

- criar commits;
- fazer push;
- mergear;
- arquivar change.

### Controller

Após aceitar um slice, o controller pode criar commit atômico e rastreável
quando isso fizer parte do workflow autorizado.

Um commit deve representar uma unidade coerente aceita.

### Push, merge e archive

Não realizar automaticamente:

- push remoto;
- merge;
- deploy;
- archive final da change;

sem autorização explícita, salvo se outro contrato do projeto definir
claramente essa autorização.

---

## 15. Definition of Done do slice

Um slice não está concluído apenas porque o código foi escrito.

Critérios:

- [ ] contrato do slice atendido;
- [ ] failing-before evidence registrada quando aplicável;
- [ ] testes relevantes passando;
- [ ] validações focadas aplicáveis passando;
- [ ] verification executada quando necessária;
- [ ] reviewer sem P0/P1 aberto;
- [ ] Engineering Policies respeitadas;
- [ ] relatório do slice produzido;
- [ ] sem credenciais ou dados reais no diff/evidências;
- [ ] markdown lint passando quando `.md` foi alterado;
- [ ] task atualizada pelo controller após aceite;
- [ ] commit criado pelo controller quando previsto.

---

## 16. Definition of Done da change

Antes de considerar uma change pronta para revisão humana final:

- [ ] todos os slices aprovados estão aceitos;
- [ ] `tasks.md` reflete corretamente o estado;
- [ ] `./scripts/test-in-container.sh check` sem erro;
- [ ] testes relevantes passando;
- [ ] `./scripts/test-in-container.sh lint` sem erro;
- [ ] `./scripts/test-in-container.sh typecheck` sem erro relevante ou com
      exceção explicitamente justificada;
- [ ] `./scripts/test-in-container.sh quality-gate` passando;
- [ ] markdown lint passando quando aplicável;
- [ ] acceptance criteria da change possuem evidência;
- [ ] artefatos OpenSpec estão coerentes com o resultado implementado;
- [ ] sem credenciais nem dados reais;
- [ ] commits são claros e rastreáveis;
- [ ] nenhuma decisão humana continua pendente.

Ao final:

```text
READY_FOR_HUMAN_FINAL_REVIEW
```

Archive/sync/publicação ocorrem conforme autorização.

---

## 17. Anti-patterns proibidos

- Não colocar lógica de negócio complexa em views, templates ou management
  commands.
- Não misturar scraping exploratório com código operacional de produção.
- Não acoplar seletores Playwright diretamente à estrutura instável do portal
  quando houver possibilidade de abstração apropriada.
- Não introduzir dependências pesadas sem justificativa arquitetural.
- Não persistir textos clínicos brutos fora do modelo/versionamento definido.
- Não versionar arquivos de debug contendo dados sensíveis.
- Não executar dois controllers de implementação simultaneamente.
- Não usar `poteto-mode` completo dentro de um worker de slice aprovado.
- Não permitir nested delegation não prevista dentro de worker/reviewer.
- Não alterar silenciosamente uma decisão OpenSpec aprovada.
- Não criar abstrações especulativas para necessidades futuras.
- Não duplicar regras globais em todos os slices.
- Não copiar grandes blocos de contexto quando uma referência canônica
  resolver.
- Não transformar P2 em loop infinito de polish.
- Não usar testes artificiais apenas para satisfazer formalmente TDD.
- Não considerar "testes passaram" equivalente a "acceptance criteria foram
  verificados".
- Não depender exclusivamente de instruções textuais para regras que possam
  ser impostas mecanicamente de forma confiável.
- Não criar tooling complexo apenas porque seria potencialmente útil no
  futuro.
- Não ignorar classes recorrentes de findings sem avaliar se merecem um lever
  estrutural.

---

## 18. Prompt de reentrada

```text
Read AGENTS.md and PROJECT_CONTEXT.md first.

Review the active OpenSpec change and determine its state before coding.

If the change is not yet approved for implementation:
- do not implement it;
- investigate or refine the OpenSpec artifacts as requested.

If using /slice-loop:
- execute exactly the selected approved slice;
- use a fresh worker and a fresh read-only reviewer;
- stop after that slice is accepted or requires human decision.

If using /change-loop:
- execute all already-approved slices sequentially;
- advance automatically after accepted slices;
- stop only for a real NEEDS_HUMAN_DECISION condition.

Treat the approved OpenSpec artifacts as the product/design contract.
Do not silently reopen approved design decisions.

Follow the Engineering Policies in AGENTS.md.
Do not repeat them into every slice.

Prefer the smallest correct change.
Use structural enforcement when a recurring or important rule can be encoded
reliably in lint, types, constraints, tests, checks, or tooling.
Do not build speculative tooling without a concrete need.

Use pi-subagents configuration as the authority for agent models.
Do not override models per call unless explicitly required.

Use TDD where a practical test seam exists.
Otherwise produce the closest reproducible failing-before evidence.

Use the official containerized validation commands.
Use product-level verification when acceptance criteria require runtime proof.

Generate /tmp/sirhosp-slice-<ID>-report.md for each slice.

Workers do not update task completion, commit, push, merge, or archive.
The controller performs task updates and commits only after slice acceptance.

Never use real patient data in tests, fixtures, traces, screenshots, or
development reports.
```

---

## 19. Segurança e dados clínicos

Este projeto trabalha com software destinado a contexto hospitalar.

Durante desenvolvimento:

- usar apenas dados sintéticos ou adequadamente anonimizados;
- não enviar dados reais de pacientes a ferramentas de desenvolvimento sem
  autorização e infraestrutura específica;
- não gravar PHI/PII real em:
  - prompts;
  - reports em `/tmp`;
  - screenshots;
  - vídeos;
  - traces;
  - fixtures;
  - logs de teste;
  - commits;
- preservar auditabilidade de transformações e decisões relevantes;
- mudanças que possam alterar interpretação clínica ou priorização devem ter
  requisitos e verification explícitos;
- decisões clínicas ou de produto não devem ser inferidas silenciosamente por
  um agente executor.

Quando houver dúvida sobre impacto clínico, privacidade, segurança ou
integridade:

```text
NEEDS_HUMAN_DECISION
```
