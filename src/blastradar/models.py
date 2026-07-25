"""Domain models shared across the Blastradar pipeline.

All shapes are frozen dataclasses (convention: immutable by default). The flow is:

    SqlFileChange        (diff/extract.py output)
      -> ModelDelta      (diff/sql_delta.py: ChangeEvents + UnresolvedProjection markers)
        -> ImpactPath    (datahub/walker.py: a changed column -> one ML asset)  [Phase 1B]
          -> ScoredImpact (scoring.py: ImpactPath + severity)                    [Phase 1C]

Phase 1A defines all of these; the later shapes (ImpactPath, ScoredImpact) are
deliberately minimal and will be extended by their owning phases.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class ChangeKind(str, Enum):
    """The kind of schema change detected in a SQL model's output projection."""

    DROP_COLUMN = "DROP_COLUMN"
    RENAME_COLUMN = "RENAME_COLUMN"
    TYPE_CHANGE = "TYPE_CHANGE"
    DROP_TABLE = "DROP_TABLE"


class Severity(str, Enum):
    """Impact severity (Phase 1C). Order mirrors PROGRESS.md's trained x deployed matrix."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FileStatus(str, Enum):
    """Git status of a changed file."""

    ADDED = "added"
    DELETED = "deleted"
    MODIFIED = "modified"


class Side(str, Enum):
    """Which version of a file a marker/observation came from."""

    BEFORE = "before"
    AFTER = "after"


# --------------------------------------------------------------------------- #
# Phase 1A: diff extraction + SQL delta
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SqlFileChange:
    """The before/after content of one changed ``.sql`` file.

    Output of ``diff/extract.py``, input to ``diff/sql_delta.py``. ``before`` is
    None for an ADDED file; ``after`` is None for a DELETED file.
    """

    path: str
    status: FileStatus
    before: str | None = None
    after: str | None = None


@dataclass(frozen=True)
class ChangeEvent:
    """One column-level (or table-level) change to a model's output projection.

    ``column`` is the affected output column (the *old* name for a rename);
    ``new_column`` carries the new name for RENAME_COLUMN. ``old_type`` / ``new_type``
    are native type strings, populated when known (an explicit CAST, or a schema
    lookup). ``column`` is None only for DROP_TABLE.
    """

    kind: ChangeKind
    table: str
    column: str | None = None
    new_column: str | None = None
    old_type: str | None = None
    new_type: str | None = None
    source_file: str = ""
    diff_hunk: str = ""


@dataclass(frozen=True)
class UnresolvedProjection:
    """Marker that a model's projection could not be fully resolved from SQL alone.

    Emitted when a ``SELECT *`` (or ``alias.*``) expands from an *external* relation
    whose columns are unknown without schema. ``star_sources`` lists those relations
    as written in the SQL. Phase 1B resolves them via a DataHub-backed
    :class:`SchemaProvider` and re-runs the delta; nothing here is a "no impact"
    signal.
    """

    table: str
    star_sources: tuple[str, ...]
    side: Side
    source_file: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ModelDelta:
    """The delta for a single changed ``.sql`` file: concrete changes + markers.

    A non-empty ``unresolved`` means the projection diff was skipped or is partial
    because of an external ``SELECT *`` — callers MUST NOT read empty ``changes`` as
    "no impact".
    """

    source_file: str
    table: str
    changes: tuple[ChangeEvent, ...] = ()
    unresolved: tuple[UnresolvedProjection, ...] = ()

    @property
    def has_unresolved(self) -> bool:
        """True if any part of this model's projection needs schema expansion."""
        return bool(self.unresolved)


class SchemaProvider(Protocol):
    """Resolves an external relation to its column names.

    Phase 1A passes no provider (external ``SELECT *`` -> UnresolvedProjection).
    Phase 1B supplies a DataHub-backed implementation so the *same* delta code
    expands stars in place. ``relation`` is the table reference as written in the
    SQL (may be schema-qualified, e.g. ``analytics.customers``).
    """

    def get_columns(self, relation: str) -> list[str] | None:
        """Return the relation's column names, or None if unknown."""
        ...


# --------------------------------------------------------------------------- #
# Phase 1B: URN resolution + lineage walk
# --------------------------------------------------------------------------- #
class ResolutionStatus(str, Enum):
    """Outcome of resolving a SQL name to a DataHub URN."""

    RESOLVED = "resolved"      # exactly one best candidate
    AMBIGUOUS = "ambiguous"    # several equally-good candidates — caller must decide
    UNRESOLVED = "unresolved"  # nothing matched


@dataclass(frozen=True)
class DatasetMatch:
    """A candidate dataset for a table name, with enough detail to rank it."""

    urn: str
    platform: str
    name: str            # full dataset name as registered
    exact: bool          # the last name segment equals the query name


@dataclass(frozen=True)
class ResolvedTable:
    """Result of resolving a table name to a dataset URN (never raises; see status)."""

    query: str
    status: ResolutionStatus
    candidates: tuple[DatasetMatch, ...] = ()   # all matches, ranked best-first
    chosen: str | None = None                   # the URN when RESOLVED, else None
    note: str = ""


