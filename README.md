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
