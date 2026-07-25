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

# Curated, semantically-plausible source columns per feature. Each entry is an
# ordered list of (table_keyword, column_keyword) candidates; the resolver picks
# the first that matches a real discovered dataset+column, then falls back to any
# themed column, then any column (so it degrades gracefully on other datapacks).
FEATURE_SOURCES: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("customer_features", "days_since_signup"):    [("customers", "customer_since")],
    ("customer_features", "lifetime_order_count"): [("order_history", "order_id"), ("orders", "order_id")],
    ("customer_features", "avg_order_value"):      [("orders", "order_total"), ("order_details", "order_total")],
    ("customer_features", "is_active_30d"):        [("order_history", "as_of_date")],
    ("customer_features", "loyalty_tier"):         [("customers", "customer_class")],
    ("order_features", "order_total_avg"):         [("order_details", "order_total"), ("orders", "order_total")],
    ("order_features", "order_item_count"):        [("order_items", "quantity")],
    ("order_features", "discount_amount"):         [("order_items", "unit_price"), ("orders", "cost_of_delivery")],
    ("order_features", "is_first_order"):          [("orders", "order_date")],
    ("session_features", "session_count_7d"):      [("order_history", "order_status"), ("orders", "order_status")],
    ("session_features", "avg_session_duration"):  [("order_items", "dispatch_date"), ("orders", "order_mode")],
    ("session_features", "last_session_recency"):  [("order_history", "as_of_date")],
}
# Feature table -> theme keyword for the themed fallback.
TABLE_THEME = {"customer_features": "customer", "order_features": "order",
               "session_features": "order"}
PREFERRED_SRC_PLATFORMS = ("dbt", "snowflake", "bigquery", "redshift", "postgres")

# Which feature tables each model consumes, plus VARIED ownership + tags so scoring
# escalation and PR attribution aren't uniform:
#   - `owner`: a CorpGroup name, or None (unowned — attribution must degrade gracefully)
#   - `tags`:  tag names; a "Tier1"/"Tier2" tag drives tag-based severity escalation
MODELS: dict[str, dict] = {
    "churn_model_v1": {"group": "churn_model", "version": "1",
                       "tables": ["customer_features", "session_features"],
                       "metrics": {"auc": "0.78", "recall": "0.71"},
                       "hyper": {"max_depth": "5", "n_estimators": "200"},
                       "owner": "ml-platform", "tags": ["Tier2"]},
    "churn_model_v2": {"group": "churn_model", "version": "2",
                       "tables": ["customer_features", "session_features"],
                       "metrics": {"auc": "0.80", "recall": "0.74"},
                       "hyper": {"max_depth": "6", "n_estimators": "300"},
                       "owner": None, "tags": []},  # UNOWNED — graceful attribution case
    "churn_model_v3": {"group": "churn_model", "version": "3",
                       "tables": ["customer_features", "session_features"],
                       "metrics": {"auc": "0.83", "recall": "0.77"},
                       "hyper": {"max_depth": "6", "n_estimators": "400"},
                       "deployed": True,
                       "owner": "ml-platform", "tags": ["Tier1"]},
    # UNOWNED + untagged, and NOT deployed. It consumes order_features (which only it
    # consumes), so a change to an order_features source column reaches ltv_model_v1
    # alone — a clean "no deployment, no escalation" case that scores a genuine MEDIUM
    # (the Task 6 medium example). Kept unowned deliberately so severity escalation is
    # exercised by the churn/reactivation models, not here.
    "ltv_model_v1": {"group": "ltv_model", "version": "1",
                     "tables": ["customer_features", "order_features"],
                     "metrics": {"rmse": "42.5", "mae": "31.0"},
                     "hyper": {"learning_rate": "0.05", "num_leaves": "64"},
                     "owner": None, "tags": []},
    # DEPLOYED but trained on a DIFFERENT dataset (order_details, NOT customers).
    # It consumes customer_features — so it reads days_since_signup (derived from
    # customers.customer_since) at INFERENCE time without having been trained on it.
    # This exercises the "deployed + inference-only" severity branch (HIGH).
    "reactivation_model_v1": {"group": "reactivation_model", "version": "1",
                              "tables": ["customer_features"],
                              "train_inputs": ["order_details"],  # override: excludes customers
                              "metrics": {"auc": "0.75", "precision": "0.68"},
                              "hyper": {"max_depth": "4", "n_estimators": "150"},
                              "deployed": True,
                              "owner": "growth-ml", "tags": []},  # owned, no tier tag
}

