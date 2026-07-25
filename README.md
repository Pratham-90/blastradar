# Blastradar

> Stub — expanded in Phase 3.

Blastradar is a CI agent that reviews data pull requests for downstream
machine-learning impact. When a PR changes a SQL/dbt model — dropping a column,
renaming one, or changing a type — Blastradar traces DataHub's column-level
lineage downstream to the ML features, models, and deployments that depend on it,
scores the blast radius, and posts a plain-English PR comment before the change
silently breaks a production model.

Dropping an upstream column doesn't throw an error. The feature pipeline emits
nulls and a model degrades for weeks before anyone notices. Blastradar closes
that gap.

It doesn't just comment — it **closes the loop back into DataHub**. For every
critical or high impact it opens an **incident**, tags the model
`pending-upstream-change`, and saves the full report as a knowledge-base
**document**, then posts (and later updates in place) a single PR comment.

## What it does on a PR

1. Parses the SQL diff with sqlglot to find the exact changed columns.
2. Resolves them to DataHub URNs and walks column-level lineage downstream to the
   ML features, models, and deployments.
3. Scores each impacted model (trained-on vs. inference-only × deployed).
4. Writes findings back into DataHub — incident, tag, document — **idempotently**.
5. Posts / updates one PR comment explaining the blast radius.

```sh
blastradar analyze \
  --changes demo-repo/demo-pr.json \
  --pr-repo order-entry/analytics --pr-number 42 \
  --dry-run                          # preview everything, write nothing
```

### ⚠️ Write-back is OFF by default

DataHub mutations require an explicit opt-in. **Set `TOOLS_IS_MUTATION_ENABLED=true`**
or Blastradar analyzes and comments but writes nothing (the comment says so). This
is the single most common setup miss — if incidents aren't appearing in DataHub,
this variable is unset. See [`.env.example`](.env.example) and
[`.github/workflows/blastradar.yml`](.github/workflows/blastradar.yml).

In CI the [GitHub Action](.github/workflows/blastradar.yml) runs this on every PR
that touches a `.sql` / dbt model. The demo project it reviews lives in
[`demo-repo/`](demo-repo/README.md).

## Status

Early build for the DataHub Agent Hackathon (deadline 2026-08-10). See
[PROGRESS.md](PROGRESS.md) for current state and [CLAUDE.md](CLAUDE.md) for the
architecture and design rules.

## Quick start (once implemented)

```sh
make demo        # full pipeline on recorded fixtures, no DataHub, <60s
make demo-live   # full pipeline against a real local DataHub
```

## License

[Apache 2.0](LICENSE).
