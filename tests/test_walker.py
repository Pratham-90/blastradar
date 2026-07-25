"""Tests for the Phase 1B walker.

Cycle-safety and hop-cap use a FakeClient (a live graph has no cycles to induce).
The remaining cases run against the local DataHub and skip if it is unreachable.
"""

from __future__ import annotations

import socket

import pytest

from blastradar.datahub.client import ClientConfig, DataHubClient
from blastradar.datahub.resolver import Resolver
from blastradar.datahub.walker import walk
from blastradar.models import (
    ChangeEvent,
    ChangeKind,
    ResolutionStatus,
    ResolvedColumn,
)

# Demo target (seeded in Phase 0).
DEMO_TABLE, DEMO_COLUMN = "customers", "customer_since"
CHURN_V3 = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model_v3,PROD)"
REACTIVATION = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,reactivation_model_v1,PROD)"


def _gms_up() -> bool:
    try:
        with socket.create_connection(("localhost", 8080), timeout=1):
            return True
    except OSError:
        return False


live = pytest.mark.skipif(not _gms_up(), reason="local DataHub GMS not reachable on :8080")


# --------------------------------------------------------------------------- #
# Fake client for cycle / hop-cap safety (no network)
# --------------------------------------------------------------------------- #
class FakeResolver:
    def __init__(self, dataset_urn: str, column: str) -> None:
        self._dataset_urn = dataset_urn
        self._column = column

    def resolve_column(self, table: str, column: str | None) -> ResolvedColumn:
        return ResolvedColumn(
            table=table, column=self._column, status=ResolutionStatus.RESOLVED,
            dataset_urn=self._dataset_urn,
            schema_field_urn=f"urn:li:schemaField:({self._dataset_urn},{self._column})",
        )


class FakeClient:
    """Minimal stand-in exposing only the methods the walker calls."""

    def __init__(self, *, col_lineage=None, tabular=None, features=None,
                 models=None, training=None) -> None:
        self.col_lineage = col_lineage or {}      # urn -> [downstream dataset urns]
        self.tabular = tabular or {}              # urn -> [downstream urns (feature/model)]
        self.features = features or {}            # feature urn -> {custom_properties}
        self.models = models or {}                # model urn -> dict
        self.training = training or {}            # dpi urn -> [input dataset urns]

    def get_lineage(self, urn, *, column=None, direction="downstream", max_hops=1, count=500):
        if column is not None:
            return [{"urn": d, "type": "DATASET",
                     "paths": [{"urn": d, "entity_name": d, "column_name": column}]}
                    for d in self.col_lineage.get(urn, [])]
        return [{"urn": x, "type": "", "paths": []} for x in self.tabular.get(urn, [])]

    def get_ml_feature(self, urn):
        return self.features.get(urn)

    def get_ml_model(self, urn):
        return self.models.get(urn)

    def get_deployment(self, urn):
        return {"urn": urn, "status": "IN_SERVICE"}

    def get_training_inputs(self, dpi_urn):
        return self.training.get(dpi_urn, [])

    def get_ownership(self, urn):
        return []

    def get_tags(self, urn):
        return []

    def get_upstream_transform(self, downstream_urn, upstream_urn):
        return None


D0 = "urn:li:dataset:(urn:li:dataPlatform:dbt,D0,PROD)"
D1 = "urn:li:dataset:(urn:li:dataPlatform:dbt,D1,PROD)"
FEAT = "urn:li:mlFeature:(t,f)"
MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,m,PROD)"


def _change() -> ChangeEvent:
    return ChangeEvent(kind=ChangeKind.DROP_COLUMN, table="t", column="col")


def test_cycle_safety_terminates() -> None:
    # D0 <-> D1 forms a column-lineage cycle; the walk must terminate.
    client = FakeClient(col_lineage={D0: [D1], D1: [D0]})
    graph = walk(_change(), client=client, resolver=FakeResolver(D0, "col"),
                 max_hops=10)
    assert graph.terminals == ()
    assert graph.visited_count <= 2  # D0 and D1 each expanded at most once


