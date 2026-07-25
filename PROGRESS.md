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
- [x] **Phase 1A — SQL delta analyzer** (COMPLETE — 16 tests pass, pure/no DataHub)
      - [x] `models.py`: frozen dataclasses (`ChangeEvent`, `SqlFileChange`, `ModelDelta`,
            `UnresolvedProjection`, `ImpactPath`, `ScoredImpact`) + `SchemaProvider` protocol.
      - [x] `diff/extract.py`: git refs (`git show` before/after; add/delete/modify) + JSON stdin.
      - [x] `diff/sql_delta.py`: sqlglot projection resolve + diff → drop / rename / type-change;
            CTE & subquery `SELECT *` expand locally; external `SELECT *` → `UnresolvedProjection`
            marker (or expand via `SchemaProvider` — the Phase 1B wire-up). Parse errors raise
            `SqlDeltaError` naming the file.
      - [x] `tests/` + `tests/fixtures/sql/` (real .sql files): all 7 required cases + deleted/added.
- [x] **Phase 1B — Lineage walker** (COMPLETE — 24 tests pass; run live on the demo target)
      - [x] `datahub/client.py`: uniform wrapper, JSON-able returns (record-ready),
            retry+backoff, DEBUG logging, `observer` record hook for Phase 2.
      - [x] `datahub/resolver.py`: table→dataset (exact + platform priority; ties →
            AMBIGUOUS, never silently pick) + column→schemaField; `DataHubSchemaProvider`
            implements the Phase 1A `SchemaProvider` for external `SELECT *`.
      - [x] `datahub/walker.py`: deterministic BFS hybrid traversal → `ImpactGraph`;
            dedup entities but preserve all paths; cycle guard; hop cap (default 6);
            frontier ceiling → truncated. Training-set detection (`_training_evidence`).
      - [x] `datahub/urns.py` helpers; `scripts/run_walker.py` demo runner; `tests/test_walker.py`.
      - [x] Live result on `customers.customer_since`: 5 models + 4 deployments; churn v1/v2/v3
            + ltv_v1 TRAINED-ON, `reactivation_v1` inference-only (deployed). Matches Phase 0.
