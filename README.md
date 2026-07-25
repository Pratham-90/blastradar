# Blastradar

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

## Quick start

Two reproduction paths (architectural rule 3). Both assume Python **3.11+** and a
one-time setup:

```sh
python3.11 -m venv .venv            # 3.12 also works; see PROGRESS.md
.venv/bin/pip install -e ".[dev]"   # installs Blastradar + test deps
```

**Offline — a stranger in 60 seconds.** No DataHub, no network, no API key:

```sh
make demo     # full pipeline on recorded fixtures — prints the PR comment, <60s
make test     # the whole suite, offline (the fixtures double as the tests)
```

`make demo` runs the real pipeline against [recorded DataHub responses](tests/fixtures/recorded/)
and writes the rendered comment to [`examples/`](examples/README.md). See three sample
shapes there: a critical trained-on hit, a medium non-deployed hit, and a clean
no-impact PR.

**Live — the full loop against a real DataHub.** Needs Docker:

```sh
make demo-live   # stands up DataHub, seeds it, runs the pipeline WITH write-back
```

`make demo-live` sets `TOOLS_IS_MUTATION_ENABLED=true` for you, so the incidents,
tags, and document actually land in DataHub (this is the #1 setup gotcha — see below).

Regenerate the recorded fixtures against a live, seeded DataHub with
`make record-fixtures` (they are generated, never hand-maintained — hand-maintained
fixtures rot).

## Status

Early build for the DataHub Agent Hackathon (deadline 2026-08-10). See
[PROGRESS.md](PROGRESS.md) for current state and [CLAUDE.md](CLAUDE.md) for the
architecture and design rules. To validate a cold-start clone, follow
[docs/CLEAN-MACHINE-CHECKLIST.md](docs/CLEAN-MACHINE-CHECKLIST.md).

## License

[Apache 2.0](LICENSE).
