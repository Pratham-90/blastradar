"""Task 3 — Seed the ML metadata graph on top of the showcase-ecommerce datapack.

Idempotent (safe to re-run: every write is an aspect upsert / deterministic-URN
emit). Discovery-driven: the source columns that ML features trace to are
DISCOVERED from the live datapack at runtime — nothing about the datapack is
hardcoded. Feature `sources` are wired to **schemaField URNs** (column-level), so a
dropped column has a real downstream path (see the DISCREPANCY note in
docs/API-NOTES.md).

Creates on top of existing datasets:
  - 2 mlModelGroups:  churn_model, ltv_model
  - 4 mlModels:       churn_model_v1/v2/v3, ltv_model_v1
  - 3 mlFeatureTables: customer_features, order_features, session_features
  - 12 mlFeatures spread across those tables, each with real schemaField sources
  - 2 mlModelDeployments attached ONLY to churn_model_v3 (deployed/not distinction)
  - 4 dataProcessInstance training runs (MLFLOW_TRAINING_RUN subtype), one per
    model version, each with input datasets, hyperparameters, and metrics

Prints a summary + which source columns were chosen (and why) and writes all URNs
to scripts/seeded_urns.json for later phases.

Run:  .venv/bin/python scripts/seed_ml_graph.py            # emit + write json
      .venv/bin/python scripts/seed_ml_graph.py --dry-run  # discover + print only

All SDK calls are verified by introspection in docs/API-NOTES.md. NOTE: not yet
executed against a live instance — run verify_cll.py first.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import datahub.emitter.mce_builder as b
import datahub.metadata.schema_classes as models
from datahub.api.entities.dataprocess.dataprocess_instance import DataProcessInstance
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.urns import DatasetUrn

from _datahub_env import get_graph

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed_ml_graph")

REPO_ROOT = Path(__file__).resolve().parent.parent
URNS_OUT = Path(__file__).resolve().parent / "seeded_urns.json"

MODEL_PLATFORM = "mlflow"
FEATURE_PLATFORM = "feast"
DEPLOY_PLATFORM = "sagemaker"
ENV = "PROD"

PREFERRED_PLATFORMS = ("dbt", "snowflake", "bigquery", "redshift", "postgres", "hive")
KEYISH = ("id", "_id", "key", "pk", "uuid", "guid")

# Feature-table -> feature names (12 features total: 5 + 4 + 3).
FEATURE_TABLES: dict[str, list[str]] = {
    "customer_features": [
        "days_since_signup", "lifetime_order_count", "avg_order_value",
        "is_active_30d", "loyalty_tier",
    ],
    "order_features": [
        "order_total_avg", "order_item_count", "discount_amount", "is_first_order",
    ],
    "session_features": [
        "session_count_7d", "avg_session_duration", "last_session_recency",
    ],
}

# Which feature tables each model consumes.
MODELS: dict[str, dict] = {
    "churn_model_v1": {"group": "churn_model", "version": "1",
                       "tables": ["customer_features", "session_features"],
                       "metrics": {"auc": "0.78", "recall": "0.71"},
                       "hyper": {"max_depth": "5", "n_estimators": "200"}},
    "churn_model_v2": {"group": "churn_model", "version": "2",
                       "tables": ["customer_features", "session_features"],
                       "metrics": {"auc": "0.80", "recall": "0.74"},
                       "hyper": {"max_depth": "6", "n_estimators": "300"}},
    "churn_model_v3": {"group": "churn_model", "version": "3",
                       "tables": ["customer_features", "session_features"],
                       "metrics": {"auc": "0.83", "recall": "0.77"},
                       "hyper": {"max_depth": "6", "n_estimators": "400"},
                       "deployed": True},
    "ltv_model_v1": {"group": "ltv_model", "version": "1",
                     "tables": ["customer_features", "order_features"],
                     "metrics": {"rmse": "42.5", "mae": "31.0"},
                     "hyper": {"learning_rate": "0.05", "num_leaves": "64"}},
}


def _platform_of(urn: str) -> str:
    marker = "dataPlatform:"
    return urn.split(marker, 1)[1].split(",", 1)[0] if marker in urn else "?"


def _is_keyish(field_path: str, is_key: bool | None) -> bool:
    low = field_path.lower()
    return bool(is_key) or any(k in low for k in KEYISH)


def discover_source_columns(graph, n_needed: int) -> list[dict]:
    """Discover (dataset_urn, column, native_type, keyish) pairs from the datapack.

    Spreads picks across as many distinct datasets as possible, prefers non-key
    columns (more plausibly 'droppable'), and is deterministic (sorted).
    """
    all_urns = list(graph.get_urns_by_filter(entity_types=["dataset"], batch_size=1000))

    def sort_key(u: str):
        plat = _platform_of(u)
        rank = PREFERRED_PLATFORMS.index(plat) if plat in PREFERRED_PLATFORMS else 99
        return (rank, u)

    datasets = sorted(all_urns, key=sort_key)
    # Build per-dataset column lists (non-key first).
    per_dataset: list[tuple[str, list[dict]]] = []
    for urn in datasets:
        sm = graph.get_schema_metadata(urn)
        if not sm or not sm.fields:
            continue
        cols = [
            {"dataset_urn": urn, "column": f.fieldPath,
             "native_type": f.nativeDataType,
             "keyish": _is_keyish(f.fieldPath, f.isPartOfKey)}
            for f in sm.fields
        ]
        cols.sort(key=lambda c: (c["keyish"], c["column"]))
        if cols:
            per_dataset.append((urn, cols))
        if len(per_dataset) >= n_needed * 2:  # enough spread
            break

    if not per_dataset:
        raise RuntimeError(
            "No datasets with schema fields found. Is the datapack ingested?"
        )

    # Round-robin: take column 0 from each dataset, then column 1, etc.
    picks: list[dict] = []
    depth = 0
    while len(picks) < n_needed:
        progressed = False
        for _urn, cols in per_dataset:
            if depth < len(cols):
                picks.append(cols[depth])
                progressed = True
                if len(picks) == n_needed:
                    break
        depth += 1
        if not progressed:
            break
    if len(picks) < n_needed:
        raise RuntimeError(
            f"Only discovered {len(picks)} source columns; need {n_needed}. "
            "Datapack is smaller than expected."
        )
    return picks


def build_plan(graph) -> dict:
    """Assign discovered columns to the 12 feature slots and compute all URNs."""
    feature_names = [(t, f) for t, fs in FEATURE_TABLES.items() for f in fs]
    n = len(feature_names)
    sources = discover_source_columns(graph, n)

    features: dict[str, dict] = {}
    for (table, feat), src in zip(feature_names, sources):
        feat_urn = b.make_ml_feature_urn(table, feat)
        sf_urn = b.make_schema_field_urn(src["dataset_urn"], src["column"])
        features[feat_urn] = {
            "table": table, "name": feat,
            "source_dataset": src["dataset_urn"], "source_column": src["column"],
            "source_native_type": src["native_type"],
            "schema_field_urn": sf_urn, "keyish": src["keyish"],
        }

    feature_tables = {
        b.make_ml_feature_table_urn(FEATURE_PLATFORM, t): {
            "name": t,
            "feature_urns": [u for u, fv in features.items() if fv["table"] == t],
        }
        for t in FEATURE_TABLES
    }
    table_urn_by_name = {v["name"]: u for u, v in feature_tables.items()}

    groups = {
        b.make_ml_model_group_urn(MODEL_PLATFORM, g, ENV): {"name": g}
        for g in {m["group"] for m in MODELS.values()}
    }
    group_urn_by_name = {v["name"]: u for u, v in groups.items()}

    model_plan: dict[str, dict] = {}
    for model_name, spec in MODELS.items():
        model_urn = b.make_ml_model_urn(MODEL_PLATFORM, model_name, ENV)
        feat_urns = [u for u, fv in features.items() if fv["table"] in spec["tables"]]
        source_datasets = sorted(
            {features[u]["source_dataset"] for u in feat_urns}
        )
        dpi = DataProcessInstance(
            id=f"{model_name}-training-run",
            orchestrator=MODEL_PLATFORM,
            subtype="MLFLOW_TRAINING_RUN",
            inlets=[DatasetUrn.from_string(d) for d in source_datasets],
        )
        deployments = []
        if spec.get("deployed"):
            deployments = [
                b.make_ml_model_deployment_urn(DEPLOY_PLATFORM, f"{model_name}-prod", ENV),
                b.make_ml_model_deployment_urn(DEPLOY_PLATFORM, f"{model_name}-canary", ENV),
            ]
        model_plan[model_urn] = {
            "name": model_name,
            "version": spec["version"],
            "group_urn": group_urn_by_name[spec["group"]],
            "feature_urns": feat_urns,
            "training_run_urn": str(dpi.urn),
            "training_inlets": source_datasets,
            "deployment_urns": deployments,
            "metrics": spec["metrics"],
            "hyper": spec["hyper"],
            "_dpi": dpi,  # not serialized
        }

    # Demo drop target: first non-keyish feature source of customer_features.
    cust_feats = [u for u, fv in features.items() if fv["table"] == "customer_features"]
    target_feat = next(
        (u for u in cust_feats if not features[u]["keyish"]), cust_feats[0]
    )
    tf = features[target_feat]
    downstream_models = [
        mu for mu, mv in model_plan.items() if target_feat in mv["feature_urns"]
    ]
    downstream_deploys = [
        d for mu in downstream_models for d in model_plan[mu]["deployment_urns"]
    ]
    demo_target = {
        "source_dataset": tf["source_dataset"],
        "source_column": tf["source_column"],
        "schema_field_urn": tf["schema_field_urn"],
        "feature_urn": target_feat,
        "feature_table": table_urn_by_name["customer_features"],
        "downstream_models": downstream_models,
        "downstream_deployments": downstream_deploys,
    }

    return {
        "features": features,
        "feature_tables": feature_tables,
        "groups": groups,
        "models": model_plan,
        "demo_drop_target": demo_target,
    }


def emit_plan(graph, plan: dict) -> None:
    ts = int(time.time() * 1000)

    def emit(entity_urn: str, aspect) -> None:
        graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=entity_urn, aspect=aspect))

    # Groups
    for urn, g in plan["groups"].items():
        emit(urn, models.MLModelGroupPropertiesClass(
            name=g["name"], description=f"Blastradar seed group: {g['name']}"))

    # Features (column-level sources) then feature tables
    for urn, fv in plan["features"].items():
        emit(urn, models.MLFeaturePropertiesClass(
            description=f"{fv['name']} (from {fv['source_column']})",
            sources=[fv["schema_field_urn"]]))
    for urn, ft in plan["feature_tables"].items():
        emit(urn, models.MLFeatureTablePropertiesClass(
            description=f"Blastradar seed feature table: {ft['name']}",
            mlFeatures=ft["feature_urns"]))

    # Deployments
    for _mu, mv in plan["models"].items():
        for d in mv["deployment_urns"]:
            emit(d, models.MLModelDeploymentPropertiesClass(
                description=f"Deployment of {mv['name']}",
                status=models.DeploymentStatusClass.IN_SERVICE, createdAt=ts))

    # Training runs (dataProcessInstance) + run properties
    for _mu, mv in plan["models"].items():
        dpi: DataProcessInstance = mv["_dpi"]
        for mcp in dpi.generate_mcp(created_ts_millis=ts, materialize_iolets=False):
            graph.emit_mcp(mcp)
        emit(mv["training_run_urn"], models.MLTrainingRunPropertiesClass(
            id=f"{mv['name']}-training-run",
            hyperParams=[models.MLHyperParamClass(name=k, value=v)
                         for k, v in mv["hyper"].items()],
            trainingMetrics=[models.MLMetricClass(name=k, value=v)
                             for k, v in mv["metrics"].items()]))

    # Models (one MLModelProperties aspect carries everything)
    for urn, mv in plan["models"].items():
        emit(urn, models.MLModelPropertiesClass(
            name=mv["name"],
            description=f"Blastradar seed model {mv['name']}",
            version=models.VersionTagClass(versionTag=mv["version"]),
            groups=[mv["group_urn"]],
            mlFeatures=mv["feature_urns"],
            trainingJobs=[mv["training_run_urn"]],
            deployments=mv["deployment_urns"] or None,
            hyperParams=[models.MLHyperParamClass(name=k, value=v)
                         for k, v in mv["hyper"].items()],
            trainingMetrics=[models.MLMetricClass(name=k, value=v)
                             for k, v in mv["metrics"].items()]))


def serializable(plan: dict) -> dict:
    out = json.loads(json.dumps(plan, default=str))
    for mv in out["models"].values():
        mv.pop("_dpi", None)
    return out


def print_summary(plan: dict) -> None:
    logger.info("\n" + "=" * 72)
    logger.info("SEED PLAN — source columns chosen (discovered from the datapack)")
    logger.info("=" * 72)
    for _u, fv in plan["features"].items():
        flag = " [keyish]" if fv["keyish"] else ""
        logger.info("  %-22s <- %s.%s (%s)%s",
                    f"{fv['table']}.{fv['name']}",
                    fv["source_dataset"].split(",")[-2] if "," in fv["source_dataset"] else fv["source_dataset"],
                    fv["source_column"], fv["source_native_type"], flag)
    dt = plan["demo_drop_target"]
    logger.info("\nDEMO DROP TARGET (column we can drop in a demo PR):")
    logger.info("  column      : %s.%s", dt["source_dataset"], dt["source_column"])
    logger.info("  schemaField : %s", dt["schema_field_urn"])
    logger.info("  -> feature  : %s", dt["feature_urn"])
    logger.info("  -> models   : %s", ", ".join(dt["downstream_models"]) or "(none)")
    logger.info("  -> deploys  : %s", ", ".join(dt["downstream_deployments"]) or "(none)")
    logger.info("\nWhy: it is a non-key column feeding a churn_model feature whose "
                "v3 is deployed — the exact silent-degradation scenario.")
    logger.info("=" * 72)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="discover + print the plan; do not emit or write json")
    args = ap.parse_args()

    graph = get_graph()
    logger.info("Discovering source columns from the datapack...")
    plan = build_plan(graph)
    print_summary(plan)

    if args.dry_run:
        logger.info("\n[--dry-run] nothing emitted, seeded_urns.json not written.")
        return 0

    logger.info("\nEmitting ML graph to DataHub...")
    emit_plan(graph, plan)
    URNS_OUT.write_text(json.dumps(serializable(plan), indent=2))
    logger.info("Wrote %s", URNS_OUT)
    logger.info(
        "Created: %d groups, %d models, %d feature tables, %d features, "
        "%d deployments, %d training runs.",
        len(plan["groups"]), len(plan["models"]), len(plan["feature_tables"]),
        len(plan["features"]),
        sum(len(m["deployment_urns"]) for m in plan["models"].values()),
        len(plan["models"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
