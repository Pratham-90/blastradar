"""Render the final PR comment (markdown) and a machine-readable JSON alongside it.

The markdown structure is fully deterministic: it iterates the pre-sorted, pre-scored
impact list and slots in the narrator's prose by asset id. The LLM cannot change the
set or order of impacts here (architectural rule 1).

Guard (Phase 1C spec): NEVER emit a comment claiming zero impact when the walk was
truncated or a column failed to resolve — say so explicitly. A false all-clear is the
worst possible output for this tool.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from blastradar.datahub.urns import short_name, simple_name
from blastradar.models import (
    ChangeEvent,
    ImpactGraph,
    ResolutionStatus,
    ScoredImpact,
    Severity,
)
from blastradar.narrate import Narration, asset_id
from blastradar.scoring import score_graph, severity_counts

logger = logging.getLogger(__name__)

SEVERITY_EMOJI = {
    Severity.CRITICAL: "🔴", Severity.HIGH: "🟠",
    Severity.MEDIUM: "🟡", Severity.LOW: "⚪",
}
_ORDER = (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW)

DEFAULT_FOOTER = (
    "---\n"
    "📋 _Write-back to DataHub (incident · tag · saved document) is available — run "
    "with write-back enabled to record this finding._"
)


@dataclass(frozen=True)
class Analysis:
    """One changed column and the impact graph the walker produced for it."""

    change: ChangeEvent
    graph: ImpactGraph


@dataclass(frozen=True)
class RenderedReport:
    """The PR comment and its machine-readable twin."""

    markdown: str
    data: dict

    def json(self, *, indent: int = 2) -> str:
        return json.dumps(self.data, indent=indent)


def _readable_path(scored: ScoredImpact) -> list[str]:
    change = scored.asset.paths[0].change if scored.asset.paths else None
    start = f"{change.table}.{change.column}" if change else short_name(scored.asset.urn)
    names = [start]
    if scored.asset.paths:
        names.extend(short_name(h.to_urn) for h in scored.asset.paths[0].hops)
    return names


def _owner_label(scored: ScoredImpact) -> str:
    owners = [simple_name(o) for o in scored.asset.owners]
    tags = [simple_name(t) for t in scored.asset.tags]
    parts = []
    parts.append("owner: " + ", ".join(f"@{o}" for o in owners) if owners else "unowned")
    if tags:
        parts.append("tags: " + ", ".join(tags))
    return " · ".join(parts)


def _counts_phrase(counts: dict[Severity, int]) -> str:
    present = [f"{counts[s]} {s.value.lower()}" for s in _ORDER if counts[s]]
    return ", ".join(present) if present else "no impact"


def _issues(analyses: list[Analysis]) -> tuple[bool, list[str]]:
    """(any_problem, human messages) — truncation or unresolved columns."""
    msgs: list[str] = []
    for a in analyses:
        r = a.graph.resolution
        if r.status is ResolutionStatus.AMBIGUOUS:
            msgs.append(f"`{a.change.table}.{a.change.column}` is AMBIGUOUS "
                        f"({len(r.candidates)} candidate datasets) — not analyzed.")
        elif r.status is ResolutionStatus.UNRESOLVED:
            msgs.append(f"`{a.change.table}.{a.change.column}` could not be resolved "
                        f"to a DataHub dataset — not analyzed.")
        if a.graph.truncated:
            msgs.append(f"traversal for `{a.change.table}.{a.change.column}` was "
                        f"TRUNCATED ({a.graph.truncation_reason}) — results may be incomplete.")
    return (bool(msgs), msgs)


def _impact_block(scored: ScoredImpact, narration: Narration, aid: str) -> str:
    a = scored.asset
    emoji = SEVERITY_EMOJI[scored.severity]
    lines = [f"**{emoji} {scored.severity.value.lower()} — `{a.name}`** ({_owner_label(scored)})"]

    depl = (", ".join(f"{short_name(d.urn)} ({d.status})" for d in a.deployments)
            if a.deployments else "not deployed")
    trained = "trained on the changed column" if scored.trained_on else "reads it at inference only"
    lines.append(f"- Deployment: {depl}  ·  Training: {trained}")
    lines.append("- Path: " + " → ".join(f"`{n}`" for n in _readable_path(scored)))

    prose = narration.explanations.get(aid)
    if prose:
        lines.append("")
        lines.append(prose)
    lines.append(f"- _Why this severity: {scored.rationale}_")
    return "\n".join(lines)


def render_report(
    analyses: list[Analysis],
    scored: list[ScoredImpact],
    narration: Narration,
    *,
    extra_issues: tuple[str, ...] = (),
    writeback_footer: str | None = None,
) -> RenderedReport:
    """Render the PR comment + JSON from the scored impacts and narration.

    ``extra_issues`` are analysis gaps the caller knows about but that aren't in the
    graphs (e.g. an unexpanded ``SELECT *``, a DROP_TABLE not yet walked). They feed
    the same no-false-all-clear guard.

    ``writeback_footer`` is the '📋 Write-back to DataHub' section (produced by
    ``writeback.WritebackSummary.footer_markdown()``); when omitted, a short default
    note is shown instead.
    """
    footer = writeback_footer if writeback_footer is not None else DEFAULT_FOOTER
    counts = severity_counts(scored)
    _, graph_issues = _issues(analyses)
    issue_msgs = list(extra_issues) + graph_issues
    has_issues = bool(issue_msgs)
    changes = [a.change for a in analyses]

    md: list[str] = []

    if not scored:
        # Guard: distinguish a genuine all-clear from an incomplete analysis.
        if has_issues:
            md.append("### ⚠️ Blastradar could not complete the ML impact analysis")
            md.append("")
            md.append("The changed column(s) were **not** cleared of downstream ML impact — "
                      "the analysis was incomplete:")
            md.extend(f"- {m}" for m in issue_msgs)
            md.append("")
            md.append("Do not treat this as a clean bill of health. Resolve the issues above "
                      "and re-run before merging.")
        else:
            cols = ", ".join(f"`{c.table}.{c.column}`" for c in changes) or "the changed columns"
            md.append("### ✅ No downstream ML impact detected")
            md.append("")
            md.append(f"Blastradar traced {cols} downstream and found no ML features, models, "
                      "or deployments that depend on them.")
        md.append("")
        md.append(footer)
        return RenderedReport(markdown="\n".join(md), data=_build_data(
            analyses, scored, narration, counts, issue_msgs))

    md.append(f"### ⚠️ ML blast radius: {_counts_phrase(counts)}")
    md.append("")
    md.append(narration.change_summary)
    if has_issues:
        md.append("")
        md.append("> ⚠️ **Partial analysis — results may be incomplete:**")
        md.extend(f"> - {m}" for m in issue_msgs)
    md.append("")

    for i, s in enumerate(scored):
        md.append(_impact_block(s, narration, asset_id(i)))
        md.append("")

    if narration.migration:
        md.append("### Suggested migration")
        md.append("")
        md.append(narration.migration)
        md.append("")

    md.append(footer)
    return RenderedReport(markdown="\n".join(md),
                          data=_build_data(analyses, scored, narration, counts, issue_msgs))


def _build_data(
    analyses: list[Analysis], scored: list[ScoredImpact], narration: Narration,
    counts: dict[Severity, int], issue_msgs: list[str],
) -> dict:
    return {
        "changes": [
            {"kind": a.change.kind.value, "table": a.change.table,
             "column": a.change.column, "new_column": a.change.new_column,
             "source_file": a.change.source_file,
             "resolution": a.graph.resolution.status.value,
             "truncated": a.graph.truncated}
            for a in analyses
        ],
        "summary": {s.value.lower(): counts[s] for s in _ORDER},
        "analysis_incomplete": bool(issue_msgs),
        "issues": issue_msgs,
        "narration_source": narration.model if narration.used_llm else "template",
        "narration_note": narration.note,
        "change_summary": narration.change_summary,
        "migration": narration.migration,
        "impacts": [
            {
                "id": asset_id(i),
                "model": s.asset.name,
                "urn": s.asset.urn,
                "severity": s.severity.value,
                "deployed": s.deployed,
                "trained_on": s.trained_on,
                "deployments": [{"name": short_name(d.urn), "status": d.status}
                                for d in s.asset.deployments],
                "owners": [simple_name(o) for o in s.asset.owners],
                "tags": [simple_name(t) for t in s.asset.tags],
                "model_group": short_name(s.asset.model_group) if s.asset.model_group else None,
                "path": _readable_path(s),
                "reasons": list(s.reasons),
                "explanation": narration.explanations.get(asset_id(i), ""),
            }
            for i, s in enumerate(scored)
        ],
    }


def score_and_render(analyses: list[Analysis], narration_fn) -> RenderedReport:
    """Convenience: score all analyses, call ``narration_fn(change, scored)``, render.

    ``narration_fn`` takes the representative change + combined scored list and returns
    a :class:`Narration` (this is where the single LLM call happens). Kept out of this
    module so ``report`` stays LLM-free.
    """
    scored: list[ScoredImpact] = []
    for a in analyses:
        scored.extend(score_graph(a.graph))
    from blastradar.scoring import _sort_key  # reuse the one deterministic ordering
    scored.sort(key=_sort_key)
    change = analyses[0].change if analyses else None
    narration = narration_fn(change, scored)
    return render_report(analyses, scored, narration)
