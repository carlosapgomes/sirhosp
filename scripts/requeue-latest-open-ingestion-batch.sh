#!/usr/bin/env bash
set -euo pipefail

# Reenfileira runs "running" do último batch de censo não finalizado.
# Uso:
#   ./scripts/requeue-latest-open-ingestion-batch.sh
# Variáveis opcionais:
#   COMPOSE_SERVICE=web   (serviço do Django no docker compose)

SERVICE="${COMPOSE_SERVICE:-web}"

PYTHON_CODE=$(cat <<'PY'
from django.db import transaction
from django.utils import timezone

from apps.ingestion.models import CensusExecutionBatch, IngestionRun

batch = (
    CensusExecutionBatch.objects
    .filter(finished_at__isnull=True)
    .order_by("-started_at")
    .first()
)

if batch is None:
    print("[requeue] Nenhum batch de censo em aberto (finished_at IS NULL).")
    raise SystemExit(0)

with transaction.atomic():
    # Lock no batch para evitar corrida com outra ação administrativa.
    batch = CensusExecutionBatch.objects.select_for_update().get(pk=batch.pk)

    base_qs = IngestionRun.objects.filter(batch=batch)
    before = {
        "queued": base_qs.filter(status="queued").count(),
        "running": base_qs.filter(status="running").count(),
        "succeeded": base_qs.filter(status="succeeded").count(),
        "failed": base_qs.filter(status="failed").count(),
    }

    running_ids = list(
        base_qs.filter(status="running").values_list("id", flat=True)
    )

    updated = (
        base_qs
        .filter(status="running")
        .update(
            status="queued",
            next_retry_at=None,
        )
    )

    after = {
        "queued": base_qs.filter(status="queued").count(),
        "running": base_qs.filter(status="running").count(),
        "succeeded": base_qs.filter(status="succeeded").count(),
        "failed": base_qs.filter(status="failed").count(),
    }

print("[requeue] Batch alvo:", batch.pk)
print("[requeue] started_at:", batch.started_at)
print("[requeue] enqueue_finished_at:", batch.enqueue_finished_at)
print("[requeue] finished_at:", batch.finished_at)
print("[requeue] status:", batch.status)
print("[requeue] status antes:", before)
print("[requeue] runs reenfileirados:", updated)
print("[requeue] status depois:", after)

if running_ids:
    preview = running_ids[:50]
    print("[requeue] IDs reenfileirados (até 50):", preview)
    if len(running_ids) > 50:
        print("[requeue] ... total IDs:", len(running_ids))
else:
    print("[requeue] Nenhum run em status running para reenfileirar.")

print("[requeue] Executado em:", timezone.now())
PY
)

echo "[requeue] Executando no serviço Docker: ${SERVICE}"
docker compose exec -T "${SERVICE}" uv run --no-sync python manage.py shell -c "$PYTHON_CODE"
