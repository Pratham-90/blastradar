# Blastradar

Blastradar is a CI agent that reviews data pull requests for downstream
machine-learning impact. When a PR changes a SQL/dbt model — dropping a column,
renaming one, changing a type — Blastradar parses the diff to find exactly which
columns changed, resolves them to DataHub URNs, walks DataHub's column-level
lineage graph downstream over multiple hops until it reaches ML entities
(`mlFeatureTable`, `mlModel`, `mlModelDeployment`), scores each impacted ML asset
by severity (including whether the model was *trained* on the changed column vs.
merely reads it at inference), posts a plain-English PR comment explaining the
blast radius, and writes the finding back into DataHub as an incident, a tag, and
a saved document. It exists because dropping an upstream column does not throw an
error: the feature pipeline silently emits nulls and a production model degrades
for weeks before anyone notices.

## Architectural rules (non-negotiable — do not revisit without asking)

1. **DETERMINISTIC CORE, LLM ONLY FOR NARRATION.**
   Lineage traversal and impact determination are plain Python calling DataHub
   tools in a fixed algorithm. The LLM is called exactly ONCE per run, at the very
   end, given a fully-resolved structured impact graph, and asked only to write
   prose and suggest a migration. The LLM never decides what is impacted.
   Reason: judges run this once; agent loops over graph traversal are not
   reproducible and a non-deterministic demo reads as broken.

2. **MUST RUN ON DATAHUB CORE (open source).**
   No DataHub Cloud-only features on the critical path. That specifically rules
   out assertions, data contracts, and the data health dashboard. Write-back uses
   incidents, tags, and saved documents only.

3. **TWO REPRODUCTION PATHS.**
   `make demo` runs the whole pipeline against recorded fixtures with no DataHub
   instance required, in under 60 seconds.
   `make demo-live` runs against a real local DataHub.
   The fixtures double as the test suite.

4. **SQL PARSING USES sqlglot, NOT REGEX.**
   Regex over diffs breaks on CTEs, aliases, and SELECT *. When SELECT * is
   encountered, expand it using DataHub's schema metadata.

5. **APACHE 2.0 LICENSE, file named exactly `LICENSE` at repo root.**

## Repo layout

```
blastradar/
  CLAUDE.md                     this file
  PROGRESS.md                   current build state — READ AT SESSION START
  README.md                     public-facing overview
  LICENSE                       Apache 2.0
  Makefile                      demo / demo-live / test / seed / record-fixtures
  pyproject.toml                packaging + deps
  docs/
    API-NOTES.md                verified DataHub/SDK API facts — READ BEFORE DataHub CODE
    ARCHITECTURE.md             component pipeline diagram
  src/blastradar/
    __init__.py                 package metadata
    models.py                   frozen dataclasses for the whole pipeline
    diff/extract.py             pull changed SQL/dbt files out of a PR diff
    diff/sql_delta.py           sqlglot delta: which columns dropped/renamed/retyped
    datahub/client.py           thin wrapper over the DataHub client / MCP tools
    datahub/resolver.py         resolve changed columns to DataHub URNs
    datahub/walker.py           deterministic column-level lineage traversal to ML
    datahub/writeback.py        incidents / tags / documents back into DataHub
    scoring.py                  deterministic severity scoring (train vs. inference)
    narrate.py                  the single LLM call — prose + migration only
    report.py                   render the PR comment / report
    cli.py                      click entry point that wires the pipeline together
  tests/
    fixtures/                   recorded DataHub responses (double as the demo data)
  scripts/
    seed_ml_graph.py            seed a local DataHub with the demo ML graph
    record_fixtures.py          capture live responses into tests/fixtures
  examples/                     sample diffs / PRs used by the demo
  demo-repo/                    the fake data repo whose PRs Blastradar reviews
  .github/workflows/            CI that runs Blastradar as an action
```

## Conventions

- Python 3.11+.
- Dataclasses are frozen by default (`@dataclass(frozen=True)`).
- Type hints everywhere.
- Tests use pytest.
- No bare `except:` — always catch a specific exception.
- Module-level logger: `logger = logging.getLogger(__name__)`.

## Read before writing DataHub code

Anything that touches the DataHub SDK, MCP tools, URNs, lineage, ML entities, or
write-back MUST first be checked against **`docs/API-NOTES.md`**. Do not write
DataHub code against an unverified section of that file.

## Session start

Read **`PROGRESS.md`** at the start of every session — it holds the current phase,
decisions made during the build, and known issues / deferred work.