# Tag display metadata (name -> (description, colorHex)).
TAG_META: dict[str, tuple[str, str]] = {
    "Tier1": ("Tier-1 production model — highest business criticality", "#d93f0b"),
    "Tier2": ("Tier-2 production model", "#fbca04"),
}


def _platform_of(urn: str) -> str:
    marker = "dataPlatform:"
    return urn.split(marker, 1)[1].split(",", 1)[0] if marker in urn else "?"


def _is_keyish(field_path: str, is_key: bool | None) -> bool:
    low = field_path.lower()
    return bool(is_key) or any(k in low for k in KEYISH)


def _short_table(urn: str) -> str:
    """Short table name from a dataset URN (last dotted/slashed segment)."""
    body = urn.split("dataPlatform:", 1)[1] if "dataPlatform:" in urn else urn
    name = body.split(",")[1] if "," in body else body
    return name.split(".")[-1].split("/")[-1].lower()


def index_datasets(graph) -> dict[str, tuple[str, dict[str, tuple[str, str, bool]]]]:
    """short_table -> (dataset_urn, {col_lower: (fieldPath, native_type, is_key)}).

    DB-backed listing (authoritative, no search-index lag). When several platforms
    share a table name, prefer dbt/warehouse platforms.
    """
    idx: dict[str, tuple[str, dict]] = {}
    for urn in graph.list_all_entity_urns("dataset", 0, 1000) or []:
        sm = graph.get_schema_metadata(urn)
        if not sm or not sm.fields:
            continue
        cols = {
            f.fieldPath.lower(): (f.fieldPath, f.nativeDataType,
                                  _is_keyish(f.fieldPath, f.isPartOfKey))
            for f in sm.fields
        }
        short = _short_table(urn)
        plat = _platform_of(urn)
        rank = PREFERRED_SRC_PLATFORMS.index(plat) if plat in PREFERRED_SRC_PLATFORMS else 99
        if short not in idx:
            idx[short] = (urn, cols, rank)  # type: ignore[assignment]
        else:
            if rank < idx[short][2]:  # type: ignore[index]
                idx[short] = (urn, cols, rank)  # type: ignore[assignment]
    return {k: (v[0], v[1]) for k, v in idx.items()}


def _match(idx, table_kw: str, col_kw: str):
    """Find (dataset_urn, fieldPath, native_type, keyish) by table + column keyword."""
    for short, (urn, cols) in idx.items():
        if table_kw not in short:
            continue
        if col_kw in cols:  # exact column
            fp, nt, key = cols[col_kw]
            return urn, fp, nt, key
        for cl, (fp, nt, key) in cols.items():  # substring column
            if col_kw in cl:
                return urn, fp, nt, key
    return None


def _themed_fallback(idx, theme_kw: str, used: set[str]):
    """Any non-key column from a table matching the feature-table theme."""
    for short, (urn, cols) in sorted(idx.items()):
        if theme_kw not in short:
            continue
        for _cl, (fp, nt, key) in sorted(cols.items()):
            sf = b.make_schema_field_urn(urn, fp)
            if not key and sf not in used:
                return urn, fp, nt, key
    return None


def _resolve_dataset(idx, table_kw: str) -> str | None:
    """First dataset URN whose short table name matches a keyword."""
    for short, (urn, _cols) in sorted(idx.items()):
        if table_kw in short:
            return urn
    return None


def resolve_feature_sources(idx) -> list[dict]:
    """Resolve each feature to a plausible real (dataset, column). Deterministic."""
    if not idx:
        raise RuntimeError("No datasets with schema fields found. Is the datapack ingested?")

    feature_names = [(t, f) for t, fs in FEATURE_TABLES.items() for f in fs]
    picks: list[dict] = []
    used: set[str] = set()
    for table, feat in feature_names:
        hit = None
        for table_kw, col_kw in FEATURE_SOURCES.get((table, feat), []):
            hit = _match(idx, table_kw, col_kw)
            if hit:
                break
        if hit is None:
            hit = _themed_fallback(idx, TABLE_THEME.get(table, ""), used)
        if hit is None:  # last resort: any column anywhere
            some_urn, some_cols = next(iter(idx.items()))[1]
            fp, nt, key = next(iter(some_cols.values()))
            hit = (some_urn, fp, nt, key)
        urn, fp, nt, key = hit
        used.add(b.make_schema_field_urn(urn, fp))
        picks.append({"dataset_urn": urn, "column": fp, "native_type": nt, "keyish": key})
    return picks


