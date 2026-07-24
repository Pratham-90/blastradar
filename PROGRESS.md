# Blastradar — Progress

Read this at the start of every session. Update it as phases complete, decisions
get made, and issues surface.

Hackathon: DataHub Agent Hackathon. Deadline: **2026-08-10**.

## Phase checklist

- [ ] **Phase 0 — Foundations and verification**
      Repo skeleton, tooling, and `docs/API-NOTES.md` filled in from the actually
      installed DataHub/Anthropic SDKs. Add the SDK deps once versions are known.
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

_(none yet)_

## Known issues / deferred

_(none yet)_
