"""Tests for Phase 1D write-back: the mutation gate, idempotency, and degradation.

No DataHub required — a small in-memory FakeClient records writes so we can assert
that a second run creates no duplicates, that the gate blocks writes, and that a
failing write degrades to a FAILED result instead of raising.
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from blastradar.datahub.writeback import (
    MUTATION_ENV,
    PENDING_TAG,
    WriteAction,
    WriteStatus,
    incident_urn_for,
    mutations_enabled,
    write_back,
)
from blastradar.models import (
    ChangeEvent,
    ChangeKind,
    DeploymentDetail,
    ImpactedAsset,
    ImpactPath,
    PathHop,
    PRContext,
    ScoredImpact,
    Severity,
    TrainingEvidence,
)

DS = "urn:li:dataset:(urn:li:dataPlatform:dbt,order_entry.customers,PROD)"
FEATURE = "urn:li:mlFeature:(customer_features,days_since_signup)"
TIER1 = "urn:li:tag:Tier1"
PR = PRContext(repo="order-entry/analytics", number=42,
               url="https://github.com/order-entry/analytics/pull/42", sha="abc123")
ENABLED = {MUTATION_ENV: "true"}


# --------------------------------------------------------------------------- #
# Fake DataHub client (records writes; enough surface for writeback)
# --------------------------------------------------------------------------- #
class FakeClient:
    def __init__(self, existing_tags: dict[str, list[str]] | None = None,
                 fail_on: str = "") -> None:
        self.incidents: dict[str, dict] = {}
        self.tags: dict[str, list[str]] = defaultdict(list, existing_tags or {})
        self.documents: dict[str, dict] = {}
        self.calls: dict[str, int] = defaultdict(int)
        self._fail_on = fail_on

    def get_incident(self, urn):
        self.calls["get_incident"] += 1
        return self.incidents.get(urn)

    def emit_incident(self, urn, *, entity_urns, title, description,
                      incident_type="DATA_SCHEMA", priority=None):
        self.calls["emit_incident"] += 1
        if self._fail_on == "incident":
            raise RuntimeError("boom-incident")
        self.incidents[urn] = {"urn": urn, "state": "ACTIVE", "title": title,
                               "description": description, "entities": list(entity_urns)}
        return urn

    def get_tags(self, urn):
        self.calls["get_tags"] += 1
        return list(self.tags.get(urn, []))

    def set_tags(self, urn, tag_urns):
        self.calls["set_tags"] += 1
        if self._fail_on == "tag":
            raise RuntimeError("boom-tag")
        self.tags[urn] = list(tag_urns)
        return list(tag_urns)

    def get_document(self, urn):
        self.calls["get_document"] += 1
        return self.documents.get(urn)

    def upsert_document(self, *, doc_id, title, text, subtype=None,
                        related_assets=None, custom_properties=None):
        self.calls["upsert_document"] += 1
        if self._fail_on == "document":
            raise RuntimeError("boom-doc")
        urn = f"urn:li:document:{doc_id}"
        self.documents[urn] = {"urn": urn, "title": title, "related": list(related_assets or [])}
        return urn


def make_scored(name, severity, *, trained=False, deployed=False,
                owners=(), tags=()) -> ScoredImpact:
    urn = f"urn:li:mlModel:(urn:li:dataPlatform:mlflow,{name},PROD)"
    change = ChangeEvent(kind=ChangeKind.DROP_COLUMN, table="customers", column="customer_since")
    hop = PathHop(from_urn=DS, to_urn=FEATURE, to_type="mlFeature", edge_kind="derived_from")
    path = ImpactPath(change=change, source_urn=f"urn:li:schemaField:({DS},customer_since)",
                      terminal_urn=urn, terminal_type="mlModel", hops=(hop,))
    deployments = ((DeploymentDetail(
        urn=f"urn:li:mlModelDeployment:(urn:li:dataPlatform:sagemaker,{name}-prod,PROD)",
        status="IN_SERVICE"),) if deployed else ())
    asset = ImpactedAsset(urn=urn, entity_type="mlModel", name=name, paths=(path,),
                          owners=tuple(owners), tags=tuple(tags), deployments=deployments,
                          training=TrainingEvidence(trained_on=trained))
    return ScoredImpact(asset=asset, severity=severity, trained_on=trained,
                        deployed=deployed, reasons=(f"{severity.value} rule",))


CHANGE = ChangeEvent(kind=ChangeKind.DROP_COLUMN, table="customers", column="customer_since")


# --------------------------------------------------------------------------- #
# The mutation gate
# --------------------------------------------------------------------------- #
def test_mutations_enabled_parsing():
    assert mutations_enabled({MUTATION_ENV: "true"}) is True
    assert mutations_enabled({MUTATION_ENV: "TRUE"}) is True
    assert mutations_enabled({MUTATION_ENV: "false"}) is False
    assert mutations_enabled({MUTATION_ENV: "1"}) is False
    assert mutations_enabled({}) is False


def test_disabled_by_default_writes_nothing():
    client = FakeClient()
    scored = [make_scored("churn_model_v3", Severity.CRITICAL, trained=True, deployed=True)]
    summary = write_back(scored, CHANGE, PR, "REPORT", client=client, dry_run=False, env={})
    # Nothing was written.
    assert client.calls == {} or all(v == 0 for v in client.calls.values())
    assert not client.incidents and not client.documents
    assert all(r.status is WriteStatus.DISABLED for r in summary.results)
    assert MUTATION_ENV in summary.note
    assert summary.ok  # a blocked run is not a failed run


def test_dry_run_plans_without_writing():
    client = FakeClient()
    scored = [make_scored("churn_model_v3", Severity.CRITICAL, trained=True, deployed=True)]
    summary = write_back(scored, CHANGE, PR, "REPORT", client=client, dry_run=True, env=ENABLED)
    assert all(r.status is WriteStatus.DRY_RUN for r in summary.results)
    assert not client.incidents and not client.documents
    # incident + tag per model, plus one document
    actions = [r.action for r in summary.results]
    assert actions.count(WriteAction.INCIDENT) == 1
    assert actions.count(WriteAction.DOCUMENT) == 1


# --------------------------------------------------------------------------- #
# The live write path + idempotency
# --------------------------------------------------------------------------- #
def test_live_writeback_creates_incident_tag_document():
    client = FakeClient(existing_tags={
        "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model_v3,PROD)": [TIER1]})
    scored = [make_scored("churn_model_v3", Severity.CRITICAL, trained=True, deployed=True,
                          tags=[TIER1])]
    summary = write_back(scored, CHANGE, PR, "REPORT", client=client, dry_run=False, env=ENABLED)

    statuses = {(r.action, r.status) for r in summary.results}
    assert (WriteAction.INCIDENT, WriteStatus.CREATED) in statuses
    assert (WriteAction.TAG, WriteStatus.CREATED) in statuses
    assert (WriteAction.DOCUMENT, WriteStatus.CREATED) in statuses
    # Incident anchored on the DATASET (mlModel is not a valid incident target).
    inc = next(iter(client.incidents.values()))
    assert inc["entities"] == [DS]
    # Tag merge preserved Tier1.
    model_urn = scored[0].asset.urn
    assert TIER1 in client.tags[model_urn]
    assert any(t.endswith(PENDING_TAG) for t in client.tags[model_urn])


def test_second_run_is_idempotent():
    client = FakeClient()
    scored = [make_scored("churn_model_v3", Severity.CRITICAL, trained=True, deployed=True)]

    first = write_back(scored, CHANGE, PR, "REPORT", client=client, dry_run=False, env=ENABLED)
    assert any(r.status is WriteStatus.CREATED for r in first.results)
    emits_after_first = client.calls["emit_incident"]
    settags_after_first = client.calls["set_tags"]

    second = write_back(scored, CHANGE, PR, "REPORT", client=client, dry_run=False, env=ENABLED)
    # No NEW incident emitted, no NEW tag set on the second run.
    assert client.calls["emit_incident"] == emits_after_first == 1
    assert client.calls["set_tags"] == settags_after_first == 1
    # Exactly one incident and one document exist — no duplicates.
    assert len(client.incidents) == 1
    assert len(client.documents) == 1
    statuses = {(r.action, r.status) for r in second.results}
    assert (WriteAction.INCIDENT, WriteStatus.EXISTS) in statuses
    assert (WriteAction.TAG, WriteStatus.EXISTS) in statuses
    assert (WriteAction.DOCUMENT, WriteStatus.UPDATED) in statuses  # doc refreshed in place


def test_incident_urn_is_deterministic_per_pr_and_model():
    urn = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model_v3,PROD)"
    assert incident_urn_for(PR, urn) == incident_urn_for(PR, urn)
    other = PRContext(repo="order-entry/analytics", number=43)
    assert incident_urn_for(PR, urn) != incident_urn_for(other, urn)


# --------------------------------------------------------------------------- #
# Scope + degradation
# --------------------------------------------------------------------------- #
def test_only_critical_and_high_are_written():
    client = FakeClient()
    scored = [
        make_scored("churn_model_v3", Severity.CRITICAL, trained=True, deployed=True),
        make_scored("reactivation_model_v1", Severity.HIGH, deployed=True),
        make_scored("churn_model_v2", Severity.MEDIUM, trained=True),
        make_scored("some_dataset", Severity.LOW),
    ]
    summary = write_back(scored, CHANGE, PR, "REPORT", client=client, dry_run=False, env=ENABLED)
    targeted = {r.target for r in summary.results if r.action is WriteAction.INCIDENT}
    assert targeted == {"churn_model_v3", "reactivation_model_v1"}
    assert len(client.incidents) == 2  # medium + low skipped


def test_failed_write_degrades_and_returns():
    client = FakeClient(fail_on="incident")
    scored = [make_scored("churn_model_v3", Severity.CRITICAL, trained=True, deployed=True)]
    # Must NOT raise — the comment must still post.
    summary = write_back(scored, CHANGE, PR, "REPORT", client=client, dry_run=False, env=ENABLED)
    incident = next(r for r in summary.results if r.action is WriteAction.INCIDENT)
    assert incident.status is WriteStatus.FAILED
    assert not summary.ok
    # The tag and document writes still happened despite the incident failure.
    assert any(r.action is WriteAction.TAG and r.status is WriteStatus.CREATED
               for r in summary.results)
    assert any(r.action is WriteAction.DOCUMENT and r.status is WriteStatus.CREATED
               for r in summary.results)


def test_no_targets_gives_empty_summary():
    client = FakeClient()
    scored = [make_scored("churn_model_v2", Severity.MEDIUM, trained=True)]
    summary = write_back(scored, CHANGE, PR, "REPORT", client=client, dry_run=False, env=ENABLED)
    assert summary.results == ()
    assert "no critical or high" in summary.note
    assert not client.incidents


# --------------------------------------------------------------------------- #
# Footer rendering (what the PR comment shows)
# --------------------------------------------------------------------------- #
def test_footer_disabled_names_the_env_var():
    client = FakeClient()
    scored = [make_scored("churn_model_v3", Severity.CRITICAL, trained=True, deployed=True)]
    summary = write_back(scored, CHANGE, PR, "REPORT", client=client, dry_run=False, env={})
    footer = summary.footer_markdown()
    assert MUTATION_ENV in footer
    assert "Write-back to DataHub" in footer


def test_footer_live_lists_writes():
    client = FakeClient()
    scored = [make_scored("churn_model_v3", Severity.CRITICAL, trained=True, deployed=True)]
    summary = write_back(scored, CHANGE, PR, "REPORT", client=client, dry_run=False, env=ENABLED)
    footer = summary.footer_markdown()
    assert "incident" in footer and "tag" in footer and "document" in footer
    assert "churn_model_v3" in footer


@pytest.mark.parametrize("column", ["customer_since"])
def test_document_links_impacted_models(column):
    client = FakeClient()
    scored = [
        make_scored("churn_model_v3", Severity.CRITICAL, trained=True, deployed=True),
        make_scored("reactivation_model_v1", Severity.HIGH, deployed=True),
    ]
    write_back(scored, CHANGE, PR, "REPORT", client=client, dry_run=False, env=ENABLED)
    doc = next(iter(client.documents.values()))
    assert any("churn_model_v3" in a for a in doc["related"])
    assert any("reactivation_model_v1" in a for a in doc["related"])
    assert DS in doc["related"]  # the changed dataset is linked too
