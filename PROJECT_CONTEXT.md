# PROJECT_CONTEXT.md

## 1. Propósito

Contexto técnico e de domínio para retomada rápida do desenvolvimento do
SIRHOSP e onboarding de colaboradores humanos ou agentes.

Este arquivo descreve principalmente:

- propósito do sistema;
- escopo;
- arquitetura de alto nível;
- fronteiras de responsabilidade;
- decisões e restrições duradouras;
- terminologia e contexto necessários para compreender o projeto.

As regras operacionais para agentes, execução de slices, testes, reviews,
commits e quality gates estão em `AGENTS.md` e não devem ser duplicadas aqui.

---

## 2. Sistema

### SIRHOSP — Sistema Interno de Relatórios Hospitalares

Sistema interno destinado à extração automatizada de dados clínicos do sistema
fonte hospitalar, armazenamento controlado em PostgreSQL e disponibilização de
informações derivadas para consulta e uso institucional.

O sistema deve apoiar, conforme os serviços implementados:

- consulta rápida de informações;
- busca textual;
- consolidação de dados clínicos;
- geração de resumos direcionados;
- gestão e acompanhamento de informações hospitalares.

Públicos e áreas de uso podem incluir:

- gestão;
- qualidade;
- jurídico;
- diretoria;
- gestão de prontuários;
- demais áreas autorizadas conforme evolução do produto.

O SIRHOSP não deve pressupor que todo dado capturado ou derivado pode ser
exposto indistintamente a qualquer perfil de usuário. Autorização, finalidade
de uso, rastreabilidade e proteção de dados devem ser consideradas nas features
que tratam informação clínica.

---

## 3. Escopo inicial

O escopo inicial prioriza:

- pacientes internados;
- pacientes atualmente internados;
- evoluções médicas;
- prescrições;
- dados necessários para composição dos serviços iniciais;
- primeiro serviço de alto valor: resumo de internação;
- autenticação local simples com perfis `admin` e `user`;
- execução programada de automações em horários ou ciclos definidos.

O escopo deve evoluir por mudanças explícitas e rastreáveis.

Funcionalidades novas não devem ser inferidas apenas porque seriam
tecnicamente convenientes.

---

## 4. Arquitetura de alto nível

O projeto adota inicialmente um **monólito modular Django**.

As principais áreas conceituais são:

### Portal web Django

Responsável por superfícies de interação com usuários, incluindo:

- autenticação;
- dashboard;
- busca;
- acesso aos serviços;
- interfaces administrativas.

Views e templates não devem absorver regras complexas que pertençam ao domínio.

### Domínio clínico

Responsável por representar e coordenar conceitos centrais do sistema, como:

- pacientes;
- internações;
- documentos clínicos;
- jobs relacionados ao domínio;
- dados e estados utilizados por serviços clínicos;
- resumos e outros produtos derivados.

Regras de negócio devem permanecer identificáveis e testáveis fora das
camadas de apresentação e integração.

### Conectores de ingestão

Responsáveis pela comunicação com sistemas fonte e pela transformação inicial
dos dados capturados.

Incluem:

- automações Playwright;
- parsers;
- rotinas de extração;
- adaptação de formatos externos para representações internas.

Código exploratório ou de laboratório deve permanecer separado do caminho
operacional de produção.

Os detalhes instáveis do sistema fonte não devem se espalhar pelo domínio.

### Persistência

PostgreSQL é a base principal para:

- persistência clínica;
- estados operacionais necessários;
- coordenação básica de jobs durante a fase inicial.

A persistência deve preservar separação entre:

- dados de origem;
- representações normalizadas;
- estados de processamento;
- resultados derivados quando aplicável.

### Coordenação operacional

A fase inicial utiliza principalmente:

- PostgreSQL;
- Django management commands;
- `systemd services`;
- `systemd timers`.

Não há Celery/Redis como infraestrutura obrigatória da fase 1.

### Processamento textual e LLM

O processamento textual ou assistido por LLM deve permanecer separado da
captura dos dados.

Essa camada pode consumir representações já obtidas e controladas pelo sistema
para produzir resultados derivados, como resumos.

Quando houver uso de LLM, devem permanecer rastreáveis, conforme aplicável:

- entrada utilizada;
- transformação realizada;
- versão da lógica ou prompt relevante;
- resultado produzido;
- relação com o dado de origem;
- estado de revisão ou processamento.

Decisões mais específicas pertencem às specs, designs ou ADRs correspondentes.

---

## 5. Fluxos operacionais atuais relevantes

O sistema atualmente possui ou prevê os seguintes mecanismos operacionais.

### Censo

O orquestrador adaptativo:

```text
run_adaptive_census_cycles --loop
```

coordena ciclos de censo conforme o estado operacional esperado.

### Ingestão

O worker contínuo:

```text
process_ingestion_runs --loop --sleep-seconds 5
```

processa runs previamente enfileirados.

### Sumários

Para processamento de sumários, o padrão operacional atual utiliza:

```text
process_summary_runs --pipeline --loop
```

### Verificação do portal dev

A suíte de verificação do portal implantado é uma camada complementar,
executada somente sob demanda do operador, nunca automaticamente e nunca
exigida pelos gates oficiais de CI:

- sessões efêmeras com revogação e timer (`scripts/verify_portal.py
  doctor/open/status/close/run`);
- smoke real por browser headless com evidências sanitizadas;
- verificação assistida por MCP através da skill `verify-sirhosp`.

Cada execução exige janela dev autorizada, dataset fictício confirmado,
workers parados e preflight `doctor` aprovado.

O runbook canônico é `docs/dev-verification.md`.

Detalhes de deploy e operação pertencem a:

- `deploy/README.md`;
- `deploy/systemd/`.

Este arquivo não deve duplicar a configuração operacional completa desses
componentes.

---

## 6. Restrições arquiteturais duradouras

Salvo decisão explícita registrada em ADR/OpenSpec:

- manter o projeto como monólito modular Django durante a fase 1;
- não introduzir Celery;
- não introduzir Redis;
- não introduzir microserviços;
- manter PostgreSQL como mecanismo principal de persistência e coordenação
  operacional básica;
- manter separação entre portal, domínio e conectores de ingestão;
- manter processamento textual/LLM desacoplado da captura;
- manter separação clara entre automação experimental e automação de produção;
- evitar dependências ou infraestrutura significativas para necessidades
  hipotéticas.

O MVP `resumo-evolucoes-clinicas` é fonte de aprendizado e reaproveitamento
técnico.

Ele não deve ser tratado automaticamente como arquitetura normativa do
SIRHOSP.

---

## 7. Dados clínicos, privacidade e segurança

Informação clínica deve ser tratada como dado sensível.

Não versionar:

- dados reais de pacientes;
- PDFs clínicos reais;
- dumps contendo dados reais;
- credenciais;
- tokens;
- arquivos de debug com informação sensível;
- screenshots ou traces com dados clínicos reais.

Ambientes e artefatos de desenvolvimento devem utilizar, sempre que possível:

- dados sintéticos;
- fixtures artificiais;
- dados adequadamente anonimizados quando explicitamente permitido.

Dados reais não devem ser introduzidos em:

- prompts de desenvolvimento;
- fixtures;
- testes;
- relatórios de slices;
- screenshots;
- vídeos;
- traces;
- commits;
- artefatos de debugging.

Mudanças que possam alterar:

- interpretação de informação clínica;
- priorização;
- comportamento de processamento clínico;
- exposição de dados;
- auditabilidade;
- integridade de dados;

devem possuir requisitos e decisões explícitas nos artefatos apropriados.

---

## 8. Auditabilidade e rastreabilidade

O projeto deve favorecer reconstrução posterior das decisões importantes.

Para mudanças relevantes, deve ser possível responder, a partir do repositório:

- qual problema estava sendo resolvido;
- qual comportamento era esperado;
- quais requisitos foram aprovados;
- quais decisões arquiteturais foram tomadas;
- quais limitações eram conhecidas;
- como a mudança foi implementada;
- como seu comportamento foi verificado.

Isso não significa documentar cada detalhe transitório da implementação.

A documentação deve priorizar decisões e contratos duradouros em vez de
reproduzir informação que já está representada de forma mais precisa pelo
código ou pelo histórico Git.

---

## 9. Fontes autoritativas e responsabilidade de cada artefato

A autoridade não é determinada apenas por data de modificação.

Cada artefato possui uma responsabilidade própria.

### `AGENTS.md`

Autoridade para:

- workflow de agentes;
- controllers;
- política de execução;
- política de testes e verification;
- quality gates;
- reviews;
- commits;
- condições de escalonamento;
- política de modelos e subagents.

### OpenSpec — specs

Autoridade para o comportamento atualmente especificado do produto dentro do
escopo correspondente.

### OpenSpec — active change

Uma change ativa descreve uma mudança proposta ou aprovada em relação ao
estado atual.

Ela não deve ser considerada automaticamente superior apenas por ser mais
recente.

Durante implementação de uma change aprovada, seus requisitos, design e slices
aprovados constituem o contrato da mudança.

### ADRs

Autoridade para decisões arquiteturais explicitamente registradas e seu
rationale.

Uma ADR só deixa de ser aplicável quando:

- substituída explicitamente;
- tornada obsoleta por outra decisão registrada;
- ou não for relevante ao escopo em questão.

### `docs/architecture.md`

Descreve a arquitetura atual de alto nível.

Deve ser mantido consistente com decisões arquiteturais aceitas.

### `PROJECT_CONTEXT.md`

