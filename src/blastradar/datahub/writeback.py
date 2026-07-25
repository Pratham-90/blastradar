"""Write Blastradar findings back into DataHub Core.

For every CRITICAL or HIGH impacted model this module, per the Phase 1D spec:

  a) opens an **incident** describing the blast radius and linking back to the PR;
  b) adds a **tag** (``pending-upstream-change``) to the model;
  c) saves one **document** to DataHub's knowledge base holding the full report.

DataHub Core only (architectural rule 2): incidents, tags, documents — no
assertions/contracts/health-dashboard. Read docs/API-NOTES.md before touching this.

Four properties the spec demands, and how they are met here:

* **Mutations are OFF by default.** Nothing writes unless ``TOOLS_IS_MUTATION_ENABLED``
  is exactly ``true``. This is the single most likely setup failure — an operator
  runs the tool, sees no incidents, and assumes it is broken. So when the gate is off
  every planned write is reported as ``DISABLED`` with a message naming the variable,
  and a loud warning is logged. See :func:`mutations_enabled`.
* **Idempotent.** Re-running on the same PR must not duplicate anything. Incidents use
  a URN derived deterministically from ``(pr, model)`` and are checked with an
  immediately-consistent aspect read before writing; tags are a set-union; the document
  uses a deterministic id and upserts in place.
* **Every write is logged and collected** into a :class:`WritebackSummary` the report
  footer renders (:meth:`WritebackSummary.footer_markdown`).
* **Degrade, don't abort.** A failing write is caught, recorded as ``FAILED``, and the
  run continues so the PR comment still posts.

Live constraint (GMS v1.5.0.6, verified): ``raiseIncident`` / raw incident aspects
**reject mlModel URNs** as a destination (``/entities/* not a valid destination``), so
the incident is anchored on the **changed dataset** — the entity that actually changed —
with the affected model named in the title/description. The document (whose
``related_assets`` accept mlModel URNs) links every impacted model directly.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from enum import Enum

from blastradar.datahub.urns import dataset_of_schema_field, short_name, simple_name
from blastradar.models import ChangeEvent, PRContext, ScoredImpact, Severity

logger = logging.getLogger(__name__)

# The mutation kill-switch. Writes require this to be exactly "true" (any case).
MUTATION_ENV = "TOOLS_IS_MUTATION_ENABLED"

# Severities we act on. Medium/low are reported in the PR comment but not written back.
WRITEBACK_SEVERITIES = frozenset({Severity.CRITICAL, Severity.HIGH})

PENDING_TAG = "pending-upstream-change"
DOCUMENT_SUBTYPE = "blastradar-finding"

# DataHub numeric incident priority (lower = more urgent): 0 CRITICAL … 3 LOW.
_INCIDENT_PRIORITY = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2}


def mutations_enabled(env: dict[str, str] | None = None) -> bool:
    """True iff ``TOOLS_IS_MUTATION_ENABLED`` is set to ``true`` (case-insensitive)."""
    source = env if env is not None else os.environ
    return source.get(MUTATION_ENV, "").strip().lower() == "true"


# --------------------------------------------------------------------------- #
# Result types (the report footer renders these)
# --------------------------------------------------------------------------- #
class WriteAction(str, Enum):
    INCIDENT = "incident"
    TAG = "tag"
    DOCUMENT = "document"


class WriteStatus(str, Enum):
    CREATED = "created"     # newly written
    UPDATED = "updated"     # already existed, content refreshed in place
    EXISTS = "exists"       # already present and identical — no write performed
    DRY_RUN = "dry-run"     # --dry-run: would write, did not
    DISABLED = "disabled"   # mutation gate off: would write, did not
    FAILED = "failed"       # attempted, errored — recorded, run continued


_STATUS_ICON = {
    WriteStatus.CREATED: "✅", WriteStatus.UPDATED: "✅", WriteStatus.EXISTS: "♻️",
    WriteStatus.DRY_RUN: "🔎", WriteStatus.DISABLED: "🚫", WriteStatus.FAILED: "❌",
}


@dataclass(frozen=True)
class WriteResult:
    """The outcome of one write-back operation, ready to log and to render."""

    action: WriteAction
    target: str                     # human name of the model/dataset the write concerns
    status: WriteStatus
    entity_urn: str | None = None   # URN of the created/updated incident, tag target, or doc
    detail: str = ""

    @property
    def line(self) -> str:
        icon = _STATUS_ICON[self.status]
        base = f"{icon} {self.action.value} · {self.target} · {self.status.value}"
        return f"{base} — {self.detail}" if self.detail else base


@dataclass(frozen=True)
class WritebackSummary:
    """All write results plus the run mode. The report footer renders this."""

    results: tuple[WriteResult, ...]
    mutation_enabled: bool
    dry_run: bool
    note: str = ""

    @property
    def ok(self) -> bool:
        """True if nothing failed (a disabled/dry run with no attempts is still ok)."""
        return not any(r.status is WriteStatus.FAILED for r in self.results)

    @property
    def wrote_anything(self) -> bool:
        return any(r.status in (WriteStatus.CREATED, WriteStatus.UPDATED) for r in self.results)

    def counts(self) -> dict[WriteStatus, int]:
        counts = {s: 0 for s in WriteStatus}
        for r in self.results:
            counts[r.status] += 1
        return counts

    def as_dict(self) -> dict:
        return {
            "mutation_enabled": self.mutation_enabled,
            "dry_run": self.dry_run,
            "ok": self.ok,
            "note": self.note,
            "results": [
                {"action": r.action.value, "target": r.target, "status": r.status.value,
                 "entity_urn": r.entity_urn, "detail": r.detail}
                for r in self.results
            ],
        }

    def footer_markdown(self) -> str:
        """The '📋 Write-back to DataHub' section appended to the PR comment."""
        lines = ["---", "### 📋 Write-back to DataHub"]
        if not self.results:
            lines.append("_No critical or high impacts — nothing written back._")
            return "\n".join(lines)

        if self.dry_run:
            lines.append("_`--dry-run`: the following would be written (no changes made):_")
        elif not self.mutation_enabled:
            lines.append(
                f"> 🚫 **Write-back skipped — mutations are disabled.** Set "
                f"`{MUTATION_ENV}=true` to open incidents, tag models, and save the "
                f"report to DataHub. The following **would** have been written:")
        else:
            failed = self.counts()[WriteStatus.FAILED]
            head = "Wrote findings back to DataHub Core"
            if failed:
                head += f" — ⚠️ {failed} write(s) failed (the comment still posted)"
            lines.append(f"_{head}:_")

        lines.append("")
        lines.append("| | Action | Target | Status | Detail |")
        lines.append("|---|---|---|---|---|")
        for r in self.results:
            icon = _STATUS_ICON[r.status]
            detail = r.detail.replace("|", "\\|") if r.detail else ""
            lines.append(f"| {icon} | {r.action.value} | `{r.target}` | "
                         f"{r.status.value} | {detail} |")
        if self.note:
            lines.append("")
            lines.append(f"_{self.note}_")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Deterministic identifiers (the basis of idempotency)
# --------------------------------------------------------------------------- #
def _hash(text: str, n: int = 16) -> str:
    import hashlib
    return hashlib.sha1(text.encode()).hexdigest()[:n]


def _slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit] or "pr"


def incident_urn_for(pr: PRContext, model_urn: str) -> str:
    """Deterministic incident URN for a (PR, model) pair — re-running hits the same URN."""
    return f"urn:li:incident:blastradar-{_hash(f'{pr.key}|{model_urn}')}"


def document_id_for(pr: PRContext) -> str:
    """Deterministic knowledge-base document id for a PR (one document per PR)."""
    return f"blastradar-{_slug(pr.key)}-{_hash(pr.key, 10)}"


def _pr_marker(pr: PRContext) -> str:
    """Hidden marker embedded in an incident so we can confirm it references this PR."""
    return f"<!-- blastradar:pr={pr.key} -->"


# --------------------------------------------------------------------------- #
# Content builders (title + body "from the impact report")
# --------------------------------------------------------------------------- #
_CHANGE_VERB = {
    "DROP_COLUMN": "dropped", "RENAME_COLUMN": "renamed",
    "TYPE_CHANGE": "retyped", "DROP_TABLE": "dropped (table)",
}


def _change_of(scored: ScoredImpact, fallback: ChangeEvent) -> ChangeEvent:
    return scored.asset.paths[0].change if scored.asset.paths else fallback


def _column_label(change: ChangeEvent) -> str:
    return f"{change.table}.{change.column}"


def _incident_title(scored: ScoredImpact, change: ChangeEvent) -> str:
    verb = _CHANGE_VERB.get(change.kind.value, "changed")
    return (f"ML model at risk ({scored.severity.value}): {scored.asset.name} — "
            f"upstream column {_column_label(change)} {verb}")


def _incident_description(scored: ScoredImpact, change: ChangeEvent, pr: PRContext) -> str:
    verb = _CHANGE_VERB.get(change.kind.value, "changed")
    col = _column_label(change)
    rel = ("was **trained on** this column" if scored.trained_on
           else "reads this column **at inference time**")
    depl = ("currently **deployed** and serving predictions" if scored.deployed
            else "not currently deployed")
    deployments = ", ".join(f"{short_name(d.urn)} ({d.status})"
                            for d in scored.asset.deployments) or "none"
    owners = ", ".join(f"@{simple_name(o)}" for o in scored.asset.owners) or "unowned"
    path = " → ".join([col, *(short_name(h.to_urn) for h in scored.asset.paths[0].hops)]) \
        if scored.asset.paths else col
    return (
        f"Pull request **{pr.key}** {verb} the upstream column `{col}`, which feeds the "
        f"model **{scored.asset.name}**.\n\n"
        f"This change does not raise an error: the feature pipeline silently emits "
        f"nulls/stale values and predictions degrade with no failure surfacing.\n\n"
        f"- **Severity:** {scored.severity.value}\n"
        f"- **Model:** {scored.asset.name} — {rel}; {depl}\n"
        f"- **Deployments:** {deployments}\n"
        f"- **Owners:** {owners}\n"
        f"- **Lineage:** {path}\n"
        f"- **Why this severity:** {scored.rationale}\n"
        f"- **Pull request:** {pr.link}\n\n"
        f"Raised automatically by Blastradar.\n{_pr_marker(pr)}"
    )


def _document_title(change: ChangeEvent, pr: PRContext) -> str:
    return f"Blast radius: {_column_label(change)} {_CHANGE_VERB.get(change.kind.value, 'changed')} ({pr.key})"


# --------------------------------------------------------------------------- #
# The write-back orchestration
# --------------------------------------------------------------------------- #
def _dataset_urn_for(scored: ScoredImpact) -> str | None:
    """The changed dataset URN this impact traces from (incident anchor)."""
    if not scored.asset.paths:
        return None
    return dataset_of_schema_field(scored.asset.paths[0].source_urn)


def _plan_targets(scored: list[ScoredImpact], change: ChangeEvent) -> list[tuple[ScoredImpact, ChangeEvent]]:
    """The (impact, its change) pairs we act on: critical + high, in the given order."""
    return [(s, _change_of(s, change)) for s in scored if s.severity in WRITEBACK_SEVERITIES]


def write_back(
    scored: list[ScoredImpact],
    change: ChangeEvent,
    pr: PRContext,
    report_markdown: str,
    *,
    client,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
) -> WritebackSummary:
    """Write incidents, tags, and one document for the critical/high impacts.

    ``client`` is a :class:`~blastradar.datahub.client.DataHubClient` (or any object
    with the same ``get_incident``/``emit_incident``/``get_tags``/``set_tags``/
    ``get_document``/``upsert_document`` methods — tests pass a fake). ``change`` is the
    representative change, used only as a fallback label. Never raises: any write error
    becomes a ``FAILED`` result so the caller can still post the PR comment.
    """
    targets = _plan_targets(scored, change)
    enabled = mutations_enabled(env)

    if not targets:
        return WritebackSummary(results=(), mutation_enabled=enabled, dry_run=dry_run,
                                note="no critical or high impacts")

    # Read-only modes: plan every write without touching the client.
    if dry_run or not enabled:
        planned = WriteStatus.DRY_RUN if dry_run else WriteStatus.DISABLED
        results: list[WriteResult] = []
        for s, ch in targets:
            results.append(WriteResult(WriteAction.INCIDENT, s.asset.name, planned,
                                       entity_urn=incident_urn_for(pr, s.asset.urn),
                                       detail="anchored on the changed dataset"))
            results.append(WriteResult(WriteAction.TAG, s.asset.name, planned,
                                       detail=f"tag `{PENDING_TAG}`"))
        results.append(WriteResult(WriteAction.DOCUMENT, "knowledge base", planned,
                                   entity_urn=f"urn:li:document:{document_id_for(pr)}",
                                   detail="full impact report"))
        note = (f"set {MUTATION_ENV}=true to apply" if not enabled and not dry_run else "")
        if not enabled and not dry_run:
            logger.warning("Write-back SKIPPED: %s is not 'true'. %d incident(s)/tag(s) "
                           "and 1 document were NOT written.", MUTATION_ENV, len(targets))
        return WritebackSummary(results=tuple(results), mutation_enabled=enabled,
                                dry_run=dry_run, note=note)

    # Live write path.
    results = []
    impacted_model_urns: list[str] = []
    related_dataset_urns: list[str] = []
    for s, ch in targets:
        impacted_model_urns.append(s.asset.urn)
        ds = _dataset_urn_for(s)
        if ds and ds not in related_dataset_urns:
            related_dataset_urns.append(ds)
        results.append(_write_incident(client, s, ch, pr))
        results.append(_write_tag(client, s))
    results.append(_write_document(
        client, targets, change, pr, report_markdown,
        related=impacted_model_urns + related_dataset_urns))

    for r in results:
        logger.info("write-back: %s", r.line)
    return WritebackSummary(results=tuple(results), mutation_enabled=True, dry_run=False)


def _write_incident(client, scored: ScoredImpact, change: ChangeEvent, pr: PRContext) -> WriteResult:
    """Open (idempotently) an incident for one impacted model. Never raises."""
    name = scored.asset.name
    inc_urn = incident_urn_for(pr, scored.asset.urn)
    ds = _dataset_urn_for(scored)
    try:
        if ds is None:
            return WriteResult(WriteAction.INCIDENT, name, WriteStatus.FAILED,
                               detail="no source dataset on the impact path")
        # Idempotency: an existing active incident referencing THIS PR → do not re-raise.
        existing = client.get_incident(inc_urn)
        if (existing and (existing.get("state") or "").upper().endswith("ACTIVE")
                and _pr_marker(pr) in (existing.get("description") or "")):
            return WriteResult(WriteAction.INCIDENT, name, WriteStatus.EXISTS,
                               entity_urn=inc_urn,
                               detail=f"already open for {pr.key}")
        client.emit_incident(
            inc_urn, entity_urns=[ds],
            title=_incident_title(scored, change),
            description=_incident_description(scored, change, pr),
            incident_type="DATA_SCHEMA",
            priority=_INCIDENT_PRIORITY.get(scored.severity, 2),
        )
        status = WriteStatus.UPDATED if existing else WriteStatus.CREATED
        return WriteResult(WriteAction.INCIDENT, name, status, entity_urn=inc_urn,
                           detail=f"on {short_name(ds)}")
    except Exception as e:  # noqa: BLE001 — degrade, don't abort (spec: comment must still post)
        logger.warning("incident write failed for %s: %s: %s", name, type(e).__name__, e)
        return WriteResult(WriteAction.INCIDENT, name, WriteStatus.FAILED,
                           entity_urn=inc_urn, detail=f"{type(e).__name__}: {e}")


def _write_tag(client, scored: ScoredImpact) -> WriteResult:
    """Add the pending-upstream-change tag to the model (set-union). Never raises."""
    from datahub.emitter.mce_builder import make_tag_urn
    name = scored.asset.urn
    tag_urn = make_tag_urn(PENDING_TAG)
    try:
        current = list(client.get_tags(scored.asset.urn))
        if tag_urn in current:
            return WriteResult(WriteAction.TAG, scored.asset.name, WriteStatus.EXISTS,
                               entity_urn=scored.asset.urn, detail=f"`{PENDING_TAG}` present")
        merged = list(dict.fromkeys(current + [tag_urn]))  # union, order-stable
        client.set_tags(scored.asset.urn, merged)
        kept = ", ".join(simple_name(t) for t in current) or "none"
        return WriteResult(WriteAction.TAG, scored.asset.name, WriteStatus.CREATED,
                           entity_urn=scored.asset.urn,
                           detail=f"added `{PENDING_TAG}` (kept: {kept})")
    except Exception as e:  # noqa: BLE001 — degrade, don't abort
        logger.warning("tag write failed for %s: %s: %s", name, type(e).__name__, e)
        return WriteResult(WriteAction.TAG, scored.asset.name, WriteStatus.FAILED,
                           entity_urn=scored.asset.urn, detail=f"{type(e).__name__}: {e}")


def _write_document(client, targets, change: ChangeEvent, pr: PRContext,
                    report_markdown: str, *, related: list[str]) -> WriteResult:
    """Save one knowledge-base document holding the full report. Idempotent. Never raises."""
    doc_id = document_id_for(pr)
    doc_urn = f"urn:li:document:{doc_id}"
    rep_change = targets[0][1] if targets else change
    try:
        existed = client.get_document(doc_urn) is not None
        header = (f"# Blast radius report — {pr.key}\n\n"
                  f"Upstream change to `{_column_label(rep_change)}`. "
                  f"Pull request: {pr.link}\n\n---\n\n")
        client.upsert_document(
            doc_id=doc_id, title=_document_title(rep_change, pr),
            text=header + report_markdown, subtype=DOCUMENT_SUBTYPE,
            related_assets=list(dict.fromkeys(related)),
            custom_properties={"blastradar.pr": pr.key, "blastradar.sha": pr.sha,
                               "blastradar.impacted_models": str(len(targets))},
        )
        status = WriteStatus.UPDATED if existed else WriteStatus.CREATED
        return WriteResult(WriteAction.DOCUMENT, "knowledge base", status,
                           entity_urn=doc_urn,
                           detail=f"{len(targets)} model(s) linked")
    except Exception as e:  # noqa: BLE001 — degrade, don't abort
        logger.warning("document write failed: %s: %s", type(e).__name__, e)
        return WriteResult(WriteAction.DOCUMENT, "knowledge base", WriteStatus.FAILED,
                           entity_urn=doc_urn, detail=f"{type(e).__name__}: {e}")


__all__ = [
    "MUTATION_ENV",
    "mutations_enabled",
    "WriteAction",
    "WriteStatus",
    "WriteResult",
    "WritebackSummary",
    "write_back",
    "incident_urn_for",
    "document_id_for",
    "PENDING_TAG",
]
