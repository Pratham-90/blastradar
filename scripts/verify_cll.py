"""Task 2 — CRITICAL ASSUMPTION CHECK: does column-level lineage exist here?

Blastradar's whole premise is that DataHub holds *column*-level lineage for the
showcase-ecommerce datapack. This script proves (or disproves) that against the
live instance:

  1. Connect to the local DataHub.
  2. Find a dataset (prefer dbt / snowflake) that HAS upstream lineage.
  3. Query lineage at COLUMN granularity for its fields.
  4. Print whether column-level edges came back, with an example path.

Exit code 0 => column-level lineage found. Non-zero => not found (STOP and tell
the human; Phase 0 plan changes to emitting a small column-level subgraph).

Run:  .venv/bin/python scripts/verify_cll.py

Verified API used (see docs/API-NOTES.md):
  client.lineage.get_lineage(source_urn=..., source_column=..., direction=...,
                             max_hops=...) -> List[LineageResult]
  LineageResult.paths: List[LineagePath]; LineagePath.column_name: Optional[str]
"""

from __future__ import annotations

import logging
import sys

from _datahub_env import get_client, get_graph

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("verify_cll")

PREFERRED_PLATFORMS = ("dbt", "snowflake", "bigquery", "redshift", "postgres", "hive")
MAX_DATASETS_TO_SCAN = 400
MAX_FIELDS_PER_DATASET = 40


def _platform_of(urn: str) -> str:
    # urn:li:dataset:(urn:li:dataPlatform:<platform>,<name>,<env>)
    marker = "dataPlatform:"
    if marker in urn:
        return urn.split(marker, 1)[1].split(",", 1)[0]
    return "?"


def find_datasets_with_upstream(client, graph) -> list[str]:
    """Return dataset URNs that have table-level upstream lineage, preferred first."""
    all_urns = list(
        graph.get_urns_by_filter(entity_types=["dataset"], batch_size=1000)
    )
    logger.info("Found %d dataset URNs total.", len(all_urns))

    def sort_key(u: str) -> tuple[int, str]:
        plat = _platform_of(u)
        rank = PREFERRED_PLATFORMS.index(plat) if plat in PREFERRED_PLATFORMS else 99
        return (rank, u)

    candidates = sorted(all_urns, key=sort_key)[:MAX_DATASETS_TO_SCAN]
    with_upstream: list[str] = []
    for urn in candidates:
        results = client.lineage.get_lineage(
            source_urn=urn, direction="upstream", max_hops=1, count=50
        )
        if results:
            with_upstream.append(urn)
            logger.info(
                "  upstream lineage: %s  (%d immediate upstream)", urn, len(results)
            )
            if len(with_upstream) >= 5:
                break
    return with_upstream


def probe_column_lineage(client, graph, dataset_urn: str):
    """For each field, ask for column-level upstream lineage. Return first hit."""
    sm = graph.get_schema_metadata(dataset_urn)
    if not sm or not sm.fields:
        logger.info("  (no schema metadata for %s)", dataset_urn)
        return None

    fields = [f.fieldPath for f in sm.fields][:MAX_FIELDS_PER_DATASET]
    logger.info("  probing %d fields of %s", len(fields), dataset_urn)
    for field in fields:
        results = client.lineage.get_lineage(
            source_urn=dataset_urn,
            source_column=field,
            direction="upstream",
            max_hops=1,
            count=50,
        )
        for r in results:
            col_paths = [p for p in (r.paths or []) if p.column_name]
            if col_paths:
                return {
                    "downstream_dataset": dataset_urn,
                    "downstream_column": field,
                    "upstream_urn": r.urn,
                    "upstream_columns": [p.column_name for p in col_paths],
                    "example_path": col_paths[0],
                }
    return None


def main() -> int:
    logger.info("=== Blastradar Task 2: column-level lineage verification ===")
    client = get_client()
    graph = get_graph()
    client.test_connection()
    logger.info("Connected.\n")

    datasets = find_datasets_with_upstream(client, graph)
    if not datasets:
        logger.error(
            "\nRESULT: No datasets with ANY upstream lineage were found. "
            "Cannot verify column-level lineage. STOP — the datapack may not have "
            "lineage loaded; re-check the ingestion."
        )
        return 2

    logger.info("\nProbing column-level lineage on %d dataset(s)...", len(datasets))
    for urn in datasets:
        hit = probe_column_lineage(client, graph, urn)
        if hit:
            logger.info("\n" + "=" * 70)
            logger.info("RESULT: COLUMN-LEVEL LINEAGE IS PRESENT. ✅")
            logger.info("=" * 70)
            logger.info("  downstream : %s", hit["downstream_dataset"])
            logger.info("    column   : %s", hit["downstream_column"])
            logger.info("  upstream   : %s", hit["upstream_urn"])
            logger.info("    column(s): %s", ", ".join(hit["upstream_columns"]))
            logger.info(
                "  example path node: entity=%s column=%s",
                hit["example_path"].entity_name,
                hit["example_path"].column_name,
            )
            return 0

    logger.warning("\n" + "=" * 70)
    logger.warning("RESULT: table-level lineage exists, but NO column-level edges. ⚠️")
    logger.warning("=" * 70)
    logger.warning(
        "STOP and tell the human: Phase 0 plan changes — we must emit a small "
        "column-level subgraph ourselves for the demo."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
