# Upstream PR prep — `ml-showcase` datapack

Prepares the ML metadata graph as a contribution to
[`datahub-project/datahub`](https://github.com/datahub-project/datahub), adding ML
sample entities that the project's example data currently lacks. Nothing has been
pushed — review the placement question below before opening, since the exact target
path is the maintainers' call.

## The gap it fills

DataHub ships sample datasets (the ecommerce showcase, etc.) but **no ML entities** —
no `mlModel`, `mlFeature`, `mlModelDeployment`, or training-run provenance. So there's
no built-in fixture for demoing or testing ML lineage, impact analysis, or
trained-on-vs-inference distinctions. This pack adds exactly that, on top of the
existing ecommerce sample.

## The diff (focused)

Add an example metadata file + recipe. Proposed location (confirm with maintainers):

```
metadata-ingestion/examples/mce_files/ml_showcase.json      # the 66-MCP datapack
metadata-ingestion/examples/recipes/ml_showcase_to_datahub.yml   # file -> datahub-rest
```

(That directory already holds `bootstrap_mce.json`, `single_mce.json`, etc., so a new
ML example file is a natural fit. Alternatively the maintainers may prefer it under a
demo-data path — see the review checklist.)

## Steps to open it

```bash
# 1. Fork datahub-project/datahub, then:
git clone git@github.com:<you>/datahub.git
cd datahub
git switch -c ml-showcase-sample-data

# 2. Add the pack + a recipe (from this Blastradar checkout):
cp <blastradar>/contrib/ml-showcase/ml-showcase.json \
   metadata-ingestion/examples/mce_files/ml_showcase.json
#   (adapt recipe.yml's `path` to the new location for the recipe example)

# 3. Commit + push + open the PR:
git add metadata-ingestion/examples/mce_files/ml_showcase.json
git commit -m "Add ml-showcase example: ML entities (models, features, deployments, training runs)"
git push -u origin ml-showcase-sample-data
```

## PR title

```
Add ml-showcase example: ML entities for the sample metadata graph
```

## PR description (paste this)

> ### What
> Adds an ingestible example metadata file, `ml_showcase.json` (66 MCPs), that layers a
> realistic **ML metadata graph** onto the existing ecommerce sample data: 5 mlModels
> (with versions, hyperparameters, metrics, ownership, tags) across 3 model groups, 3
> mlFeatureTables / 12 mlFeatures, 4 mlModelDeployments, and 5 training runs
> (`dataProcessInstance`) **with input datasets populated**.
>
> ### Why
> The sample datasets today carry no ML entities, so there's no out-of-the-box fixture
> for demoing or testing ML lineage, impact analysis, or governance features that touch
> `mlModel`/`mlFeature`/`mlModelDeployment`. This provides one. It's deliberately shaped
> to include the cases that matter: models *trained on* a source column vs. ones that
> only *read it at inference*, deployed vs. shelved, owned vs. unowned, tagged vs. not.
>
> ### How to load
> ```bash
> datahub docker ingest-sample-data        # the ecommerce datasets this builds on
> datahub ingest -c ml_showcase_to_datahub.yml
> ```
> Idempotent (deterministic URNs, aspect upserts).
>
> ### Note
> The features/training runs reference the ecommerce sample dataset URNs. Generated
> programmatically (discovering those URNs from a live instance), so it can be
> regenerated if the sample dataset naming ever changes.

## Review before you open it

- [ ] **Confirm the target path.** `metadata-ingestion/examples/mce_files/` is a
      reasonable home (it holds `bootstrap_mce.json`), but maintainers may prefer a
      dedicated demo-data location. Open a short issue first, or ask in the PR.
- [ ] **Dataset-URN coupling.** The pack references the ecommerce sample's dataset URNs
      (`…b2fd91.order_entry_db…`). Confirm those match the sample data the maintainers
      expect people to have ingested; if the standard sample differs, regenerate with
      `scripts/seed_ml_graph.py --export-datapack`.
- [ ] **Format check.** Validate it ingests cleanly on a fresh quickstart
      (`datahub ingest -c recipe.yml`) and that the entities render in the UI.
- [ ] **Scope.** Keep the diff to the example file (+ recipe). Don't bundle unrelated
      changes.
- [ ] **License / DCO.** DataHub requires a DCO sign-off (`git commit -s`). Add it.
