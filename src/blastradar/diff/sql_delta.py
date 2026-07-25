"""SQL delta analyzer: diff two versions of a model to find output-column changes.

Uses sqlglot (never regex). For each changed ``.sql`` file it resolves the model's
*output projection* — the set of columns the query produces, with each column's
underlying expression and any CAST type — for the before and after versions, then
diffs those sets into :class:`ChangeEvent` objects (drop / rename / type-change).

Design notes:
  * Renames are detected heuristically: a dropped output name and an added output
    name that share the same underlying expression are one RENAME_COLUMN, not a
    drop + add.
  * ``SELECT *`` from a CTE or subquery is expanded locally (the definition is in
    the query). ``SELECT *`` from an *external* table needs schema we don't have in
    this phase: with no :class:`SchemaProvider` it yields an
    :class:`UnresolvedProjection` marker (Phase 1B expands it); with a provider the
    same code path expands it in place.
  * Parse failures raise :class:`SqlDeltaError` naming the file — we never silently
    return an empty change set, which would read as "no impact" when we actually
    failed.

Default dialect is snowflake; override per call.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from blastradar.models import (
    ChangeEvent,
    ChangeKind,
    FileStatus,
    ModelDelta,
    SchemaProvider,
    Side,
    SqlFileChange,
    UnresolvedProjection,
)

logger = logging.getLogger(__name__)

DEFAULT_DIALECT = "snowflake"

# CAST node types whose target type we can read (`CAST(x AS t)`, `x::t`, `TRY_CAST`).
_CAST_TYPES: tuple[type, ...] = tuple(
    t for t in (getattr(exp, "Cast", None), getattr(exp, "TryCast", None)) if t
)


class SqlDeltaError(Exception):
    """Raised when SQL cannot be parsed or the delta cannot be computed. Loud by design."""


@dataclass(frozen=True)
class _ColumnSpec:
    """How one output column is produced: its base expression and optional CAST type."""

    base_expr: str          # normalized SQL of the value, stripped of outer CAST + alias
    cast_type: str | None   # target type of an outermost CAST, else None


@dataclass(frozen=True)
class _Projection:
    """A resolved output projection: output-name -> spec, plus unresolvable star sources."""

    columns: dict[str, _ColumnSpec]
    unresolved_sources: tuple[str, ...]


def table_name_from_path(path: str) -> str:
    """Return the logical model name for a file path (the filename stem).

    Assumes dbt-style one-model-per-file naming (``models/customers.sql`` -> ``customers``).
    """
    return Path(path).stem


# --------------------------------------------------------------------------- #
# Projection resolution
# --------------------------------------------------------------------------- #
def _relation_ref(table: exp.Table) -> str:
    """The table reference as written, schema-qualified where present (``raw.customers``)."""
    return ".".join(p for p in (table.catalog, table.db, table.name) if p)


def _direct_sources(select: exp.Select) -> list[exp.Expression]:
    """The FROM + JOIN source expressions directly on this SELECT (not nested)."""
    sources: list[exp.Expression] = []
    frm = select.args.get("from_")
    if frm is not None:
        sources.append(frm.this)
    for join in select.args.get("joins") or []:
        sources.append(join.this)
    return sources


def _source_label(source: exp.Expression) -> str:
    """Alias-or-name used to match a qualified ``alias.*`` to its source."""
    alias = source.alias
    if alias:
        return alias
    if isinstance(source, exp.Table):
        return source.name
    return ""


def _spec_for_expr(proj: exp.Expression, dialect: str) -> tuple[str, _ColumnSpec]:
    """Compute (output_name, spec) for a normal (non-star) projection expression."""
    if isinstance(proj, exp.Alias):
        name = proj.alias
        inner: exp.Expression = proj.this
    else:
        name = proj.output_name
        inner = proj
    cast_type: str | None = None
    if _CAST_TYPES and isinstance(inner, _CAST_TYPES):
        cast_type = inner.to.sql(dialect=dialect)
        inner = inner.this
    base_expr = inner.sql(dialect=dialect, normalize=True)
    if not name:  # anonymous expression column — fall back to its expression text
        name = base_expr
    return name, _ColumnSpec(base_expr=base_expr, cast_type=cast_type)


def _outermost_select(root: exp.Expression) -> exp.Select:
    """Peel UNION wrappers to the leading SELECT; raise on unsupported statements."""
    node = root
    while isinstance(node, exp.Union):
        node = node.this
    if isinstance(node, exp.Subquery):
        node = node.this
    if not isinstance(node, exp.Select):
        raise SqlDeltaError(
            f"unsupported top-level statement: {type(node).__name__} "
            f"(expected a SELECT / CTE / UNION)"
        )
    return node


def _resolve_projection(
    select: exp.Select,
    dialect: str,
    schema: SchemaProvider | None,
    cte_scope: dict[str, exp.Select],
) -> _Projection:
    """Resolve a SELECT's output projection, expanding stars where possible.

    ``cte_scope`` maps CTE names visible here to their definition SELECTs. Stars over
    a CTE/subquery are expanded by recursion; stars over an external table are
    expanded via ``schema`` if given, else recorded as unresolved.
    """
    scope = dict(cte_scope)
    for cte in select.ctes:
        scope[cte.alias] = cte.this

    columns: dict[str, _ColumnSpec] = {}
    unresolved: list[str] = []

    def expand_source(source: exp.Expression) -> None:
        if isinstance(source, exp.Subquery):
            inner = _resolve_projection(_outermost_select(source.this), dialect, schema, scope)
            columns.update(inner.columns)
            unresolved.extend(inner.unresolved_sources)
            return
        if isinstance(source, exp.Table):
            if not source.db and source.name in scope:  # CTE reference
                inner = _resolve_projection(scope[source.name], dialect, schema, scope)
                columns.update(inner.columns)
                unresolved.extend(inner.unresolved_sources)
                return
            relation = _relation_ref(source)
            cols = schema.get_columns(relation) if schema is not None else None
            if cols is None:
                unresolved.append(relation)
            else:
                for col in cols:
                    columns[col] = _ColumnSpec(base_expr=f"{relation}.{col}", cast_type=None)
            return
        unresolved.append(source.sql(dialect=dialect))  # table function, etc.

    sources = _direct_sources(select)
    for proj in select.selects:
        if isinstance(proj, exp.Star):
            for src in sources:
                expand_source(src)
        elif isinstance(proj, exp.Column) and isinstance(proj.this, exp.Star):
            target = proj.table
            matched = [s for s in sources if _source_label(s) == target]
            for src in matched or sources:
                expand_source(src)
        else:
            name, spec = _spec_for_expr(proj, dialect)
            columns[name] = spec

    return _Projection(columns=columns, unresolved_sources=tuple(dict.fromkeys(unresolved)))


def _parse(sql: str, dialect: str, path: str, side: Side) -> exp.Select:
    """Parse SQL to its outermost SELECT, raising :class:`SqlDeltaError` on failure."""
    try:
        root = sqlglot.parse_one(sql, read=dialect)
    except SqlglotError as e:
        raise SqlDeltaError(f"failed to parse {path} ({side.value}) as {dialect}: {e}") from e
    if root is None:
        raise SqlDeltaError(f"failed to parse {path} ({side.value}): empty parse result")
    return _outermost_select(root)


# --------------------------------------------------------------------------- #
# Diffing
# --------------------------------------------------------------------------- #
def _looks_like_reference(base_expr: str) -> bool:
    """True if an expression plausibly identifies a real column (for rename matching).

    Guards against pairing two unrelated literals/`NULL`s as a rename.
    """
    stripped = base_expr.strip().strip("()")
    if not stripped:
        return False
    if stripped.upper() in {"NULL", "TRUE", "FALSE"}:
        return False
    return not (stripped[0].isdigit() or stripped[0] in "'\"")


def _diff_projections(
    before: _Projection,
    after: _Projection,
    *,
    table: str,
    source_file: str,
) -> list[ChangeEvent]:
    """Diff two resolved projections into deterministic ChangeEvents."""
    b, a = before.columns, after.columns
    dropped = [n for n in b if n not in a]
    added = [n for n in a if n not in b]

    def mk(**kw) -> ChangeEvent:
        return ChangeEvent(table=table, source_file=source_file, **kw)

    events: list[ChangeEvent] = []
    consumed_adds: set[str] = set()

    # Renames: a dropped name and an added name sharing the same base expression.
    for d in sorted(dropped):
        for cand in sorted(added):
            if cand in consumed_adds:
                continue
            if b[d].base_expr == a[cand].base_expr and _looks_like_reference(b[d].base_expr):
                consumed_adds.add(cand)
                events.append(mk(
                    kind=ChangeKind.RENAME_COLUMN, column=d, new_column=cand,
                    old_type=b[d].cast_type, new_type=a[cand].cast_type,
                    diff_hunk=f"{d} -> {cand}  ({b[d].base_expr})",
                ))
                break
        else:
            events.append(mk(
                kind=ChangeKind.DROP_COLUMN, column=d, old_type=b[d].cast_type,
                diff_hunk=f"- {d}  ({b[d].base_expr})",
            ))

    # Type changes: same output name, differing CAST target type.
    for name in sorted(set(b) & set(a)):
        bt, at = b[name].cast_type, a[name].cast_type
        if bt != at and (bt is not None or at is not None):
            events.append(mk(
                kind=ChangeKind.TYPE_CHANGE, column=name, old_type=bt, new_type=at,
                diff_hunk=f"{name}: {bt} -> {at}",
            ))
    return events


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def analyze_delta(
    change: SqlFileChange,
    *,
    dialect: str = DEFAULT_DIALECT,
    schema: SchemaProvider | None = None,
) -> ModelDelta:
    """Compute the column-level delta for one changed SQL file.

    Assumes one model per file (table name = filename stem). A DELETED file becomes a
    DROP_TABLE; an ADDED file is not a breaking change (empty delta). For a MODIFIED
    file, the before/after output projections are resolved and diffed.

    If either version's projection cannot be fully resolved (external ``SELECT *`` with
    no ``schema`` provider), the diff is skipped and an :class:`UnresolvedProjection`
    marker is returned instead — never an empty change set masquerading as "no impact".

    Raises :class:`SqlDeltaError` on parse failure, naming the file.
    """
    table = table_name_from_path(change.path)

    if change.status is FileStatus.DELETED:
        return ModelDelta(
            source_file=change.path, table=table,
            changes=(ChangeEvent(
                kind=ChangeKind.DROP_TABLE, table=table, source_file=change.path,
                diff_hunk=f"deleted {change.path}",
            ),),
        )
    if change.status is FileStatus.ADDED:
        return ModelDelta(source_file=change.path, table=table)  # new model, non-breaking

    if change.before is None or change.after is None:
        raise SqlDeltaError(
            f"{change.path}: MODIFIED file missing before/after content"
        )

    before = _resolve_projection(
        _parse(change.before, dialect, change.path, Side.BEFORE), dialect, schema, {}
    )
    after = _resolve_projection(
        _parse(change.after, dialect, change.path, Side.AFTER), dialect, schema, {}
    )

    unresolved: list[UnresolvedProjection] = []
    if before.unresolved_sources:
        unresolved.append(UnresolvedProjection(
            table=table, star_sources=before.unresolved_sources, side=Side.BEFORE,
            source_file=change.path,
            reason=f"SELECT * from external relation(s): {', '.join(before.unresolved_sources)}",
        ))
    if after.unresolved_sources:
        unresolved.append(UnresolvedProjection(
            table=table, star_sources=after.unresolved_sources, side=Side.AFTER,
            source_file=change.path,
            reason=f"SELECT * from external relation(s): {', '.join(after.unresolved_sources)}",
        ))

    if unresolved:
        # Ambiguous without schema: emit markers, skip the (unreliable) diff.
        logger.warning(
            "%s: projection unresolved (%s) — deferring diff to schema expansion",
            change.path, ", ".join(u.reason for u in unresolved),
        )
        return ModelDelta(source_file=change.path, table=table, unresolved=tuple(unresolved))

    changes = _diff_projections(before, after, table=table, source_file=change.path)
    return ModelDelta(source_file=change.path, table=table, changes=tuple(changes))


def analyze_changes(
    changes: Iterable[SqlFileChange],
    *,
    dialect: str = DEFAULT_DIALECT,
    schema: SchemaProvider | None = None,
) -> list[ModelDelta]:
    """Run :func:`analyze_delta` over many files, preserving order."""
    return [analyze_delta(c, dialect=dialect, schema=schema) for c in changes]
