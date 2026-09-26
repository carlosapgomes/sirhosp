## ADDED Requirements

### Requirement: Navegação autorizada expõe Estatísticas na ordem operacional

O portal SHALL exibir o item `Estatísticas` entre `Leitos` e `Fluxo Hospitalar`
somente para usuários autorizados e SHALL indicar seu estado ativo na página do
relatório.

#### Scenario: Usuário autorizado visualiza o item

- **WHEN** um usuário com permissão de consulta estatística visualiza o menu
- **THEN** o item `Estatísticas` aparece imediatamente depois de `Leitos`
- **AND** imediatamente antes de `Fluxo Hospitalar`
- **AND** aponta para `/statistics/`

#### Scenario: Usuário sem permissão visualiza o menu

- **WHEN** um usuário não possui permissão de consulta estatística
- **THEN** o item `Estatísticas` não é renderizado

#### Scenario: Página estatística marca item ativo

- **WHEN** um usuário autorizado acessa `/statistics/`
- **THEN** o item `Estatísticas` é apresentado como ativo
