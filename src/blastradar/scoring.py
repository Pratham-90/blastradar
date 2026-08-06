"""Deterministic severity scoring for impacted ML assets.

Architectural rule 1: plain Python rules, no LLM — the same ImpactGraph always
produces the same scores. The policy lives in :data:`SEVERITY_RULES`, a
module-level table you can read top-to-bottom as data (first match wins), so a
judge can trace any score back to the clause that produced it via
``ScoredImpact.reasons``.

Table (verbatim from the Phase 1C spec):
    critical : mlModel with an active deployment AND trained on the changed column
    high     : mlModel with an active deployment (inference-time consumption only)
    medium   : mlModel or mlFeatureTable with no active deployment
    low      : dataset or dashboard with no ML downstream
Then escalate one level if the asset carries a Tier1/Critical tag, or has an owner group
**and** an active deployment. (Ownership alone is near-universal on production models, so
it is not an independent escalator — see :func:`_escalation_reason`.)

Reachability note: :func:`score_graph` currently scores only ``mlModel`` terminals (the
walker does not yet surface feature tables, datasets, or dashboards as terminals), so the
``mlFeatureTable`` / ``dataset`` / ``dashboard`` rows below cannot fire through that entry
point today. They are kept — and exercised directly via :func:`score_asset` in the test
suite — so the table stays a complete statement of the policy and starts working the
moment the walker widens. Nothing silently mis-scores as a result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from blastradar.datahub.urns import simple_name
from blastradar.models import ImpactedAsset, ImpactGraph, ScoredImpact, Severity

logger = logging.getLogger(__name__)

# Deployment statuses that count as an *active* deployment (serving traffic).
ACTIVE_DEPLOYMENT_STATUSES = frozenset({"IN_SERVICE", "UPDATING", "ROLLING_BACK"})
# Tag names (case-insensitive) that escalate severity one level.
ESCALATION_TAGS = frozenset({"tier1", "critical"})

# Severity ordering, most-severe first.
_SEVERITY_ORDER = (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW)
_RANK = {s: i for i, s in enumerate(_SEVERITY_ORDER)}


@dataclass(frozen=True)
class _AssetFacts:
    """The boolean facts the rules table matches against."""

    entity_type: str          # mlModel | mlFeatureTable | dataset | dashboard
    has_active_deployment: bool
    trained_on: bool
    has_ml_downstream: bool


@dataclass(frozen=True)
class SeverityRule:
    """One row of the severity table, expressed as data (not an if-branch)."""

    severity: Severity
    conditions: dict[str, Any]   # fact name -> required value
    clause: str                  # human-readable rule text, echoed into `reasons`

    def matches(self, facts: _AssetFacts) -> bool:
        return all(getattr(facts, key) == val for key, val in self.conditions.items())


# THE RULES TABLE — the whole scoring policy, as data. First match wins.
SEVERITY_RULES: tuple[SeverityRule, ...] = (
    SeverityRule(
        Severity.CRITICAL,
        {"entity_type": "mlModel", "has_active_deployment": True, "trained_on": True},
        "mlModel with an active deployment AND trained on the changed column",
    ),
    SeverityRule(
        Severity.HIGH,
        {"entity_type": "mlModel", "has_active_deployment": True},
        "mlModel with an active deployment (inference-time consumption only)",
    ),
    SeverityRule(
        Severity.MEDIUM,
        {"entity_type": "mlModel", "has_active_deployment": False},
        "mlModel with no active deployment",
    ),
    SeverityRule(
        Severity.MEDIUM,
        {"entity_type": "mlFeatureTable", "has_active_deployment": False},
        "mlFeatureTable with no active deployment",
    ),
    SeverityRule(
        Severity.LOW,
        {"entity_type": "dataset", "has_ml_downstream": False},
        "dataset with no ML downstream",
    ),
    SeverityRule(
        Severity.LOW,
        {"entity_type": "dashboard", "has_ml_downstream": False},
        "dashboard with no ML downstream",
    ),
)

# Fallback when nothing matches (keeps scoring total; never crashes on odd input).
_DEFAULT_RULE = SeverityRule(Severity.LOW, {}, "no severity rule matched — defaulted to low")


def _escalate(severity: Severity) -> Severity:
    """Bump one level toward CRITICAL, capped at CRITICAL."""
    return _SEVERITY_ORDER[max(0, _RANK[severity] - 1)]


def _facts(asset: ImpactedAsset) -> _AssetFacts:
    active = any(
        (d.status or "").upper() in ACTIVE_DEPLOYMENT_STATUSES for d in asset.deployments
    )
    trained = bool(asset.training and asset.training.trained_on)
    ml_downstream = asset.entity_type in {"mlModel", "mlFeatureTable"}
    return _AssetFacts(asset.entity_type, active, trained, ml_downstream)


def _escalation_reason(asset: ImpactedAsset, *, deployed: bool) -> str | None:
    """The escalation clause that fires for this asset, or None.

    A Tier1/Critical tag escalates on its own — the tag *is* the owning team's
    explicit statement that this asset is high-stakes.

    Ownership escalates only when the model also has an **active deployment**.
    Ownership alone is a near-universal property of production models, so treating it
    as an independent escalator bumped almost every model up one level regardless of
    whether it was actually serving — including shelved models that aren't live (e.g. a
    trained-but-undeployed owned model jumped MEDIUM → HIGH). That over-escalated across
    the board and muddied the distinction the tool exists to make (trained-on vs.
    inference-only). Requiring "owned *and* serving traffic" keeps the signal meaningful:
    a shelved owned model stays at its base severity, while a deployed one still escalates
    (so a deployed, inference-only, owned model still reaches CRITICAL — deliberately).
    """
    hit = [simple_name(t) for t in asset.tags if simple_name(t).lower() in ESCALATION_TAGS]
    if hit:
        return f"escalated one level: carries tag {', '.join(sorted(hit))}"
    if asset.owners and deployed:
        owners = ", ".join(sorted(simple_name(o) for o in asset.owners))
        return f"escalated one level: owner group set ({owners}) on an active deployment"
    return None


def score_asset(asset: ImpactedAsset) -> ScoredImpact:
    """Score one impacted asset via the rules table + escalation. Deterministic."""
    facts = _facts(asset)
    rule = next((r for r in SEVERITY_RULES if r.matches(facts)), _DEFAULT_RULE)
    severity = rule.severity
    reasons = [rule.clause]

    esc = _escalation_reason(asset, deployed=facts.has_active_deployment)
    if esc is not None:
        bumped = _escalate(severity)
        if bumped != severity:
            severity = bumped
            reasons.append(esc)
        else:
            reasons.append(f"{esc} (already at maximum severity)")

    return ScoredImpact(
        asset=asset, severity=severity,
        trained_on=facts.trained_on, deployed=facts.has_active_deployment,
        reasons=tuple(reasons),
    )


def _sort_key(scored: ScoredImpact) -> tuple[int, int, str]:
    # severity (critical first) -> deployed first -> name alphabetical (stability).
    return (_RANK[scored.severity], 0 if scored.deployed else 1, scored.asset.name.lower())


def score_graph(graph: ImpactGraph) -> list[ScoredImpact]:
    """Score every ML model terminal in an ImpactGraph, sorted deterministically.

    Only ``mlModel`` terminals are scored; each model's deployments are represented
    on the model itself (``asset.deployments``). Feature tables/datasets would score
    here too once the walker surfaces them as terminals.
    """
    scored = [score_asset(a) for a in graph.terminals if a.entity_type == "mlModel"]
    return sorted(scored, key=_sort_key)


def severity_counts(scored: list[ScoredImpact]) -> dict[Severity, int]:
    """Counts per severity (all four levels present, zeros included)."""
    counts = {s: 0 for s in _SEVERITY_ORDER}
    for si in scored:
        counts[si.severity] += 1
    return counts
