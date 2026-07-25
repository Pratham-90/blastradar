# Blastradar — task runner
#
# Targets are stubs for now; each is implemented in the phase noted below.
# See PROGRESS.md for phase status and CLAUDE.md for the architectural rules
# these targets must honor (notably: `demo` runs offline in <60s, rule 3).

.PHONY: help demo demo-live test seed record-fixtures writeback-demo

PY := .venv/bin/python

help:
	@echo "Blastradar targets:"
	@echo "  make demo             Run the full pipeline on recorded fixtures, no DataHub (<60s)"
	@echo "  make demo-live        Run the full pipeline against a real local DataHub"
	@echo "  make writeback-demo   Analyze the demo PR + write back to a live DataHub (needs seed)"
	@echo "  make test             Run the pytest suite (fixtures double as tests)"
	@echo "  make seed             Seed a local DataHub with the demo ML lineage graph"
	@echo "  make record-fixtures  Capture live DataHub responses into tests/fixtures"

demo:  ## Offline demo against recorded fixtures (Phase 2)
	@echo "TODO(Phase 2): run pipeline on tests/fixtures with no DataHub instance."

demo-live:  ## Live demo against a local DataHub (Phase 2)
	@echo "TODO(Phase 2): run pipeline against a real local DataHub."

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

test:  ## Run the pytest suite
	$(PY) -m pytest -q

seed:  ## Seed a local DataHub with the demo ML graph
	$(PY) scripts/seed_ml_graph.py

record-fixtures:  ## Record live DataHub responses into fixtures (Phase 2)
	@echo "TODO(Phase 2): python scripts/record_fixtures.py"
