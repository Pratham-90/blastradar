#!/usr/bin/env bash
#
# make demo-live — the full Blastradar pipeline against a REAL local DataHub.
#
# The offline `make demo` is for a stranger with 60 seconds; this is the live path
# (architectural rule 3). It stands up DataHub's docker-compose stack, waits for it
# to be healthy, loads the ecommerce substrate + the demo ML graph, then runs
# Blastradar with write-back ENABLED so incidents/tags/documents actually land in
# DataHub — nobody hits the TOOLS_IS_MUTATION_ENABLED wall.
#
# DataHub's stack is stood up via `datahub docker quickstart`, which pulls and runs
# the official, version-matched docker-compose quickstart for the installed
# acryl-datahub (hand-vendoring that large multi-service compose would rot — the same
# reason our fixtures are generated, not hand-written). First run pulls several GB.
#
# Idempotent: safe to re-run. If DataHub is already healthy it skips the quickstart.

set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
DATAHUB=.venv/bin/datahub
GMS_URL="${DATAHUB_GMS_URL:-http://localhost:8080}"

# Live path: never let a stray replay env var divert us to fixtures.
unset BLASTRADAR_REPLAY

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# 0. Preconditions -----------------------------------------------------------
command -v docker >/dev/null 2>&1 || die "docker not found. Install Docker Desktop and retry."
docker info >/dev/null 2>&1       || die "Docker daemon not running. Start Docker Desktop and retry."
[ -x "$PY" ]      || die "missing .venv — create it: python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
[ -x "$DATAHUB" ] || die "missing datahub CLI in .venv — run: .venv/bin/pip install -e '.[dev]'"

# 1. Stand up DataHub (official quickstart compose stack; idempotent) --------
if curl -sf "$GMS_URL/health" >/dev/null 2>&1; then
  log "DataHub already healthy at $GMS_URL — skipping quickstart."
else
  log "Standing up DataHub via docker-compose quickstart (first run pulls several GB — be patient)..."
  "$DATAHUB" docker quickstart
fi

# 2. Wait for GMS health -----------------------------------------------------
log "Waiting for DataHub GMS to report healthy at $GMS_URL ..."
for i in $(seq 1 60); do
  if curl -sf "$GMS_URL/health" >/dev/null 2>&1; then echo "  healthy."; break; fi
  [ "$i" -eq 60 ] && die "GMS did not become healthy within ~5 minutes."
  sleep 5
done

# 3. Ingest the ecommerce sample substrate (the datasets the ML graph builds on) --
log "Ingesting the ecommerce sample data (the substrate the ML graph builds on)..."
DATAHUB_GMS_URL="$GMS_URL" "$DATAHUB" docker ingest-sample-data || \
  echo "  (sample-data ingest returned non-zero — continuing; it is usually already present)"

# 4. Seed the demo ML lineage graph -----------------------------------------
log "Seeding the demo ML lineage graph (models, features, deployments, training runs)..."
DATAHUB_GMS_URL="$GMS_URL" $PY scripts/seed_ml_graph.py

# 5. Run Blastradar LIVE with write-back ENABLED ----------------------------
#    TOOLS_IS_MUTATION_ENABLED=true is set here automatically so the write-back
#    actually happens (this is the single most common setup miss).
log "Running Blastradar against the live DataHub — write-back ENABLED..."
DATAHUB_GMS_URL="$GMS_URL" \
TOOLS_IS_MUTATION_ENABLED=true \
PYTHONPATH=src $PY -m blastradar.cli analyze \
  --changes demo-repo/demo-pr.json \
  --pr-repo order-entry/analytics --pr-number 42 \
  --pr-url https://github.com/order-entry/analytics/pull/42 \
  --write-back --no-post-comment

log "Done."
echo "Open the DataHub UI at ${GMS_URL/8080/9002} (login: datahub / datahub) to see the"
echo "incidents on the customers dataset, the pending-upstream-change tags on the models,"
echo "and the saved knowledge-base document. Re-run this script — it stays idempotent."
