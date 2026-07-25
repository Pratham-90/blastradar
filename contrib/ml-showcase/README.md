# `ml-showcase` datapack

A reusable DataHub datapack that adds a realistic **ML metadata graph** on top of
DataHub's ecommerce sample data. None of DataHub's shipped sample datasets carry ML
entities, so there's no out-of-the-box way to demo or test anything that touches
`mlModel` / `mlFeature` / `mlModelDeployment` lineage. This fills that gap.

It's the exact output of Blastradar's Phase 0 seeding, packaged as an ingestible
metadata file (66 MCPs) so anyone can load it with one command.

## What's in it

| Entity | Count | Notes |
|---|---|---|
| `mlModelGroup` | 3 | churn, ltv, reactivation |
| `mlModel` | 5 | with versions, hyperparameters, metrics, ownership, tags |
| `mlFeatureTable` | 3 | customer / order / session features |
| `mlFeature` | 12 | each records its exact source column in `customProperties` |
| `mlModelDeployment` | 4 | `IN_SERVICE`, attached only to deployed models |
| `dataProcessInstance` | 5 | one training run per model, **with input datasets** |
| `tag` / `corpGroup` | 2 / 2 | `Tier1`/`Tier2`; owner groups |

The graph is deliberately shaped to exercise real ML-governance cases: a model
**trained on** a source column vs. one that only **reads it at inference**; deployed vs.
shelved models; owned vs. unowned; tagged vs. untagged. Training-run provenance
(`dataProcessInstanceInput`) is populated, which is what lets a tool distinguish
trained-on from inference-only impact.

## Prerequisites

The ecommerce sample data must be ingested first — the ML features and training runs
reference those dataset URNs:

```sh
datahub docker ingest-sample-data      # or your usual sample-data load
```

## Ingest it

```sh
datahub ingest -c recipe.yml           # DATAHUB_GMS_URL defaults to http://localhost:8080
```

Idempotent — every record is an aspect upsert on a deterministic URN, so re-ingesting
is safe.

## Portability note

The feature `sources` and training inputs point at the ecommerce sample's dataset URNs
(e.g. `urn:li:dataset:(urn:li:dataPlatform:dbt,…order_entry.customers,PROD)`). If your
instance names those datasets differently, regenerate the pack against your own
instance — it discovers the dataset URNs live:

```sh
python scripts/seed_ml_graph.py --export-datapack contrib/ml-showcase/ml-showcase.json
```

## Files

| File | What |
|---|---|
| `ml-showcase.json` | The datapack — 66 MCPs, DataHub `file`-source ingestible |
| `recipe.yml` | Ingestion recipe (file → datahub-rest) |
| `UPSTREAM-PR.md` | How this is prepared as a contribution to `datahub-project/datahub` |

## License

Apache 2.0.