def test_hop_cap_blocks_deep_terminal() -> None:
    client = FakeClient(
        tabular={D0: [FEAT], FEAT: [MODEL]},
        features={FEAT: {"custom_properties": {"blastradar.source_column": "col"}}},
        models={MODEL: {"name": "m", "deployments": [], "training_jobs": [], "groups": [],
                        "version": "1"}},
    )
    resolver = FakeResolver(D0, "col")
    # max_hops=1: the feature (hop 1) cannot expand to the model (hop 2).
    capped = walk(_change(), client=client, resolver=resolver, max_hops=1)
    assert capped.models == ()
    assert any("hop cap" in n for n in capped.notes)
    # max_hops=6: the model is reached.
    full = walk(_change(), client=client, resolver=resolver, max_hops=6)
    assert [a.urn for a in full.models] == [MODEL]


# --------------------------------------------------------------------------- #
# Live tests
# --------------------------------------------------------------------------- #
@pytest.fixture()
def live_client() -> DataHubClient:
    return DataHubClient(ClientConfig(server="http://localhost:8080", token=None))


@live
def test_known_column_reaches_known_model(live_client: DataHubClient) -> None:
    graph = walk(ChangeEvent(kind=ChangeKind.DROP_COLUMN, table=DEMO_TABLE, column=DEMO_COLUMN),
                 client=live_client, resolver=Resolver(live_client))
    model_urns = {a.urn for a in graph.models}
    assert CHURN_V3 in model_urns
    churn = next(a for a in graph.models if a.urn == CHURN_V3)
    # correct path shape: column -> feature -> model
    assert [h.edge_kind for h in churn.paths[0].hops] == ["derived_from", "consumes"]
    # trained-on detection + a live deployment
    assert churn.training is not None and churn.training.trained_on is True
    assert any(d.status == "IN_SERVICE" for d in churn.deployments)


@live
def test_training_distinction_inference_only(live_client: DataHubClient) -> None:
    graph = walk(ChangeEvent(kind=ChangeKind.DROP_COLUMN, table=DEMO_TABLE, column=DEMO_COLUMN),
                 client=live_client, resolver=Resolver(live_client))
    react = next((a for a in graph.models if a.urn == REACTIVATION), None)
    assert react is not None
    # deployed but NOT trained on the changed dataset — the differentiating case.
    assert react.training is not None and react.training.trained_on is False
    assert react.deployments  # it IS deployed


@live
def test_column_with_no_ml_downstream_is_empty(live_client: DataHubClient) -> None:
    # phone_number is a real column but is not wired to any feature.
    graph = walk(ChangeEvent(kind=ChangeKind.DROP_COLUMN, table=DEMO_TABLE, column="phone_number"),
                 client=live_client, resolver=Resolver(live_client))
    assert graph.resolution.status is ResolutionStatus.RESOLVED
    assert graph.terminals == ()  # empty result, not an error


@live
def test_unresolvable_table_is_clean(live_client: DataHubClient) -> None:
    graph = walk(ChangeEvent(kind=ChangeKind.DROP_COLUMN, table="totally_made_up_xyz", column="foo"),
                 client=live_client, resolver=Resolver(live_client))
    assert graph.resolution.status is ResolutionStatus.UNRESOLVED
    assert graph.terminals == ()


@live
def test_hop_cap_respected_live(live_client: DataHubClient) -> None:
    graph = walk(ChangeEvent(kind=ChangeKind.DROP_COLUMN, table=DEMO_TABLE, column=DEMO_COLUMN),
                 client=live_client, resolver=Resolver(live_client), max_hops=1)
    assert graph.models == ()  # models are 2 hops away
    assert any("hop cap" in n for n in graph.notes)


@live
def test_walk_is_deterministic(live_client: DataHubClient) -> None:
    def run():
        g = walk(ChangeEvent(kind=ChangeKind.DROP_COLUMN, table=DEMO_TABLE, column=DEMO_COLUMN),
                 client=live_client, resolver=Resolver(live_client))
        return [(a.urn, tuple(p.urns for p in a.paths)) for a in g.terminals]
    assert run() == run()
