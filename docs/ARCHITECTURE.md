# Architecture

Blastradar is a single deterministic pipeline. Data flows left to right; the LLM
is touched exactly once, at the Narrator stage (architectural rule 1). Everything
before it is plain Python calling DataHub tools in a fixed algorithm.

## Component pipeline

```
   PR diff
      │
      ▼
┌──────────────┐     ┌────────────────────┐     ┌──────────────┐     ┌───────────────────┐
│ Diff Extract │ ──▶ │ SQL Delta Analyzer │ ──▶ │ URN Resolver │ ──▶ │ Blast Radius      │
│ (diff/       │     │ (diff/sql_delta,   │     │ (datahub/    │     │ Walker            │
│  extract.py) │     │  sqlglot)          │     │  resolver.py)│     │ (datahub/         │
└──────────────┘     └────────────────────┘     └──────────────┘     │  walker.py)       │
                                                                      └─────────┬─────────┘
                                                                                │
                                                                                ▼
                                                                      ┌───────────────────┐
                                                                      │ Severity Scorer   │
                                                                      │ (scoring.py)      │
                                                                      │ train vs.         │
                                                                      │ inference         │
                                                                      └─────────┬─────────┘
                                                                                │
                                                                                ▼
                                                                      ┌───────────────────┐
                                                                      │ Narrator          │
                                                                      │ (narrate.py)      │
                                                                      │ ── the ONE LLM ── │
                                                                      │ call: prose +     │
                                                                      │ migration only    │
                                                                      └─────────┬─────────┘
                                                                                │
                                                          ┌─────────────────────┴─────────────────────┐
                                                          ▼                                            ▼
                                                ┌───────────────────┐                       ┌───────────────────┐
                                                │ PR Commenter      │                       │ DataHub Writeback │
                                                │ (report.py)       │                       │ (writeback.py)    │
                                                │ Markdown on the   │                       │ incident + tag +  │
                                                │ pull request      │                       │ saved document    │
                                                └───────────────────┘                       └───────────────────┘
```

## Stage responsibilities

| Stage               | Module                   | Responsibility                                                                 |
| ------------------- | ------------------------ | ------------------------------------------------------------------------------ |
| Diff Extract        | `diff/extract.py`        | Pull changed SQL/dbt model files and their before/after text from a PR diff.   |
| SQL Delta Analyzer  | `diff/sql_delta.py`      | sqlglot parse of before/after → columns dropped / renamed / retyped.           |
| URN Resolver        | `datahub/resolver.py`    | Map changed columns to DataHub schemaField URNs.                               |
| Blast Radius Walker | `datahub/walker.py`      | Deterministic multi-hop column-level lineage traversal to ML entities.         |
| Severity Scorer     | `scoring.py`             | Score each impacted ML asset; distinguish trained-on vs. inference-time reads. |
| Narrator            | `narrate.py`             | The single LLM call: prose explanation + suggested migration.                  |
| PR Commenter        | `report.py`              | Render the blast radius + narration into a Markdown PR comment.                |
| DataHub Writeback   | `datahub/writeback.py`   | Record the finding as a DataHub Core incident, tag, and saved document.        |

The structured impact graph is fully resolved by the Severity Scorer stage; the
Narrator receives it as data and only produces language. The PR Commenter and
DataHub Writeback are independent sinks fed by the same scored result.
