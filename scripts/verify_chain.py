"""Task 4 — Confirm the blast-radius chain end to end.

Starts from the seeded demo drop-target column and walks DOWNSTREAM through the
lineage graph, printing the full path it finds, ideally ending at a deployment.
This is the exact traversal Phase 1B (datahub/walker.py) will automate.

Two modes of evidence:
  1. PURE LINEAGE walk via client.lineage.get_lineage (hop by hop). This is what
     matters — it proves DataHub actually traverses column -> feature -> model ->
     deployment as lineage.
  2. If the pure walk cannot cross an edge (e.g. mlModel.mlFeatures is not exposed
     as traversable lineage), fall back to reconstructing the chain from the
     seeded relationships in seeded_urns.json — clearly labelled as NOT pure
     lineage, so we know exactly what Phase 1B must handle.

Run:  .venv/bin/python scripts/verify_chain.py

Reads scripts/seeded_urns.json (produced by seed_ml_graph.py).
"""

from __future__ import annotations

import json
import logging
import sys
from collections import deque
from pathlib import Path

from _datahub_env import get_client, urn_type

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("verify_chain")

URNS_IN = Path(__file__).resolve().parent / "seeded_urns.json"
MAX_DEPTH = 6
ML_TYPES = {"mlFeature", "mlFeatureTable", "mlModel", "mlModelDeployment"}


def pure_lineage_walk(client, start_urn: str, start_column: str) -> list[list[str]]:
    """BFS downstream from a column. Returns discovered node path(s) to a deployment.

    Each node is rendered as "type:urn[:column]". Returns list of path-chains
    (list of node labels) that terminate at an mlModelDeployment.
    """
    start = (start_urn, start_column)
    parents: dict[tuple[str, str | None], tuple[str, str | None] | None] = {start: None}
    frontier: deque[tuple[str, str | None]] = deque([start])
    depth = {start: 0}
    terminals: list[tuple[str, str | None]] = []

    while frontier:
        urn, column = frontier.popleft()
        if depth[(urn, column)] >= MAX_DEPTH:
            continue
        results = client.lineage.get_lineage(
            source_urn=urn, source_column=column, direction="downstream",
            max_hops=1, count=200,
        )
        for r in results:
            cols = [p.column_name for p in (r.paths or [])] or [None]
            for c in cols:
                node = (r.urn, c)
                if node in parents:
                    continue
                parents[node] = (urn, column)
                depth[node] = depth[(urn, column)] + 1
                frontier.append(node)
                if urn_type(r.urn) == "mlModelDeployment":
                    terminals.append(node)

    def chain(node):
        out = []
        while node is not None:
            u, c = node
            label = f"{urn_type(u) or 'dataset'}:{u.split(',')[-2] if ',' in u else u}"
            if c:
                label += f"[{c}]"
            out.append(label)
            node = parents[node]
        return list(reversed(out))

    return [chain(t) for t in terminals]


def seed_reconstruction(seed: dict) -> list[str]:
    """Reconstruct the intended chain from seeded relationships (not pure lineage)."""
    dt = seed["demo_drop_target"]
    steps = [
        f"column  {dt['source_dataset']} . {dt['source_column']}",
        f"schemaField  {dt['schema_field_urn']}",
        f"mlFeature  {dt['feature_urn']}",
        f"mlFeatureTable  {dt['feature_table']}",
    ]
    for mu in dt["downstream_models"]:
        steps.append(f"mlModel  {mu}")
    for d in dt["downstream_deployments"]:
        steps.append(f"mlModelDeployment  {d}")
    return steps


def main() -> int:
    if not URNS_IN.exists():
        logger.error("Missing %s — run seed_ml_graph.py first.", URNS_IN)
        return 2
    seed = json.loads(URNS_IN.read_text())
    dt = seed["demo_drop_target"]

    logger.info("=== Blastradar Task 4: end-to-end chain from a source column ===")
    logger.info("Start column: %s . %s", dt["source_dataset"], dt["source_column"])
    logger.info("Expected terminal deployments: %s\n",
                ", ".join(dt["downstream_deployments"]) or "(none seeded)")

    client = get_client()
    client.test_connection()

    logger.info("--- Pure lineage walk (get_lineage, downstream) ---")
    chains = pure_lineage_walk(client, dt["source_dataset"], dt["source_column"])
    if chains:
        logger.info("REACHED A DEPLOYMENT VIA PURE LINEAGE. ✅")
        for i, ch in enumerate(chains, 1):
            logger.info("  path %d:", i)
            for j, node in enumerate(ch):
                logger.info("    %s%s", "   " * j + "-> " if j else "", node)
        return 0

    logger.warning("Pure lineage walk did NOT reach a deployment. ⚠️")
    logger.warning("This tells Phase 1B which edges are not lineage-traversable and "
                   "must be bridged via aspect reads (mlModel.mlFeatures, "
                   "mlModel.deployments).")
    logger.info("\n--- Seed-metadata reconstruction (NOT pure lineage) ---")
    for step in seed_reconstruction(seed):
        logger.info("  -> %s", step)
    # Non-zero: the pure-lineage goal wasn't met, so the human sees it plainly.
    return 1


if __name__ == "__main__":
    sys.exit(main())
