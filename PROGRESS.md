# Blastradar — Progress

Read this at the start of every session. Update it as phases complete, decisions
get made, and issues surface.

Hackathon: DataHub Agent Hackathon. Deadline: **2026-08-10**.

## Phase checklist

- [x] **Phase 0 — Foundations and verification** (COMPLETE — verified against live DataHub)
      - [x] Repo skeleton + tooling; `.venv` on Python 3.12.7.
      - [x] Task 1: `acryl-datahub==1.6.0.15` installed, introspected, docs cross-checked;
            `docs/API-NOTES.md` filled with VERIFIED signatures; dep pinned in pyproject.
      - [x] Task 2 `[run]`: **column-level lineage CONFIRMED present** in the ecommerce
            bootstrap datapack (`verify_cll.py`).
      - [x] Task 3 `[run]`: `seed_ml_graph.py` created 2 groups, 4 models, 3 feature
            tables, 12 features, 2 deployments, 4 training runs. `seeded_urns.json` written.
      - [x] Task 4 `[run]`: `verify_chain.py` walked `customers.customer_since` →
            feature → 4 models (all trained-on) → churn_model_v3 → 2 live deployments.
      - [ ] Deferred to Phase 1D: incident/tag/document **write-back** not yet run live.
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
- **Feature `sources` are DATASET-level** (GMS rejects schemaField URNs with 422 —
  live-corrected). Column precision is preserved by recording the exact source
  column in the feature's `customProperties["blastradar.source_column"]`.
- **Walker is a HYBRID traversal (live-decided):** column-level dataset lineage for
  propagation → table-level lineage into features (column precision from the custom
  property) → table-level into models → **aspect reads** for deployments and
  training-run inputs (model→deployment `DeployedTo` is NOT lineage-traversable).
  See the traversability table in API-NOTES.
- **Local quickstart has auth DISABLED** → tokenless connections work; the helper
  now allows no token. `~/.datahubenv` is broken (`server: datahub`), so the
  `datahub` CLI needs `DATAHUB_GMS_URL=http://localhost:8080` overridden.
- **Substrate:** the ecommerce showcase loads via `datahub docker ingest-sample-data`
  (default bootstrap pack). `--pack showcase-ecommerce` resolves to an EMPTY file on
  this build — do not use it.
- **Write-back mapping (DataHub Core only):** incident = `raiseIncident` GraphQL;
  tag = `GlobalTagsClass`; document = new `datahub.sdk.document.Document`
  (`set_title`/`set_text`/`add_related_asset`).
- **MCP server not on the critical path:** deterministic core calls the Python SDK
  directly; the separate `mcp-server-datahub` package is optional (decision pending).

## Known issues / deferred

- **Index lag after emit:** new entities/edges take ~minutes to appear in the
  search/graph index (aspect reads are immediately consistent). Scripts that rely on
  `get_lineage`/search should tolerate lag. `seed_ml_graph.py` uses DB-backed
  `list_all_entity_urns` for discovery to avoid this.
- **Write-back NOT yet run live** (`raiseIncident` GraphQL, tag aspect, `document`
  entity). Still `[docs]`/`[introspect]` — validate in Phase 1D. Confirm the
  `document` entity + `raiseIncident` mutation exist on this GMS image when we get there.
- **`_short()` URN display in verify_chain** truncates mlFeature names cosmetically
  (shows the feature-table segment). Harmless; tidy if it bothers.
- **Anthropic SDK deferred to Phase 1C** (narration) — version not yet verified.
- `datahub.sdk` emits an `ExperimentalWarning`; import path may change when it
  stabilizes.