@dataclass(frozen=True)
class ResolvedColumn:
    """Result of resolving a (table, column) to a schemaField URN."""

    table: str
    column: str | None
    status: ResolutionStatus
    dataset_urn: str | None = None
    schema_field_urn: str | None = None
    candidates: tuple[DatasetMatch, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class PathHop:
    """One edge in a lineage path, with the way it was traversed captured.

    ``transform`` holds the SQL / transform text when DataHub exposes it (often None —
    the ecommerce datapack does not populate ``transformOperation``/``query``).
    """

    from_urn: str
    to_urn: str
    to_type: str            # entity token: dataset | mlFeature | mlModel | mlModelDeployment
    edge_kind: str          # column_lineage | derived_from | consumes | deployed_to
    column: str | None = None
    transform: str | None = None
    hop_index: int = 0


@dataclass(frozen=True)
class ImpactPath:
    """One concrete route from the changed column to a single downstream ML asset."""

    change: ChangeEvent
    source_urn: str                 # schemaField URN of the changed column
    terminal_urn: str
    terminal_type: str
    hops: tuple[PathHop, ...] = ()

    @property
    def urns(self) -> tuple[str, ...]:
        """The URNs along the path, source first."""
        return (self.source_urn, *(h.to_urn for h in self.hops))


@dataclass(frozen=True)
class TrainingEvidence:
    """Whether a model was TRAINED on the changed dataset, with the evidence."""

    trained_on: bool
    training_run_urn: str | None = None
    matched_input_dataset: str | None = None
    input_datasets: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeploymentDetail:
    """A deployment of a model, with its status."""

    urn: str
    status: str | None = None


@dataclass(frozen=True)
class ImpactedAsset:
    """A downstream ML terminal (model or deployment) with every path that reaches it."""

    urn: str
    entity_type: str                # mlModel | mlModelDeployment
    name: str
    paths: tuple[ImpactPath, ...] = ()
    owners: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    model_group: str | None = None
    version: str | None = None
    deployments: tuple[DeploymentDetail, ...] = ()   # for a model terminal
    deployment_status: str | None = None             # for a deployment terminal
    training: TrainingEvidence | None = None         # for a model terminal


@dataclass(frozen=True)
class ImpactGraph:
    """The full downstream ML impact of one :class:`ChangeEvent`.

    ``terminals`` holds the impacted models and deployments, each with its paths.
    ``truncated`` is set only when the frontier ceiling was hit (runaway guard), not
    when a branch simply reached the hop cap (that is recorded in ``notes``).
    """

    change: ChangeEvent
    resolution: ResolvedColumn
    terminals: tuple[ImpactedAsset, ...] = ()
    truncated: bool = False
    truncation_reason: str = ""
    visited_count: int = 0
    notes: tuple[str, ...] = ()

    @property
    def models(self) -> tuple[ImpactedAsset, ...]:
        return tuple(t for t in self.terminals if t.entity_type == "mlModel")

    @property
    def deployments(self) -> tuple[ImpactedAsset, ...]:
        return tuple(t for t in self.terminals if t.entity_type == "mlModelDeployment")


# --------------------------------------------------------------------------- #
# Phase 1C: scoring (minimal — extended later)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScoredImpact:
    """An impacted asset with a deterministic severity and the rule clauses that fired.

    ``reasons`` traces the score back to the rules table in ``scoring.py`` — a judge
    can read them and follow each clause to the table. Determined by plain Python
    rules, NOT the LLM (architectural rule 1).
    """

    asset: ImpactedAsset
    severity: Severity
    trained_on: bool = False
    deployed: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def rationale(self) -> str:
        """A one-line human summary — the reason clauses joined."""
        return "; ".join(self.reasons)


# --------------------------------------------------------------------------- #
# Phase 1D: pull-request context (shared by write-back + GitHub integration)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PRContext:
    """Identity of the pull request under review — the thing we link findings back to.

    Populated from CLI flags or GitHub Actions env. ``key`` is the stable identifier
    used to make write-back idempotent (deterministic incident/document URNs derive
    from it); ``link`` is what we show a human.
    """

    repo: str = ""              # "owner/name"
    number: int | None = None
    url: str = ""               # full PR URL, for linking back
    sha: str = ""               # head commit sha
    title: str = ""
    branch: str = ""

    @property
    def key(self) -> str:
        """Stable identifier for idempotency (repo#number, else the URL, else a marker)."""
        if self.repo and self.number:
            return f"{self.repo}#{self.number}"
        return self.url or "local-pr"

    @property
    def link(self) -> str:
        """Best human-facing reference to the PR."""
        return self.url or self.key


__all__ = [
    "ChangeKind",
    "Severity",
    "FileStatus",
    "Side",
    "SqlFileChange",
    "ChangeEvent",
    "UnresolvedProjection",
    "ModelDelta",
    "SchemaProvider",
    "ResolutionStatus",
    "DatasetMatch",
    "ResolvedTable",
    "ResolvedColumn",
    "PathHop",
    "ImpactPath",
    "TrainingEvidence",
    "DeploymentDetail",
    "ImpactedAsset",
    "ImpactGraph",
    "ScoredImpact",
    "PRContext",
]
