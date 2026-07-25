# Blastradar — task runner.
#
# Two reproduction paths (architectural rule 3):
#   make demo       — the whole pipeline on RECORDED fixtures. No DataHub, no network,
#                     no API key. Under 60 seconds. This is the "stranger in 60s" path.
#   make demo-live  — the whole pipeline against a REAL local DataHub (docker stack).
#
# See PROGRESS.md for build state and CLAUDE.md for the rules these targets honor.

.PHONY: help demo examples demo-live test seed record-fixtures writeback-demo clean-examples

PY := .venv/bin/python

help:
	@echo "Blastradar targets:"
	@echo "  make demo             Full pipeline on recorded fixtures — no DataHub/network/key, <60s"
	@echo "  make examples         Regenerate all three sample reports under examples/ (md + json)"
	@echo "  make demo-live        Full pipeline against a real local DataHub (stands up the docker stack)"
	@echo "  make test             Run the pytest suite (offline — fixtures double as tests)"
	@echo "  make seed             Seed a local DataHub with the demo ML lineage graph"
	@echo "  make record-fixtures  Re-record live DataHub responses into tests/fixtures/recorded/"
	@echo "  make writeback-demo   Analyze the demo PR against a live DataHub (dry-run unless WRITE=1)"

# --- Offline path (recorded fixtures) --------------------------------------- #
demo:  ## Offline demo against recorded fixtures — prints the comment, writes it to examples/
	@$(PY) scripts/demo.py --scenario critical

examples:  ## Regenerate all three sample reports (critical / medium / clean) as md + json
	@$(PY) scripts/demo.py --scenario all --quiet
	@echo "Regenerated examples/*.md + examples/*.json"

# --- Live path (real DataHub) ----------------------------------------------- #
demo-live:  ## Stand up DataHub, seed, and run the pipeline with write-back enabled
	@bash scripts/demo_live.sh

# Phase 1D: analyze the demo PR and write findings back into a live local DataHub.
# Dry-run by default (safe); `make writeback-demo WRITE=1` performs the writes.
writeback-demo:  ## Analyze the demo PR against a live DataHub
	@DATAHUB_GMS_URL=$${DATAHUB_GMS_URL:-http://localhost:8080} \
	 TOOLS_IS_MUTATION_ENABLED=$(if $(WRITE),true,false) \
	 PYTHONPATH=src $(PY) -m blastradar.cli analyze \
	   --changes demo-repo/demo-pr.json \
	   --pr-repo order-entry/analytics --pr-number 42 \
	   --pr-url https://github.com/order-entry/analytics/pull/42 \
	   --no-post-comment $(if $(WRITE),,--dry-run)

# --- Tests + fixtures ------------------------------------------------------- #
test:  ## Run the pytest suite (offline)
	$(PY) -m pytest -q

seed:  ## Seed a local DataHub with the demo ML graph
	$(PY) scripts/seed_ml_graph.py

record-fixtures:  ## Re-record live DataHub responses into fixtures (needs a live, seeded DataHub)
	$(PY) scripts/record_fixtures.py
