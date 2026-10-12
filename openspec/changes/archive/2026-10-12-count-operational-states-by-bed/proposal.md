# Proposal

## Why

A diretoria conferiu o card `Estados operacionais informados` da página
`/beds/` contra os demais agregados da mesma página e encontrou disparidade
num dia específico. A causa é estrutural: esse card é o único agregado da
página contado **por linha bruta do censo**, enquanto os demais contam
entidades deduplicadas (pacientes por prontuário em grupo oficial; posições
físicas na ponte v3/v4). Linhas repetidas, leitos com estados divergentes e
linhas sem leito inflam os números do card sem correspondência física,
quebrando a conferência aritmética que a diretoria faz entre cards.

Além do número correto, falta na página a **prova auditável** de como o
número foi obtido: hoje a evidência por unidade existe, mas o agregado não
é clicável nem fecha publicamente com os casos problemáticos (conflitos,
duplicadas, linhas sem leito).

## What Changes

- Contar os estados operacionais do card por **leito (posição física)**, não
  por linha: leitos cujas linhas concordam contam 1 vez no seu estado;
  leitos com estados divergentes (incluindo ocupado + marcador operacional
  no mesmo leito) não entram em nenhum estado e viram contador visível de
  divergência; linhas repetidas do mesmo estado colapsam; linhas sem leito
  saem do badge e viram contador separado.
- Precedência explícita: **consenso da fonte** — o projeto não escolhe
  vencedor para estados divergentes do mesmo leito (mesma convenção de v3/v4
  para conflito de posição).
- Elevar o schema do reconciliation v5 persistido (3 → 4) com as novas
  chaves agregadas; measurements antigos (schema 3) continuam renderizando a
  semântica de linha, sem re-materialização.
- Nova página autenticada `beds/estados-operacionais/` vinculada ao
  `measurement` exato (imutável), acessível a partir do card, mostrando por
  setor: leitos inequívocos por estado, leitos com estados divergentes,
  linhas repetidas colapsadas, casos ocupado + estado e linhas sem leito,
  com fechamento aritmético contra o card.
- Avisar na página de detalhe quando a foto consultada não for mais a mais
  recente.
- Sem dados nominais na página de detalhe: linhas operacionais exibem
  apenas estado, leito e setor (sem nome cru nem prontuário).

Decisões aprovadas pela operação:

1. histórico imutável — nenhum caminho de re-materialização de runs
   antigos; o dia conferido pela diretoria permanece com a semântica de
   linha;
2. linhas sem leito ficam fora do badge, visíveis apenas no detalhe;
3. a página de detalhe inclui aviso de foto não mais recente.

### Não-objetivos

- Alterar a contagem de pacientes, a taxa oficial ou qualquer ponte v1–v4.
- Alterar a lista de unidades (evidência por unidade permanece por linha,
  com seus casos factuais `estados informados para o mesmo leito`).
- Re-materializar ou corrigir retroativamente measurements persistidos.
- Exportação CSV da página de detalhe (pode entrar depois, se solicitado).
- Novos modelos, migrations ou infraestrutura.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `bed-status-capacity-view`: o requisito de sumário da situação real passa
  a contar estados operacionais por leito (com exclusão explícita de
  divergentes, duplicadas e sem leito); novo requisito para a página de
  detalhe por setor com fechamento aritmético e privacidade.

## Impact

- `apps/census/occupancy.py`: `_calculate_v5` (contagem por posição),
  allowlist e `_reconciliation_v5_json` (schema 4), `_v5_real_totals`
  (leitura das novas chaves com fallback para schema 3), compartilhamento
  do classificador por chave entre materialização e apresentação.
- `apps/census/views.py` + `apps/census/urls.py`: nova view autenticada
  vinculada ao measurement.
- Novo template `apps/census/templates/census/bed_operational_detail.html`
  e link no card de `bed_status.html`.
- Testes: unitários de materialização/reconciliation, de view e de
  fechamento aritmético card ↔ detalhe; regressão de schemas antigos.
- Risco principal: mudança de significado dos números do card a partir dos
  novos runs (documentada no subtítulo do card) e necessidade de fallback
  correto para measurements schema 3.
