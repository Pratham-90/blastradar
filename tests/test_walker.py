"""Tests for the Phase 1B walker.

Two layers, both offline (architectural rule 3 — no Docker, no network):

  * cycle-safety and the hop cap use a hand-built ``FakeClient`` (a real graph has no
    cycles to induce);
  * the end-to-end cases run the walker against the **recorded** DataHub fixtures via
    the ``replay_client`` fixture (see ``conftest.py``). These are the former live
    tests, now reproducible with no instance running. Regenerate the recording with
    ``make record-fixtures``.
"""

from __future__ import annotations

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


# --------------------------------------------------------------------------- #
# Fake client for cycle / hop-cap safety (no fixtures needed)
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
# End-to-end cases against the recorded DataHub fixtures (offline)
# --------------------------------------------------------------------------- #
def _walk(replay_client, table=DEMO_TABLE, column=DEMO_COLUMN, **kw):
    return walk(ChangeEvent(kind=ChangeKind.DROP_COLUMN, table=table, column=column),
                client=replay_client, resolver=Resolver(replay_client), **kw)


def test_known_column_reaches_known_model(replay_client) -> None:
    graph = _walk(replay_client)
    model_urns = {a.urn for a in graph.models}
    assert CHURN_V3 in model_urns
    churn = next(a for a in graph.models if a.urn == CHURN_V3)
    # correct path shape: column -> feature -> model
    assert [h.edge_kind for h in churn.paths[0].hops] == ["derived_from", "consumes"]
    # trained-on detection + a live deployment
    assert churn.training is not None and churn.training.trained_on is True
    assert any(d.status == "IN_SERVICE" for d in churn.deployments)


def test_training_distinction_inference_only(replay_client) -> None:
    graph = _walk(replay_client)
    react = next((a for a in graph.models if a.urn == REACTIVATION), None)
    assert react is not None
    # deployed but NOT trained on the changed dataset — the differentiating case.
    assert react.training is not None and react.training.trained_on is False
    assert react.deployments  # it IS deployed


def test_column_with_no_ml_downstream_is_empty(replay_client) -> None:
    # phone_number is a real column but is not wired to any feature.
    graph = _walk(replay_client, column="phone_number")
    assert graph.resolution.status is ResolutionStatus.RESOLVED
    assert graph.terminals == ()  # empty result, not an error


def test_unresolvable_table_is_clean(replay_client) -> None:
    graph = _walk(replay_client, table="totally_made_up_xyz", column="foo")
    assert graph.resolution.status is ResolutionStatus.UNRESOLVED
    assert graph.terminals == ()


def test_hop_cap_respected(replay_client) -> None:
    graph = _walk(replay_client, max_hops=1)
    assert graph.models == ()  # models are 2 hops away
    assert any("hop cap" in n for n in graph.notes)


def test_walk_is_deterministic(replay_client) -> None:
    def run():
        g = _walk(replay_client)
        return [(a.urn, tuple(p.urns for p in a.paths)) for a in g.terminals]
    assert run() == run()
