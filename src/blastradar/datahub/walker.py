"""Deterministic downstream lineage walk: ChangeEvent -> impacted ML assets.

Architectural rule 1: this is plain, deterministic Python — no LLM, and the same
input always yields the same output (every collection is sorted before returning).

The graph is heterogeneous, so the walk is a HYBRID (see the traversability table in
docs/API-NOTES.md), crossing each edge the only way DataHub exposes it:

    changed column (schemaField)
      └─ column-level lineage ────────────▶ downstream dataset columns   (propagation)
      └─ table-level lineage + source-col ▶ mlFeature                     (derived_from)
                                              └─ table-level lineage ────▶ mlModel  (consumes)
                                                    └─ aspect read ──────▶ mlModelDeployment (deployed_to)

Column precision into features is recovered from the feature's
``blastradar.source_column`` custom property (feature ``sources`` are dataset-granular).
Deployments and training-run inputs are ASPECT READS — they are not lineage edges.

Task 4 (training-set detection) lives in :func:`_training_evidence`: a model was
TRAINED on the change iff the changed dataset is among its training run's inputs —
returned as a boolean plus the evidence (which run, which input dataset).
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque

from blastradar.datahub.client import DataHubClient
from blastradar.datahub.resolver import Resolver
from blastradar.datahub.urns import short_name, urn_type
from blastradar.models import (
    ChangeEvent,
    DeploymentDetail,
    ImpactedAsset,
    ImpactGraph,
    ImpactPath,
    PathHop,
    ResolutionStatus,
    TrainingEvidence,
)

logger = logging.getLogger(__name__)

ML_TERMINALS = frozenset({"mlModel", "mlModelDeployment"})
SOURCE_COLUMN_PROPERTY = "blastradar.source_column"

DEFAULT_MAX_HOPS = 6
DEFAULT_FRONTIER_CEILING = 2000


def _dataset_matches(target_urn: str, candidates: list[str]) -> str | None:
    """Return the candidate URN equal to target (exact, then case-insensitive)."""
    if target_urn in candidates:
        return target_urn
    low = target_urn.lower()
    return next((c for c in candidates if c.lower() == low), None)


def _neighbors(
    client: DataHubClient, urn: str, node_type: str, column: str | None,
) -> list[tuple[str, str, str | None, str, str | None]]:
    """Downstream neighbours of a node as (to_urn, to_type, to_column, edge_kind, transform).

    Sorted by URN for determinism. Only column-precise edges are followed.
    """
    out: list[tuple[str, str, str | None, str, str | None]] = []
    if node_type == "dataset":
        # (a) column-level propagation to downstream dataset columns.
        for r in client.get_lineage(urn, column=column, direction="downstream", max_hops=1):
            if urn_type(r["urn"]) == "dataset":
                paths = r.get("paths") or []
                to_col = paths[-1]["column_name"] if paths else column
                transform = client.get_upstream_transform(r["urn"], urn)
                out.append((r["urn"], "dataset", to_col, "column_lineage", transform))
        # (b) dataset -> mlFeature (table-level), kept only when the feature's recorded
        #     source column matches the column we are carrying.
        for r in client.get_lineage(urn, direction="downstream", max_hops=1):
            if urn_type(r["urn"]) != "mlFeature":
                continue
            feat = client.get_ml_feature(r["urn"]) or {}
            src_col = (feat.get("custom_properties") or {}).get(SOURCE_COLUMN_PROPERTY)
            if column is not None and src_col is not None and src_col.lower() == column.lower():
                out.append((r["urn"], "mlFeature", None, "derived_from", None))
    elif node_type == "mlFeature":
        for r in client.get_lineage(urn, direction="downstream", max_hops=1):
            if urn_type(r["urn"]) == "mlModel":
                out.append((r["urn"], "mlModel", None, "consumes", None))
    return sorted(out, key=lambda t: t[0])


def _training_evidence(
    client: DataHubClient, model: dict, changed_dataset_urn: str,
) -> TrainingEvidence:
    """Determine whether the model was TRAINED on the changed dataset (Task 4)."""
    runs = list(model.get("training_jobs") or [])
    for dpi in sorted(runs):
        inputs = client.get_training_inputs(dpi)
        matched = _dataset_matches(changed_dataset_urn, inputs)
        if matched is not None:
            return TrainingEvidence(
                trained_on=True, training_run_urn=dpi, matched_input_dataset=matched,
                input_datasets=tuple(sorted(inputs)),
            )
    # Not trained on it — still surface the (first) run's inputs as evidence.
    first = sorted(runs)[0] if runs else None
    inputs = client.get_training_inputs(first) if first else []
    return TrainingEvidence(
        trained_on=False, training_run_urn=first, matched_input_dataset=None,
        input_datasets=tuple(sorted(inputs)),
    )


def _model_deployments(client: DataHubClient, model: dict) -> list[tuple[str, str | None]]:
    """(deployment_urn, status) for each deployment attached to a model, sorted."""
    out = []
    for dep in sorted(model.get("deployments") or []):
        status = (client.get_deployment(dep) or {}).get("status")
        out.append((dep, status))
    return out


def _build_model_asset(
    client: DataHubClient, urn: str, paths: tuple[ImpactPath, ...],
    origin_dataset_urn: str,
) -> ImpactedAsset:
    """Fetch full detail for a model terminal: group, version, owners, tags, deploys, training."""
    model = client.get_ml_model(urn) or {}
    deployments = tuple(
        DeploymentDetail(urn=d, status=s) for d, s in _model_deployments(client, model)
    )
    groups = model.get("groups") or []
    return ImpactedAsset(
        urn=urn, entity_type="mlModel", name=model.get("name") or short_name(urn),
        paths=paths,
        owners=tuple(sorted(client.get_ownership(urn))),
        tags=tuple(sorted(client.get_tags(urn))),
        model_group=groups[0] if groups else None,
        version=model.get("version"),
        deployments=deployments,
        training=_training_evidence(client, model, origin_dataset_urn),
    )


def _build_deployment_asset(
    client: DataHubClient, urn: str, paths: tuple[ImpactPath, ...],
) -> ImpactedAsset:
    """Fetch full detail for a deployment terminal."""
    dep = client.get_deployment(urn) or {}
    return ImpactedAsset(
        urn=urn, entity_type="mlModelDeployment", name=short_name(urn), paths=paths,
        owners=tuple(sorted(client.get_ownership(urn))),
        tags=tuple(sorted(client.get_tags(urn))),
        deployment_status=dep.get("status"),
    )


def walk(
    change: ChangeEvent,
    *,
    client: DataHubClient,
    resolver: Resolver,
    max_hops: int = DEFAULT_MAX_HOPS,
    frontier_ceiling: int = DEFAULT_FRONTIER_CEILING,
) -> ImpactGraph:
    """Find every ML asset downstream of a changed column. Deterministic BFS.

    Resolves the column to a schemaField URN, then breadth-first traverses downstream,
    tracking the path to each node. A branch stops at an ML terminal or the hop cap;
    entities are de-duplicated but every distinct path is preserved. If the frontier
    exceeds ``frontier_ceiling`` the walk stops and the result is marked truncated.

    Returns an :class:`ImpactGraph`; on an unresolvable/ambiguous column it returns an
    empty graph carrying the resolution status (never raises for a miss).
    """
    resolved = resolver.resolve_column(change.table, change.column)
    if resolved.status is not ResolutionStatus.RESOLVED or resolved.schema_field_urn is None:
        logger.info("walk: column unresolved (%s): %s", resolved.status.value, resolved.note)
        return ImpactGraph(change=change, resolution=resolved, notes=(resolved.note,))

    source_urn = resolved.schema_field_urn
    origin_dataset = resolved.dataset_urn
    assert origin_dataset is not None
    start_column = resolved.column

    # BFS over partial paths. Item: (urn, type, column, hops, hop_count).
    frontier: deque[tuple[str, str, str | None, tuple[PathHop, ...], int]] = deque()
    frontier.append((origin_dataset, "dataset", start_column, (), 0))

    terminal_paths: dict[str, list[ImpactPath]] = defaultdict(list)
    terminal_types: dict[str, str] = {}
    expanded: set[tuple[str, str | None]] = set()
    visited_count = 0
    truncated = False
    truncation_reason = ""
    cap_hits = 0

    def record_terminal(to_urn: str, to_type: str, hops: tuple[PathHop, ...]) -> None:
        terminal_paths[to_urn].append(
            ImpactPath(change=change, source_urn=source_urn,
                       terminal_urn=to_urn, terminal_type=to_type, hops=hops))
        terminal_types[to_urn] = to_type

    while frontier:
        if len(frontier) > frontier_ceiling:
            truncated = True
            truncation_reason = f"frontier exceeded ceiling ({frontier_ceiling})"
            logger.warning("walk: %s", truncation_reason)
            break

        urn, node_type, column, hops, hop_count = frontier.popleft()
        if hop_count >= max_hops:
            cap_hits += 1
            continue
        key = (urn, column)
        if key in expanded:  # already expanded this (node, column) — cycle/dup guard
            continue
        expanded.add(key)
        visited_count += 1

        path_urns = {source_urn, origin_dataset, *(h.to_urn for h in hops)}
        for to_urn, to_type, to_col, edge_kind, transform in _neighbors(
            client, urn, node_type, column
        ):
            if to_urn in path_urns:  # per-path cycle guard
                continue
            hop = PathHop(from_urn=urn, to_urn=to_urn, to_type=to_type,
                          edge_kind=edge_kind, column=to_col, transform=transform,
                          hop_index=hop_count + 1)
            new_hops = (*hops, hop)
            if to_type in ML_TERMINALS:
                record_terminal(to_urn, to_type, new_hops)
                if to_type == "mlModel":
                    # Deployments are aspect reads, not lineage — attach as terminals.
                    model = client.get_ml_model(to_urn) or {}
                    for dep, _status in _model_deployments(client, model):
                        dep_hop = PathHop(from_urn=to_urn, to_urn=dep,
                                          to_type="mlModelDeployment",
                                          edge_kind="deployed_to",
                                          hop_index=hop_count + 2)
                        record_terminal(dep, "mlModelDeployment", (*new_hops, dep_hop))
                continue  # stop expanding past a terminal
            frontier.append((to_urn, to_type, to_col, new_hops, hop_count + 1))

    # Build terminal detail deterministically.
    assets: list[ImpactedAsset] = []
    for urn in sorted(terminal_paths):
        paths = tuple(sorted(terminal_paths[urn], key=lambda p: p.urns))
        if terminal_types[urn] == "mlModel":
            assets.append(_build_model_asset(client, urn, paths, origin_dataset))
        else:
            assets.append(_build_deployment_asset(client, urn, paths))

    notes: list[str] = []
    if cap_hits:
        notes.append(f"hop cap ({max_hops}) reached on {cap_hits} branch(es)")
    return ImpactGraph(
        change=change, resolution=resolved, terminals=tuple(assets),
        truncated=truncated, truncation_reason=truncation_reason,
        visited_count=visited_count, notes=tuple(notes),
    )
