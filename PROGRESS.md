# Blastradar — Progress

Read this at the start of every session. Update it as phases complete, decisions
get made, and issues surface.

Hackathon: DataHub Agent Hackathon. Deadline: **2026-08-10**.

## Phase checklist

- [~] **Phase 0 — Foundations and verification** (IN PROGRESS — blocked on live DataHub)
      - [x] Repo skeleton + tooling; `.venv` on Python 3.12.7.
      - [x] Task 1: `acryl-datahub==1.6.0.15` installed, introspected, docs cross-checked;
            `docs/API-NOTES.md` filled with VERIFIED signatures; dep pinned in pyproject.
      - [x] Tasks 2–4 scripts written + SDK calls validated offline
            (`verify_cll.py`, `seed_ml_graph.py`, `verify_chain.py`, `_datahub_env.py`).
      - [ ] **BLOCKED:** run Tasks 2–4 against a live DataHub. Needs (a) Docker/GMS up
            at `:8080`, (b) a `.env` with `DATAHUB_GMS_TOKEN` (see `.env.example`).
      - [ ] LIVE-VERIFY items (see API-NOTES): column-level edges exist in the datapack;
            schemaField `sources` are lineage-traversable; `document` entity + `raiseIncident`
            available on the quickstart image.
- [ ] **Phase 1A — SQL delta analyzer**
      sqlglot-based before/after column diff (dropped / renamed / retyped), with
      SELECT * expansion via DataHub schema metadata.
- [ ] **Phase 1B — Lineage walker**
      URN resolver + deterministic multi-hop column-level traversal down to ML
      entities.
- [ ] **Phase 1C — Scoring and narration**
      Severity scoring (train vs. inference) and the single LLM narration call.
- [ ] **Phase 1D — Write-back and PR comment**
      Incidents / tags / documents into DataHub Core, plus the rendered PR comment.
- [ ] **Phase 2 — Fixtures and reproducibility**
      `make demo` (offline fixtures, <60s) and `make demo-live` (real DataHub);
      fixtures double as the test suite.
- [ ] **Phase 3 — Docs, skill, and packaging**
      README, architecture docs, agent skill, and packaging for submission.

## Decisions made during build

- **SDK pinned:** `acryl-datahub==1.6.0.15`, Python **3.12.7** venv (`.venv/`).
  3.11 unavailable locally; 3.13 avoided (SDK-lag risk).
- **Client strategy:** use the new experimental `datahub.sdk.DataHubClient` for
  entities + column-level lineage (`client.lineage.get_lineage`), and drop to
  `DataHubGraph` for schema reads and GraphQL. Pin the version because `datahub.sdk`
  is experimental.
- **Column-level lineage is a first-class SDK call:** `get_lineage(source_urn=...,
  source_column=..., direction=..., max_hops=...)` returns `LineageResult.paths[].column_name`.
  This is the walker's core primitive (Phase 1B).
- **Seed via low-level MCP + aspect classes** (not the partial new-SDK MLModel),
  because `MLModelPropertiesClass` alone carries groups/mlFeatures/deployments/
  trainingJobs/hyperParams/metrics — one aspect, full control, idempotent.
- **Feature `sources` use schemaField (column-level) URNs, not dataset URNs** — the
  docs example is dataset-level; our premise needs column-level. (See API-NOTES
  discrepancy note.)
- **Write-back mapping (DataHub Core only):** incident = `raiseIncident` GraphQL;
  tag = `GlobalTagsClass`; document = new `datahub.sdk.document.Document`
  (`set_title`/`set_text`/`add_related_asset`).
- **MCP server not on the critical path:** deterministic core calls the Python SDK
  directly; the separate `mcp-server-datahub` package is optional (decision pending).

## Known issues / deferred

- **DataHub was DOWN during Phase 0** (Docker daemon not running, GMS `:8080`
  unreachable, no `.env`). Tasks 2–4 are written and offline-validated but **not
  run**. Bring up `datahub docker quickstart` + add `.env`, then run:
  `verify_cll.py` → `seed_ml_graph.py` → `verify_chain.py`.
- **LIVE-VERIFY (must confirm before Phase 1 relies on them):** column-level edges
  actually present in showcase-ecommerce; schemaField `sources` produce traversable
  lineage; `document` entity + `raiseIncident` mutation exist on the quickstart image.
- **Anthropic SDK deferred to Phase 1C** (narration) — version not yet verified.
- `datahub.sdk` emits an `ExperimentalWarning`; import path may change when it
  stabilizes.
