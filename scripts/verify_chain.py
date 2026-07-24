"""Task 4 — Confirm the blast-radius chain end to end.

Starts from the seeded demo drop-target column and walks DOWNSTREAM to the
deployment(s) it impacts. This is the exact traversal Phase 1B (datahub/walker.py)
will automate — and Phase 0 proved (see PROGRESS.md / API-NOTES) that it must be a
HYBRID walk, because different edges are reachable different ways:

  * dataset  -> mlFeature   : table-level get_lineage downstream (DerivedFrom edge).
                              NOTE: column-constrained get_lineage(source_column=)
                              does NOT reach features — mlFeature.sources is
                              dataset-granular (GMS rejects schemaField sources), so
                              column precision is recovered from the feature's
                              `blastradar.source_column` custom property.
  * mlFeature -> mlModel    : table-level get_lineage downstream (Consumes edge).
  * mlModel  -> deployment  : NOT lineage (DeployedTo is not traversed) — read the
                              model's MLModelProperties.deployments aspect.
  * trained-vs-inference    : read model.trainingJobs -> each dataProcessInstance's
                              inputs; if the changed column's dataset is a training
                              input, the model was TRAINED on it (not just serving).

Run:  .venv/bin/python scripts/verify_chain.py
Reads scripts/seeded_urns.json (produced by seed_ml_graph.py).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import datahub.metadata.schema_classes as M

from _datahub_env import get_client, get_graph, urn_type

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("verify_chain")

URNS_IN = Path(__file__).resolve().parent / "seeded_urns.json"


def _down(client, urn: str, want_type: str) -> list[str]:
    """One-hop table-level downstream neighbours of `urn` of a given entity type."""
    results = client.lineage.get_lineage(
        source_urn=urn, direction="downstream", max_hops=1, count=200
    )
    return [r.urn for r in results if urn_type(r.urn) == want_type]


def _short(urn: str) -> str:
    return urn.split(",")[-2] if "," in urn else urn


def blast_walk(client, graph, dataset_urn: str, column: str) -> list[dict]:
    """The real hybrid walk: column -> feature(s) -> model(s) -> deployment(s)."""
    chains: list[dict] = []

    # dataset -> features, keep only those whose recorded source column matches.
    features = _down(client, dataset_urn, "mlFeature")
    matched = []
    for f in features:
        fp = graph.get_aspect(f, M.MLFeaturePropertiesClass)
        col = (fp.customProperties or {}).get("blastradar.source_column") if fp else None
        if col == column:
            matched.append(f)

    for feat in matched:
        for model in _down(client, feat, "mlModel"):
            mp = graph.get_aspect(model, M.MLModelPropertiesClass)
            deployments = list(mp.deployments or []) if mp else []
            training_jobs = list(mp.trainingJobs or []) if mp else []

            trained_on = False
            for job in training_jobs:
                di = graph.get_aspect(job, M.DataProcessInstanceInputClass)
                if di and dataset_urn in (di.inputs or []):
                    trained_on = True
                    break

            chains.append({
                "feature": feat, "model": model,
                "deployments": deployments, "trained_on": trained_on,
                "deployed": bool(deployments),
            })
    return chains


def main() -> int:
    if not URNS_IN.exists():
        logger.error("Missing %s — run seed_ml_graph.py first.", URNS_IN)
        return 2
    seed = json.loads(URNS_IN.read_text())
    dt = seed["demo_drop_target"]

    logger.info("=== Blastradar Task 4: end-to-end chain from a source column ===")
    logger.info("Start column: %s . %s\n", _short(dt["source_dataset"]), dt["source_column"])

    client = get_client()
    graph = get_graph()
    client.test_connection()

    chains = blast_walk(client, graph, dt["source_dataset"], dt["source_column"])
    if not chains:
        logger.error("No impact chain found — check indexing / seed. ❌")
        return 1

    deployed = [c for c in chains if c["deployed"]]
    logger.info("BLAST RADIUS (via live lineage + aspect reads): %d model(s) impacted, "
                "%d deployed. ✅\n", len(chains), len(deployed))
    logger.info("  %s . %s   [dropped column]", _short(dt["source_dataset"]), dt["source_column"])
    for c in chains:
        logger.info("    └─> feature %s", _short(c["feature"]))
        tag = "TRAINED-ON" if c["trained_on"] else "inference-only"
        logger.info("          └─> model %s  [%s]", _short(c["model"]), tag)
        for d in c["deployments"]:
            logger.info("                └─> DEPLOYMENT %s  🚨 (live)", _short(d))
        if not c["deployments"]:
            logger.info("                └─> (not deployed)")

    logger.info("\nTerminal deployments reached: %s",
                ", ".join(sorted({_short(d) for c in chains for d in c["deployments"]})) or "(none)")
    logger.info("This is exactly the traversal Phase 1B will automate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