Fornece orientação geral sobre:

- domínio;
- arquitetura;
- restrições duradouras;
- fronteiras;
- conceitos necessários para compreender o projeto.

Não é um substituto para specs, ADRs ou contratos de changes.

### `README.md`

Serve principalmente para apresentação, setup e orientação geral.

Não deve ser usado como fonte principal para resolver contradições
arquiteturais ou de requisitos quando houver artefato específico.

---

## 10. Resolução de conflitos entre documentação

Não usar a regra genérica:

> "o arquivo mais novo vence".

Quando dois artefatos parecerem conflitantes:

1. identificar a natureza da informação em conflito;
2. determinar qual tipo de artefato possui autoridade sobre aquela informação;
3. verificar se existe decisão explícita de substituição;
4. verificar o estado da change relevante;
5. não alterar comportamento silenciosamente se ainda houver ambiguidade.

Exemplos:

- regra de execução de agentes -> `AGENTS.md`;
- comportamento aprovado do produto -> spec relevante;
- mudança ainda em implementação -> OpenSpec change aprovada;
- decisão arquitetural -> ADR correspondente;
- visão geral da arquitetura -> `docs/architecture.md`.

Se a contradição não puder ser resolvida dessa forma, tratá-la como decisão
pendente, não como licença para escolher arbitrariamente uma interpretação.

---

## 11. OpenSpec e memória do desenvolvimento

OpenSpec é utilizado para tornar mudanças relevantes explícitas e
reconstruíveis.

De forma conceitual:

```text
proposal
    -> por que esta mudança existe

spec
    -> qual comportamento é esperado

design
    -> quais decisões estruturais foram aprovadas

tasks / slices
    -> como o trabalho aprovado foi decomposto para execução
```

Durante execução, evidências podem revelar que uma premissa do design está
incorreta.

Nesse caso, a documentação pode e deve ser atualizada.

O importante é que a mudança de decisão seja **explícita**, e não uma
divergência silenciosa entre implementação e design.

---

## 12. Slices

O desenvolvimento pode ser decomposto em slices verticais pequenos e
verificáveis.

Um slice não é uma nova especificação de produto.

Ele é uma unidade de execução derivada de uma change já suficientemente
definida.

Slices devem:

- manter relação clara com requisitos;
- possuir acceptance criteria verificáveis;
- limitar drift;
- permitir execução com contexto fresh por meio de referências explícitas;
- evitar duplicar grandes blocos de especificação ou design.

As regras detalhadas para criação, execução, review e aceite de slices estão em
`AGENTS.md` e nas skills/prompts correspondentes.

---

## 13. Tests e verification

O projeto distingue conceitualmente:

### Tests

Validam componentes e contratos do software.

Exemplos:

- regras de negócio;
- parsers;
- persistência;
- queries;
- services;
- endpoints;
- integração entre componentes.

### Verification

Demonstra que o comportamento solicitado funciona em uma superfície
representativa do produto.

Pode envolver:

- aplicação em execução;
- Playwright;
- browser;
- banco;
- jobs;
- screenshots;
- traces;
- CLIs;
- cenários end-to-end;
- avaliações de comportamento de LLM.

Verification deve crescer incrementalmente junto com as funcionalidades
implementadas.

Não construir infraestrutura genérica de verification apenas por antecipação.

Os procedimentos concretos pertencem a `AGENTS.md` e às ferramentas de
verification do projeto.

---

## 14. Princípios de evolução

Ao evoluir o SIRHOSP:

- preferir mudanças pequenas e verificáveis;
- preservar fronteiras existentes quando ainda forem adequadas;
- evitar generalização prematura;
- evitar infraestrutura baseada apenas em necessidades futuras imaginadas;
- registrar decisões estruturais duradouras;
- deixar detalhes implementacionais no código quando o código for a fonte mais
  precisa;
- manter documentação focada em intenção, contrato, decisão e contexto;
- criar ferramentas reproduzíveis quando uma operação importante começar a se
  repetir;
- usar evidência de execução para revisar suposições;
- não permitir que a conveniência de um agente redefina silenciosamente
  requisitos ou arquitetura.

---

## 15. Reentrada no projeto

Ao retomar desenvolvimento, a sequência conceitual é:

1. ler `AGENTS.md`;
2. ler este `PROJECT_CONTEXT.md`;
3. identificar OpenSpec changes ativas;
4. determinar se o trabalho está em:
   - investigação;
   - especificação/design;
   - execução de change aprovada;
   - verification;
   - encerramento;
5. consultar somente os artefatos necessários ao estágio atual;
6. seguir o controller apropriado definido em `AGENTS.md`.

Não presumir que uma change ativa está pronta para implementação apenas porque
existe.

Não presumir que o próximo passo seja escrever código antes de identificar o
estado atual da change.