def build_plan(graph) -> dict:
    """Assign discovered columns to the 12 feature slots and compute all URNs."""
    idx = index_datasets(graph)
    feature_names = [(t, f) for t, fs in FEATURE_TABLES.items() for f in fs]
    sources = resolve_feature_sources(idx)

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
        if spec.get("train_inputs"):
            # Trained on explicit datasets (may differ from consumed-feature sources),
            # modelling a model that reads a feature at inference without training on it.
            source_datasets = sorted(
                {d for kw in spec["train_inputs"] if (d := _resolve_dataset(idx, kw))}
            )
        else:
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
            "owner": spec.get("owner"),
            "owner_urn": b.make_group_urn(spec["owner"]) if spec.get("owner") else None,
            "tags": list(spec.get("tags") or []),
            "tag_urns": [b.make_tag_urn(t) for t in (spec.get("tags") or [])],
            "_dpi": dpi,  # not serialized
        }

    # Demo drop target: prefer days_since_signup (customers.customer_since — a
    # believable "rename the signup column" break), else first non-key customer feature.
    cust_feats = [u for u, fv in features.items() if fv["table"] == "customer_features"]
    preferred = b.make_ml_feature_urn("customer_features", "days_since_signup")
    target_feat = next(
        (u for u in cust_feats if u == preferred and not features[u]["keyish"]),
        next((u for u in cust_feats if not features[u]["keyish"]), cust_feats[0]),
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

    # Features: GMS requires `sources` to be DATASET urns (schemaField is rejected
    # at /sources/*), so we link the dataset and record the exact column in
    # customProperties for our deterministic core to read. (See API-NOTES.)
    for urn, fv in plan["features"].items():
        emit(urn, models.MLFeaturePropertiesClass(
            description=f"{fv['name']} (derived from {fv['source_column']})",
            sources=[fv["source_dataset"]],
            customProperties={
                "blastradar.source_column": fv["source_column"],
                "blastradar.source_dataset": fv["source_dataset"],
                "blastradar.source_schema_field": fv["schema_field_urn"],
            }))
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

    # Tag + CorpGroup entities referenced by models (created once, idempotent).
    referenced_tags = {t for mv in plan["models"].values() for t in mv["tags"]}
    for tag in sorted(referenced_tags):
        desc, color = TAG_META.get(tag, (f"Blastradar tag {tag}", None))
        emit(b.make_tag_urn(tag), models.TagPropertiesClass(
            name=tag, description=desc, colorHex=color))
    referenced_owners = {mv["owner"] for mv in plan["models"].values() if mv["owner"]}
    for grp in sorted(referenced_owners):
        emit(b.make_group_urn(grp), models.CorpGroupInfoClass(
            admins=[], members=[], groups=[], displayName=f"@{grp}",
            description=f"Blastradar seed owner group @{grp}"))

    # Ownership + tags per model (varied: some unowned, some tagged for escalation).
    for urn, mv in plan["models"].items():
        if mv["owner_urn"]:
            emit(urn, models.OwnershipClass(owners=[models.OwnerClass(
                owner=mv["owner_urn"], type=models.OwnershipTypeClass.TECHNICAL_OWNER)]))
        else:
            # Explicitly emit an empty owners set so re-seeding a now-unowned model
            # CLEARS any owner from a prior seed (aspect emits replace in place).
            emit(urn, models.OwnershipClass(owners=[]))
        if mv["tag_urns"]:
            emit(urn, models.GlobalTagsClass(tags=[
                models.TagAssociationClass(tag=t) for t in mv["tag_urns"]]))
        else:
            # Clear any leftover tags (e.g. a `pending-upstream-change` from a prior
            # write-back run) so the seeded graph is a clean baseline — the write-back
            # tag then appears only after a real `make demo-live` write.
            emit(urn, models.GlobalTagsClass(tags=[]))


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
