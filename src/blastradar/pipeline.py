"""The Blastradar analysis pipeline, factored out of the CLI.

One code path drives every entry point so the offline demo, the fixture recorder,
the test suite, and the live CLI cannot drift apart (architectural rule 3 — the
fixtures double as the tests). Split in two so each caller takes only what it needs:

  * :func:`run_analysis` — diff-delta → resolve → walk → the read-heavy core. This
    is where *every* DataHub read happens, so recording an observed client through
    exactly this function captures exactly what the demo replays.
  * :func:`finalize` — score → narrate once → render → write-back footer. Pure
    assembly on top of the analyses; the single LLM call lives here (rule 1).

``cli.py`` is now a thin wrapper: extract input, connect, ``run_analysis``,
``finalize``, post the comment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from blastradar.datahub.client import DataHubClient, DataHubClientError
from blastradar.datahub.resolver import DataHubSchemaProvider, Resolver
from blastradar.datahub.walker import walk
from blastradar.datahub.writeback import (
    WritebackSummary,
    mutations_enabled,
    write_back,
)
from blastradar.diff.sql_delta import SqlDeltaError, analyze_delta
from blastradar.models import (
    ChangeEvent,
    ChangeKind,
    ImpactGraph,
    PRContext,
    ResolutionStatus,
    ResolvedColumn,
    ScoredImpact,
    SqlFileChange,
)
from blastradar.narrate import Narration, narrate
from blastradar.report import DEFAULT_FOOTER, Analysis, RenderedReport, render_report
from blastradar.scoring import _sort_key, score_graph

logger = logging.getLogger(__name__)

COLUMN_CHANGE_KINDS = frozenset({
    ChangeKind.DROP_COLUMN, ChangeKind.RENAME_COLUMN, ChangeKind.TYPE_CHANGE,
})


@dataclass
class PipelineResult:
    """Everything :func:`run_analysis` produced: the per-column analyses + gaps."""

    analyses: list[Analysis] = field(default_factory=list)
    extra_issues: list[str] = field(default_factory=list)
    representative: ChangeEvent | None = None

    @property
    def has_output(self) -> bool:
        """True if there is anything to report (impacts or analysis gaps)."""
        return bool(self.analyses or self.extra_issues)


@dataclass
class FinalReport:
    """The rendered comment (with write-back footer) + its machine-readable twin."""

    markdown: str
    data: dict
    writeback: WritebackSummary | None
    narration: Narration


def _unreachable_graph(change: ChangeEvent, note: str) -> ImpactGraph:
    """A stand-in graph so a DataHub failure surfaces as 'incomplete', not 'all-clear'."""
    return ImpactGraph(
        change=change,
        resolution=ResolvedColumn(table=change.table, column=change.column,
                                  status=ResolutionStatus.UNRESOLVED, note=note),
        notes=(note,),
    )


def run_analysis(
    changes: list[SqlFileChange],
    *,
    client: DataHubClient | None,
    resolver: Resolver | None,
    schema: DataHubSchemaProvider | None,
    dialect: str = "snowflake",
    max_hops: int = 6,
    connect_note: str = "",
) -> PipelineResult:
    """Diff-delta every changed file, then walk each column change to ML terminals.

    ``client``/``resolver`` may be ``None`` (DataHub unreachable) — every column then
    becomes an 'incomplete' analysis carrying ``connect_note``, never a false
    all-clear. This is the only function that reads from DataHub, so recording an
    observed client across it captures the whole demo's fixtures.
    """
    result = PipelineResult()

    # 1. SQL delta -> ChangeEvents (external SELECT * expands via live schema when connected).
    events: list[ChangeEvent] = []
    for fc in changes:
        try:
            delta = analyze_delta(fc, dialect=dialect, schema=schema)
        except SqlDeltaError as e:
            result.extra_issues.append(f"could not parse `{fc.path}`: {e}")
            continue
        events.extend(delta.changes)
        for marker in delta.unresolved:
            result.extra_issues.append(
                f"`{marker.table}` has an unresolved `SELECT *` from "
                f"{', '.join(marker.star_sources)} — impact for it was not analyzed.")

    # 2. Walk each column change downstream to ML.
    for ev in events:
        if ev.kind is ChangeKind.DROP_TABLE:
            result.extra_issues.append(
                f"`{ev.table}` is dropped entirely — table-level impact "
                "is not analyzed in this phase.")
            continue
        if ev.kind not in COLUMN_CHANGE_KINDS or ev.column is None:
            continue
        if client is None or resolver is None:
            result.analyses.append(Analysis(ev, _unreachable_graph(ev, connect_note)))
            continue
        try:
            graph = walk(ev, client=client, resolver=resolver, max_hops=max_hops)
        except DataHubClientError as e:
            graph = _unreachable_graph(ev, f"DataHub error during walk ({e})")
        result.analyses.append(Analysis(ev, graph))

    result.representative = (
        result.analyses[0].change if result.analyses else (events[0] if events else None)
    )
    return result


def score(result: PipelineResult) -> list[ScoredImpact]:
    """Deterministically score + sort every impacted model across all analyses."""
    scored = [s for a in result.analyses for s in score_graph(a.graph)]
    scored.sort(key=_sort_key)
    return scored


def finalize(
    result: PipelineResult,
    *,
    pr: PRContext,
    use_llm: bool,
    client: DataHubClient | None,
    do_writeback: bool = True,
    dry_run: bool = False,
) -> FinalReport:
    """Score, narrate once, render, run write-back, and assemble the final comment.

    ``use_llm`` gates the single LLM narration call (rule 1); with it off (or on any
    API failure) the templated fallback is used, so the tool works with no API key.
    Write-back is idempotent and gated by ``TOOLS_IS_MUTATION_ENABLED`` inside
    ``write_back``; ``dry_run`` / a disabled gate plan without touching ``client``.
    """
    scored = score(result)
    rep = result.representative
    narration = (
        narrate(rep, scored, use_llm=use_llm) if rep is not None
        else Narration(change_summary="")
    )
    base = render_report(result.analyses, scored, narration,
                         extra_issues=tuple(result.extra_issues), writeback_footer="")

    summary = _run_writeback(do_writeback, scored, rep, pr, base.markdown, client, dry_run)
    footer = summary.footer_markdown() if summary is not None else DEFAULT_FOOTER
    final_markdown = base.markdown.rstrip() + "\n\n" + footer

    data = dict(base.data)
    if summary is not None:
        data["writeback"] = summary.as_dict()
    return FinalReport(markdown=final_markdown, data=data,
                       writeback=summary, narration=narration)


def _run_writeback(do_writeback, scored, representative, pr, body_markdown, client, dry_run):
    """Run write-back if requested, tolerating an unreachable DataHub."""
    if not do_writeback or representative is None:
        return None
    # dry-run and 'mutations disabled' only PLAN — they never touch the client, so they
    # work offline. A live write needs a connection.
    if client is None and mutations_enabled() and not dry_run:
        return WritebackSummary(
            results=(), mutation_enabled=True, dry_run=False,
            note="DataHub unreachable — write-back skipped; the PR comment still posts")
    return write_back(scored, representative, pr, body_markdown, client=client, dry_run=dry_run)


def empty_message(result: PipelineResult, changes: list[SqlFileChange]) -> str | None:
    """The terminal message for a run that produced nothing to report, or None."""
    if result.has_output:
        return None
    if not changes:
        return "No changed .sql files in the input — nothing to analyze."
    return "Detected SQL changes, but none affect a resolvable output column."