- [x] **Phase 1C — Scoring and narration** (COMPLETE — 40 tests pass; CLI run end-to-end)
      - [x] `scoring.py`: deterministic rules table as a module constant (`SEVERITY_RULES`),
            first-match-wins; every `ScoredImpact` carries a `reasons` tuple tracing to the
            table; one-level escalation for Tier1/Critical tag or owner-group; sort by
            severity → deployed → name.
      - [x] `narrate.py` + `prompts/narrate.md`: the single LLM call, pinned `claude-opus-4-8`,
            `effort: low` (temperature removed on 4.8), prose-only (can't add/remove/re-rank);
            full templated fallback on `--no-llm` or any API failure.
      - [x] `report.py`: deterministic markdown + machine-readable JSON; guard so a truncated/
            unresolved walk is reported as "incomplete", never a false all-clear.
      - [x] `cli.py` (click): `blastradar analyze --base/--head` with `--no-llm/--json/--dry-run`
            (+ `--repo-dir/--dialect/--max-hops`). Live demo on `customers.customer_since`:
            2 critical, 2 high, 1 medium.
- [x] **Phase 1D — Write-back and PR comment** (COMPLETE — run live twice, idempotent; 61 tests pass)
      - [x] `datahub/client.py`: write primitives `emit_incident` / `get_incident` /
            `set_tags` / `upsert_document` / `get_document` (plumbing only; retry+observer
            reused). `urns.dataset_of_schema_field` helper. All verified live.
      - [x] `datahub/writeback.py`: for each CRITICAL/HIGH model — incident (idempotent,
            deterministic URN) + `pending-upstream-change` tag (set-union, preserves
            existing) + one knowledge-base document (deterministic id, full report).
            `TOOLS_IS_MUTATION_ENABLED` gate; `--dry-run` plans without writing; every
            write is a `WriteResult` collected into a `WritebackSummary` the report footer
            renders; a failed write degrades to FAILED and the comment still posts.
      - [x] `github.py`: `post_or_update_comment` finds our comment by a hidden marker
            (`<!-- blastradar:comment -->`) and PATCHes it in place (never spams); httpx,
            injectable for tests; degrades to SKIPPED/FAILED (no token / API error).
            `pr_context_from_env` reads the Actions event payload.
      - [x] `cli.py`: `--changes JSON` input (offline/CI), `--pr-*` flags, `--write-back`,
            `--post-comment`; runs write-back then posts, appends the write-back footer.
      - [x] `.github/workflows/blastradar.yml`: PR trigger on SQL/dbt paths; every secret
            documented in-file (DATAHUB_GMS_URL/TOKEN, ANTHROPIC_API_KEY,
            TOOLS_IS_MUTATION_ENABLED, GITHUB_TOKEN); least-privilege perms; concurrency.
      - [x] `demo-repo/`: idiomatic dbt project (dbt_project.yml, sources, staging, marts,
            schema.yml) whose `customers` mart maps to the seeded `customers` dataset;
            `demo-pr.patch` + `demo-pr.json` drop `customer_since` (the Phase 0 target).
      - [x] `tests/test_writeback.py` (18) + `tests/test_github.py` (11): gate, idempotency
            (2nd run = EXISTS/UPDATED, no dupes), degradation, marker post-vs-update.
      - [x] **LIVE**: ran the demo PR twice against the quickstart. Run 1 = 4 incidents +
            4 tags + 1 doc CREATED; run 2 = 8 EXISTS + doc UPDATED. Confirmed in DataHub:
            exactly 4 incidents on the `customers` dataset (CRITICAL/HIGH priority badges),
            `pending-upstream-change` on all 4 models (Tier1/Tier2 preserved), the document
            linking all 4 models + the dataset. PR comment POSTed then PATCHed in place
            (single comment) through the real CLI→httpx path against a local mock GitHub API.
- [x] **Phase 2 — Fixtures and reproducibility** (COMPLETE — 74 tests green offline;
      `make demo` cold-starts in ~0.5s)
      - [x] Task 1: **record/replay** in `datahub/replay.py`. `Recorder` is the
            `observer` hook the client was built for (Phase 1B); `ReplayClient` subclasses
            `DataHubClient` and overrides just `_ensure` (no-op) + `_call` (serve by
            **request signature**, not call order). Selection = `(method, canonical kwargs)`;
            a miss raises `ReplayMiss` (loud, points at `make record-fixtures`).
            `DataHubClient.from_env()` returns a `ReplayClient` when `BLASTRADAR_REPLAY`
            is set — so the *same* CLI runs offline. `scripts/record_fixtures.py` +
            `make record-fixtures` capture the live reads (113 calls) into
            `tests/fixtures/recorded/datahub_calls.json`.
      - [x] Task 2: `make demo` → `scripts/demo.py` replays the full pipeline (diff→…→report)
            with **no DataHub/network/key** (templated narration), prints the comment, writes
            `examples/`. **~0.5s** (budget 60s).
      - [x] Task 3: `make demo-live` → `scripts/demo_live.sh`: `datahub docker quickstart`
            (the version-matched official compose) → health-wait → ingest sample data → seed →
            live pipeline with **`TOOLS_IS_MUTATION_ENABLED=true` set automatically**.
      - [x] Task 4: live tests → **fixture tests** (`tests/conftest.py` forces replay
            session-wide, so nothing can touch the network). Suite runs green with Docker down
            AND with GMS pointed at a black hole. New `test_pipeline.py` (3 shapes + an
            examples-don't-rot guard) and `test_replay.py`. CI: `.github/workflows/ci.yml`
            (py3.11+3.12, offline, smoke-tests the demo, fails if `examples/` drift).
      - [x] Task 5: `docs/CLEAN-MACHINE-CHECKLIST.md` — precise wipe/clone/README runbook for
            the human clean-machine test (findings table to fill + hand back).
      - [x] Task 6: three generated `examples/` (critical trained-on / medium non-deployed /
            clean no-impact), each committed as `.md` + `.json`, indexed in `examples/README.md`.
      - [x] Refactor: extracted `src/blastradar/pipeline.py` (`run_analysis` = the read core;
            `finalize` = score→narrate→render→write-back footer). `cli.py` is now a thin
            wrapper over it, so the CLI / demo / recorder / tests share ONE path (no drift).
            Verified behaviour-preserving on the live path (`make writeback-demo` dry-run).
- [x] **Phase 3 — Docs, skill, and packaging** (COMPLETE — all phases done; 74 tests green)
      - [x] Task 1: **README** rewritten to the judge-skim order (one-liner → problem →
            sample comment → `make demo` → mermaid architecture + deterministic-core/LLM
            split → live setup with `TOOLS_IS_MUTATION_ENABLED` bolded → DataHub API
            specifics → honest limitations → license).
      - [x] Task 2: **DataHub Skill** at `skills/datahub-ml-impact/` (SKILL.md + README +
            references/ + templates/ + `scripts/ml_impact.py`), matching the datahub-skills
            layout. The runner **reuses** Blastradar's core (walk/score/narrate/render) for a
            single column — no reimplementation. Verified offline via fixtures. Upstream-PR
            prep + review checklist in `skills/datahub-ml-impact/UPSTREAM-PR.md`.
      - [x] Task 3: **`ml-showcase` datapack** at `contrib/ml-showcase/` — 66 MCPs, the Phase 0
            ML graph packaged as a DataHub `file`-ingestible artifact + recipe. Generated by a
            new `seed_ml_graph.py --export-datapack` mode that shares `iter_mcps` with the live
            seed (byte-stable, pinned ts). Upstream-PR prep for datahub-project/datahub.
      - [x] Task 4: **video script** (`docs/VIDEO-SCRIPT.md`) — 3-min beat sheet with
            voiceover + on-screen + retake flags for the slow/non-deterministic bits
            (image-pull, index lag, LLM prose).
      - [x] Task 5: **`SUBMISSION.md`** — Devpost checklist (public repo, LICENSE in About
            sidebar, video <3min public, demo URL, description text, category, tech tags,
            feedback survey opt-in).
      - [x] `pip install -e .` performed in `.venv` (console script `blastradar` available;
            the documented setup step).

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
- **Severity matrix (trained × deployed)** — Phase 1C `scoring.py` will own the
  authoritative version; previewed live in `verify_chain.py`:
  trained+deployed → **CRITICAL**, deployed+inference-only → **HIGH**,
  trained+not-deployed → **MEDIUM**, neither → **LOW**. The seed's 5 models cover
  CRITICAL/HIGH/MEDIUM: `churn_model_v3` (critical), `reactivation_model_v1`
  (high — deployed, trained on `order_details` not `customers`, reads the feature at
  inference), `churn_model_v1/v2` + `ltv_model_v1` (medium). Per-model spec supports
  a `train_inputs` override to decouple training inputs from consumed-feature sources.
- **Phase 1A data model (approved):** `ChangeEvent` gained a `new_column` field
  (renames need old+new names). `sql_delta` returns `list[ModelDelta]` (not bare
  `ChangeEvent`s) so external `SELECT *` surfaces as an `UnresolvedProjection` marker,
  never a silent empty set. `SchemaProvider` protocol is the single wire-up point for
  Phase 1B: pass a DataHub-backed provider and the same diff code expands external
  stars in place — no re-diffing. CTE/subquery stars already expand locally.
- **Phase 1B walker (built):** the client returns plain dicts (not SDK objects) so
  Phase 2 can record/replay; the resolver returns AMBIGUOUS (all candidates) rather
  than guessing; deployments/training-inputs are aspect reads (not lineage). Column
  precision into features comes from the feature's `blastradar.source_column` property
  matched against the carried column. Determinism enforced by sorting all outputs.
- **Phase 1B deps:** `requests` (already present via acryl-datahub) used for transient-error
  retry classification in the client wrapper.
- **Phase 1A deps:** `sqlglot==30.13.0`, `pytest==9.1.1` installed into `.venv`.
  Gotchas found: sqlglot 30.x uses the arg key **`from_`** (trailing underscore), and
  it **normalizes types per dialect** (snowflake `NUMBER(10,2)`→`DECIMAL`, `FLOAT`→`DOUBLE`)
  — type-change diffs compare normalized types, which is fine as long as both sides
  use the same dialect (default snowflake, configurable per call).
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
  (`set_title`/`set_text`/`add_related_asset`). **← superseded live in Phase 1D, see below.**
- **MCP server not on the critical path:** deterministic core calls the Python SDK
  directly; the separate `mcp-server-datahub` package is optional (decision pending).
- **Phase 1D write-back (built + run live; three plan corrections):**
  1. **Incidents can't target mlModels on this GMS** (500: `mlModel … not a valid
     destination for /entities/*`). Datasets are accepted → each incident is anchored on
     the **changed dataset**, with the affected model named in the title/description. This
     is a spec deviation forced by GMS ("open an incident on the affected mlModel" → on
     the dataset instead); documented in `writeback.py` + API-NOTES.
  2. **Idempotency via deterministic incident URN, not `raiseIncident`.** `raiseIncident`
     mints a random UUID and there's no lag-free way to list an entity's incidents
     (`MLModel.incidents` GraphQL undefined; summaries/relationships lag). So we emit
     `IncidentInfoClass` on `urn:li:incident:blastradar-<sha1(pr|dataset)>` and dedupe with
     a zero-lag `get_aspect` read. Two runs ⇒ exactly N incidents, verified.
  3. **`Document.create_document(id=…, …)` is the real constructor.** The
     `Document(urn=…)` + fluent-setters form raises "DocumentInfo aspect must be set".
     Deterministic `id` ⇒ idempotent upsert; mlModel URNs ARE valid `related_assets`
     (unlike incidents).
- **Mutation gate (`TOOLS_IS_MUTATION_ENABLED`):** implemented as a Blastradar-level
  policy in `writeback.mutations_enabled` (must equal `"true"`). Off ⇒ writes are planned
  and reported as DISABLED, the PR comment still posts. Flagged as the #1 setup gotcha in
  README/.env.example/the workflow.
- **PR comment updates in place:** `github.post_or_update_comment` matches a hidden
  `<!-- blastradar:comment -->` marker and PATCHes; never spams. Verified end-to-end
  through the CLI against a local mock GitHub API (POST then PATCH, one comment).
- **Incident numeric priority is inverse:** `0 CRITICAL, 1 HIGH, 2 MEDIUM, 3 LOW` — map
  severity accordingly so the UI badge matches (`_INCIDENT_PRIORITY` in writeback).
- **Phase 2 replay is signature-keyed, via `_call` override (not order).** The client
  already funnelled every call through `_call(method, fn, **kwargs)` and ran an `observer`
  after each — so `ReplayClient` needs to override only `_ensure` (skip connecting) and
  `_call` (look the result up by `(method, kwargs)` signature). Zero per-method
  duplication; a refactor that reorders reads can't break replay. One combined recording
  file (union of all scenarios) — signatures make combining free.
- **`make demo` drives the real CLI path offline.** `DataHubClient.from_env()` honours
  `BLASTRADAR_REPLAY`, so the demo/tests exercise the exact production pipeline, just with
  a replay client. Pipeline core was extracted to `pipeline.py` so cli/demo/recorder/tests
  can't drift.
- **Seed refinement for a genuine MEDIUM example (approved live):** `ltv_model_v1` is now
  **unowned** (was `@analytics-ml`). With the owner-escalation rule, every *owned*
  non-deployed model escalates MEDIUM→HIGH, and the only never-escalated model
  (`churn_v2`) can't be reached in isolation — so no PR could top out at MEDIUM. Making
  ltv unowned lets `order_details.order_total` → ltv render a real MEDIUM (the Task 6
  medium example). Ripple: the flagship `customer_since` mix shifted **2C/2H/1M →
  2C/1H/2M**. The seed now also **clears** ownership/tags for un-owned/un-tagged models
  (empty-aspect emit) so re-seeding is a clean baseline and a leftover
  `pending-upstream-change` tag from a prior write-back doesn't cling.
- **`make demo-live` uses `datahub docker quickstart`, not a vendored compose.** DataHub's
  stack is a large, version-coupled multi-service compose; the CLI fetches the one matching
  the installed `acryl-datahub`. Hand-vendoring it would rot (same rationale as generated
  fixtures). The script is idempotent and skips quickstart if GMS is already healthy.

## Known issues / deferred

- **Index lag after emit:** new entities/edges take ~minutes to appear in the
  search/graph index (aspect reads are immediately consistent). Scripts that rely on
  `get_lineage`/search should tolerate lag. `seed_ml_graph.py` uses DB-backed
  `list_all_entity_urns` for discovery to avoid this.
- **Write-back run live (Phase 1D) ✅** — incident (deterministic-URN aspect emit, on the
  changed dataset), tag merge, and `Document.create_document` all confirmed on GMS
  v1.5.0.6. See the three plan corrections under "Decisions" and the write-back callout in
  API-NOTES. Remaining live gap for later: the **LLM narration** path is still untested
  here (no `ANTHROPIC_API_KEY` in this env) — the demo uses `--no-llm`/templated prose.
- **PR comment posting is validated against a MOCK GitHub API**, not github.com — there is
  no git remote in this env. The real REST calls (list/POST/PATCH) run through the actual
  CLI→httpx path; only the server is local. In CI the same code hits github.com via
  `GITHUB_TOKEN`. `gh` CLI is not installed (not used — we call the REST API directly).
- **`_short()` URN display in verify_chain** truncates mlFeature names cosmetically.
  Superseded in package code by `datahub/urns.short_name` (strips trailing `)`);
  `scripts/verify_chain.py` still has the old helper — harmless, tidy if it bothers.
- **Seeded models now have VARIED owners/tags** (seed amended): churn_v3 `@ml-platform`+`Tier1`,
  churn_v1 `@ml-platform`+`Tier2`, churn_v2 UNOWNED/untagged, ltv_v1 `@analytics-ml`,
  reactivation_v1 `@growth-ml`. Exercises tag-based escalation (Tier1/Tier2), the
  unowned-attribution path, and non-uniform ownership for Phase 1C scoring + PR comment.
- **No transformation SQL in the datapack** — `UpstreamLineage.transformOperation` and
  `query` are None, so per-hop "SQL transform" capture yields nothing here (the walker
  captures it where present; it just isn't). The demo column also has no column-level
  downstream datasets, so paths are column→feature→model→deployment with no dataset hops.
- **Anthropic SDK pinned:** `anthropic==0.120.0`, model `claude-opus-4-8`. **`temperature`
  is removed on Opus 4.8** (sending it is a 400) — low-variance narration is requested via
  `output_config={"effort": "low"}` + no extended thinking. The literal "set temperature low"
  couldn't be honored on the pinned model; this is the closest equivalent.
- **LLM path untested live (no key here):** no `ANTHROPIC_API_KEY` / `ant` profile in this
  env, so the real narration was not exercised — the demo shows the **templated fallback**
  (the keyless-judge path). Export `ANTHROPIC_API_KEY` to get Opus-4.8-written prose.
- **Scoring escalation is potent (flag for review):** "owner group set" escalates one level,
  and almost every seeded model has an owner — so the deployed-but-inference-only model
  (`reactivation_v1`) escalates HIGH→CRITICAL, matching the trained+deployed one. Faithful to
  the spec's rule; if unintended, drop the owner clause from `SEVERITY_RULES`. Also: `Tier2`
  tags do NOT escalate (only Tier1/Critical), so `churn_v1` escalates via its owner, not its tag.
- `datahub.sdk` emits an `ExperimentalWarning`; import path may change when it
  stabilizes.
- **SDK `get_lineage` crashes on non-dataset downstreams (live-found, Phase 2):** some
  datapack datasets (`order_items`, `orders`) have **chart** downstreams, and
  `datahub.sdk.lineage_client` passes those URNs to `DatasetUrn.from_string` → raises
  `InvalidUrnError: Passed an urn of type chart`. So those columns can't be walked and were
  avoided as demo targets. `order_details` (an analytics table with no chart downstream) is
  used for the medium example instead. If a real target ever hits a chart downstream the
  walk raises `DataHubClientError` and the column is reported "incomplete" — not a false
  all-clear. Deferred: catch/skip non-dataset lineage rows inside the client, or pin an SDK
  with the fix.
- **Phase 2 fixtures cover exactly the demo/example scenarios + edge cases** (customer_since,
  order_details.order_total, phone_number, an unresolvable table). A new column/scenario
  needs a re-record (`make record-fixtures` against a seeded live DataHub); a replay miss is
  loud, so this fails visibly rather than silently. The recording reflects the **seeded**
  graph — run `make seed` before `make record-fixtures` for a clean baseline.
- **Clean-machine test (Task 5) still needs the human** — see
  `docs/CLEAN-MACHINE-CHECKLIST.md`. `make demo-live`'s full cold-start (image pull) was not
  timed here (DataHub was already up in this env); the checklist times it end-to-end.
