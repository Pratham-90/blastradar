"""End-to-end pipeline tests on the recorded fixtures — the three demo shapes.

These replay each demo/example PR through the real ``pipeline`` and assert the
severity shape, then assert the committed ``examples/*.md`` still match what the
pipeline generates (so the examples cannot silently rot). All offline.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

from blastradar.datahub.client import DataHubClient
from blastradar.datahub.resolver import DataHubSchemaProvider, Resolver
from blastradar.diff.extract import extract_from_json
from blastradar.models import ResolutionStatus, Severity
from blastradar.pipeline import run_analysis, score

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import demo  # noqa: E402  — reuse the exact demo logic to guard the examples


def _analyze(changes_path: Path):
    client = DataHubClient.from_env()  # ReplayClient via conftest's BLASTRADAR_REPLAY
    client.test_connection()
    resolver = Resolver(client)
    schema = DataHubSchemaProvider(resolver, client)
    with changes_path.open(encoding="utf-8") as fh:
        changes = extract_from_json(fh)
    return run_analysis(changes, client=client, resolver=resolver, schema=schema)


def test_critical_scenario_shape() -> None:
    # churn_model_v3       CRITICAL — deployed + trained on the column (tag Tier1, capped)
    # reactivation_model_v1 CRITICAL — deployed inference-only, escalated (owned + serving)
    # churn_model_v1        MEDIUM  — trained but NOT deployed; ownership alone no longer
    #                                 escalates a shelved model
    # churn_model_v2        MEDIUM  — not deployed, unowned
    # ltv_model_v1          MEDIUM  — not deployed, unowned
    result = _analyze(REPO / "demo-repo" / "demo-pr.json")
    counts = Counter(s.severity for s in score(result))
    assert counts[Severity.CRITICAL] == 2
    assert counts[Severity.HIGH] == 0
    assert counts[Severity.MEDIUM] == 3


def test_medium_scenario_is_single_non_deployed() -> None:
    result = _analyze(REPO / "demo-repo" / "medium-pr.json")
    scored = score(result)
    assert len(scored) == 1
    assert scored[0].severity is Severity.MEDIUM
    assert scored[0].deployed is False
    assert scored[0].asset.name == "ltv_model_v1"


def test_clean_scenario_no_impact_but_resolved() -> None:
    result = _analyze(REPO / "demo-repo" / "clean-pr.json")
    assert score(result) == []
    # Resolved to a real dataset — a genuine all-clear, not an analysis failure.
    assert all(a.graph.resolution.status is ResolutionStatus.RESOLVED
               for a in result.analyses)
    assert not result.extra_issues


@pytest.mark.parametrize("key", ["critical", "medium", "clean"])
def test_examples_do_not_rot(key: str) -> None:
    scenario = demo.SCENARIOS[key]
    committed = (REPO / "examples" / f"{scenario.out_stem}.md").read_text()
    regenerated = demo._run(scenario, write=False, quiet=True).rstrip() + "\n"
    assert regenerated == committed, (
        f"examples/{scenario.out_stem}.md is stale — regenerate with `make examples`")
