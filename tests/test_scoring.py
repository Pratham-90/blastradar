"""Tests for Phase 1C: scoring rules, narration fallback, and the report guard. Pure."""

from __future__ import annotations

from blastradar.models import (
    ChangeEvent,
    ChangeKind,
    DeploymentDetail,
    ImpactedAsset,
    ImpactGraph,
    ResolutionStatus,
    ResolvedColumn,
    Severity,
    TrainingEvidence,
)
from blastradar.narrate import narrate
from blastradar.report import Analysis, render_report
from blastradar.scoring import score_asset, score_graph, severity_counts


def _model(name, *, deployed=False, status="IN_SERVICE", trained=False, owners=(), tags=()):
    deployments = (
        (DeploymentDetail(
            urn=f"urn:li:mlModelDeployment:(urn:li:dataPlatform:sagemaker,{name}-prod,PROD)",
            status=status),)
        if deployed else ()
    )
    return ImpactedAsset(
        urn=f"urn:li:mlModel:(urn:li:dataPlatform:mlflow,{name},PROD)",
        entity_type="mlModel", name=name,
        deployments=deployments, owners=tuple(owners), tags=tuple(tags),
        training=TrainingEvidence(trained_on=trained),
    )


def _tag(name):
    return f"urn:li:tag:{name}"


def _group(name):
    return f"urn:li:corpGroup:{name}"


# --------------------------------------------------------------------------- #
# Rules table
# --------------------------------------------------------------------------- #
def test_critical_deployed_and_trained():
    s = score_asset(_model("m", deployed=True, trained=True))
    assert s.severity is Severity.CRITICAL
    assert any("trained on the changed column" in r for r in s.reasons)


def test_high_deployed_inference_only():
    s = score_asset(_model("m", deployed=True, trained=False))
    assert s.severity is Severity.HIGH
    assert any("inference-time" in r for r in s.reasons)


def test_medium_not_deployed():
    s = score_asset(_model("m", deployed=False, trained=True))
    assert s.severity is Severity.MEDIUM


def test_inactive_deployment_is_not_active():
    # OUT_OF_SERVICE must not count as an active deployment.
    s = score_asset(_model("m", deployed=True, status="OUT_OF_SERVICE", trained=True))
    assert s.severity is Severity.MEDIUM
    assert s.deployed is False


def test_escalation_by_owner_requires_an_active_deployment():
    # Owned AND serving: HIGH base (deployed, inference-only) escalates to CRITICAL.
    s = score_asset(_model("m", deployed=True, trained=False, owners=[_group("analytics-ml")]))
    assert s.severity is Severity.CRITICAL
    assert any("owner group set" in r for r in s.reasons)


def test_owner_alone_does_not_escalate_a_shelved_model():
    # Ownership is near-universal; on a non-deployed model it must NOT escalate.
    s = score_asset(_model("m", trained=True, owners=[_group("analytics-ml")]))
    assert s.severity is Severity.MEDIUM
    assert not any("owner group set" in r for r in s.reasons)


def test_escalation_by_tier1_tag():
    s = score_asset(_model("m", trained=True, tags=[_tag("Tier1")]))
    assert s.severity is Severity.HIGH
    assert any("Tier1" in r for r in s.reasons)


def test_tier2_tag_alone_does_not_escalate():
    s = score_asset(_model("m", trained=True, tags=[_tag("Tier2")]))
    assert s.severity is Severity.MEDIUM  # Tier2 not in the escalation set, no owner


def test_unowned_untagged_does_not_escalate():
    s = score_asset(_model("m", trained=True))
    assert s.severity is Severity.MEDIUM


def test_escalation_capped_at_critical():
    s = score_asset(_model("m", deployed=True, trained=True, owners=[_group("x")]))
    assert s.severity is Severity.CRITICAL
    assert any("already at maximum severity" in r for r in s.reasons)


def test_sort_order_severity_then_deployed_then_name():
    graph = _graph(terminals=(
        _model("zebra", deployed=False, trained=True),                    # MEDIUM
        _model("bravo", deployed=True, trained=True),                     # CRITICAL
        _model("alpha", deployed=True, trained=False),                    # HIGH
        _model("delta", deployed=True, trained=True, owners=[_group("t")]),  # CRITICAL, deployed
    ))
    order = [s.asset.name for s in score_graph(graph)]
    # criticals first (alpha-sorted: bravo, delta), then high (alpha), then medium.
    assert order == ["bravo", "delta", "alpha", "zebra"]


def test_severity_counts():
    graph = _graph(terminals=(
        _model("a", deployed=True, trained=True),
        _model("b", deployed=True, trained=False),
        _model("c", trained=True),
    ))
    counts = severity_counts(score_graph(graph))
    assert counts[Severity.CRITICAL] == 1
    assert counts[Severity.HIGH] == 1
    assert counts[Severity.MEDIUM] == 1


# --------------------------------------------------------------------------- #
# Narration fallback (no LLM)
# --------------------------------------------------------------------------- #
def _change():
    return ChangeEvent(kind=ChangeKind.DROP_COLUMN, table="customers", column="customer_since")


def test_narrate_templated_fallback():
    scored = score_graph(_graph(terminals=(_model("m", deployed=True, trained=True),)))
    n = narrate(_change(), scored, use_llm=False)
    assert n.used_llm is False
    assert n.change_summary
    assert n.migration
    assert set(n.explanations) == {"a1"}


# --------------------------------------------------------------------------- #
# Report guard: never a false all-clear
# --------------------------------------------------------------------------- #
def _graph(*, status=ResolutionStatus.RESOLVED, terminals=(), truncated=False):
    return ImpactGraph(
        change=_change(),
        resolution=ResolvedColumn(table="customers", column="customer_since", status=status,
                                  dataset_urn="urn:li:dataset:(x)", schema_field_urn="urn:li:schemaField:(x)"),
        terminals=tuple(terminals), truncated=truncated,
    )


def test_report_all_clear_when_resolved_and_empty():
    a = [Analysis(_change(), _graph(terminals=()))]
    md = render_report(a, [], narrate(_change(), [], use_llm=False)).markdown
    assert "No downstream ML impact" in md
    assert "could not complete" not in md.lower()


def test_report_not_all_clear_when_unresolved():
    a = [Analysis(_change(), _graph(status=ResolutionStatus.UNRESOLVED, terminals=()))]
    md = render_report(a, [], narrate(_change(), [], use_llm=False)).markdown
    assert "could not complete" in md.lower()
    assert "No downstream ML impact" not in md


def test_report_warns_when_truncated():
    model = _model("m", deployed=True, trained=True)
    graph = _graph(terminals=(model,), truncated=True)
    scored = score_graph(graph)
    md = render_report([Analysis(_change(), graph)], scored,
                       narrate(_change(), scored, use_llm=False)).markdown
    assert "Partial analysis" in md


def test_report_json_has_impacts_and_summary():
    model = _model("m", deployed=True, trained=True)
    graph = _graph(terminals=(model,))
    scored = score_graph(graph)
    report = render_report([Analysis(_change(), graph)], scored,
                           narrate(_change(), scored, use_llm=False))
    assert report.data["summary"]["critical"] == 1
    assert report.data["impacts"][0]["model"] == "m"
    assert report.data["narration_source"] == "template"
