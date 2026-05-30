#!/usr/bin/env bash
# Exporta o último snapshot do censo como CSV para /tmp/censo-snapshot.csv
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

docker compose -f compose.yml -f compose.dev.yml exec -T web \
  uv run --no-sync python manage.py shell << 'PYEOF' > /tmp/censo-snapshot.csv
import csv, sys
from django.db.models import Max
from apps.census.models import CensusSnapshot

latest = CensusSnapshot.objects.aggregate(m=Max('captured_at'))['m']
if not latest:
    print('Nenhum snapshot encontrado.', file=sys.stderr)
    sys.exit(1)

rows = CensusSnapshot.objects.filter(captured_at=latest).order_by('setor', 'leito')

fields = [
    'captured_at', 'setor', 'setor_codigo', 'leito', 'prontuario', 'nome',
    'especialidade', 'data_internacao', 'tempo_internacao',
    'data_movimentacao', 'tipo_alta', 'origem', 'bed_status',
]
writer = csv.writer(sys.stdout)
writer.writerow(fields)
for r in rows:
    writer.writerow([getattr(r, f) for f in fields])
PYEOF

echo "OK — $(wc -l < /tmp/censo-snapshot.csv) linhas em /tmp/censo-snapshot.csv"
