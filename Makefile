# Blastradar — task runner
#
# Targets are stubs for now; each is implemented in the phase noted below.
# See PROGRESS.md for phase status and CLAUDE.md for the architectural rules
# these targets must honor (notably: `demo` runs offline in <60s, rule 3).

.PHONY: help demo demo-live test seed record-fixtures

help:
	@echo "Blastradar targets:"
	@echo "  make demo             Run the full pipeline on recorded fixtures, no DataHub (<60s)"
	@echo "  make demo-live        Run the full pipeline against a real local DataHub"
	@echo "  make test             Run the pytest suite (fixtures double as tests)"
	@echo "  make seed             Seed a local DataHub with the demo ML lineage graph"
	@echo "  make record-fixtures  Capture live DataHub responses into tests/fixtures"

demo:  ## Offline demo against recorded fixtures (Phase 2)
	@echo "TODO(Phase 2): run pipeline on tests/fixtures with no DataHub instance."

demo-live:  ## Live demo against a local DataHub (Phase 2)
	@echo "TODO(Phase 2): run pipeline against a real local DataHub."

test:  ## Run the test suite (Phase 2)
	@echo "TODO(Phase 2): pytest."

seed:  ## Seed a local DataHub with the demo ML graph (Phase 2)
	@echo "TODO(Phase 2): python scripts/seed_ml_graph.py"

record-fixtures:  ## Record live DataHub responses into fixtures (Phase 2)
	@echo "TODO(Phase 2): python scripts/record_fixtures.py"
