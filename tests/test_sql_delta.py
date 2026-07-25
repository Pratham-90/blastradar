"""Tests for the SQL delta analyzer (Phase 1A). Pure — no DataHub, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from blastradar.diff.sql_delta import SqlDeltaError, analyze_delta
from blastradar.models import ChangeKind, FileStatus, Side, SqlFileChange

FIXTURES = Path(__file__).parent / "fixtures" / "sql"


def _read(case: str, side: str) -> str:
    return (FIXTURES / case / f"{side}.sql").read_text()


def _modified(case: str) -> SqlFileChange:
    """Load a fixture's before/after as a MODIFIED SqlFileChange."""
    return SqlFileChange(
        path=f"models/{case}.sql",
        status=FileStatus.MODIFIED,
        before=_read(case, "before"),
        after=_read(case, "after"),
    )


def test_simple_column_drop() -> None:
    delta = analyze_delta(_modified("simple_drop"))
    assert not delta.has_unresolved
    assert len(delta.changes) == 1
    ev = delta.changes[0]
    assert ev.kind is ChangeKind.DROP_COLUMN
    assert ev.column == "email"
    assert ev.table == "simple_drop"
    assert ev.source_file == "models/simple_drop.sql"


def test_column_drop_inside_cte_propagates() -> None:
    # Outer `SELECT * FROM base` expands the CTE locally (no schema needed); the
    # column dropped inside the CTE must surface as a DROP on the output.
    delta = analyze_delta(_modified("cte_drop"))
    assert not delta.has_unresolved, "CTE stars resolve locally — no marker expected"
    kinds = [(c.kind, c.column) for c in delta.changes]
    assert kinds == [(ChangeKind.DROP_COLUMN, "email")]


def test_rename_alias_change() -> None:
    delta = analyze_delta(_modified("rename"))
    assert len(delta.changes) == 1
    ev = delta.changes[0]
    assert ev.kind is ChangeKind.RENAME_COLUMN
    assert ev.column == "cid"
    assert ev.new_column == "customer_ref"
    # A rename must NOT be reported as a drop + add.
    assert all(c.kind is not ChangeKind.DROP_COLUMN for c in delta.changes)


def test_type_change_via_cast() -> None:
    delta = analyze_delta(_modified("type_change"))
    assert len(delta.changes) == 1
    ev = delta.changes[0]
    assert ev.kind is ChangeKind.TYPE_CHANGE
    assert ev.column == "order_total"
    assert ev.old_type is not None and ev.new_type is not None
    assert ev.old_type != ev.new_type
    # sqlglot normalizes types per dialect: snowflake NUMBER(10,2)->DECIMAL, FLOAT->DOUBLE.
    assert "DECIMAL" in ev.old_type.upper()
    assert ev.new_type.upper() == "DOUBLE"


def test_where_reorder_produces_no_events() -> None:
    delta = analyze_delta(_modified("where_reorder"))
    assert not delta.has_unresolved
    assert delta.changes == ()


def test_select_star_external_is_unresolved() -> None:
    delta = analyze_delta(_modified("select_star"))
    # Must NOT be an empty change set — it must be an explicit marker.
    assert delta.has_unresolved
    assert delta.changes == ()
    marker = delta.unresolved[0]
    assert marker.side is Side.AFTER
    assert marker.star_sources == ("raw.customers",)


def test_select_star_expanded_with_schema_provider() -> None:
    # Same fixture, but a provider supplies the external table's columns so the
    # SAME code path expands the star and finds the real drop (phone).
    class FakeSchema:
        def get_columns(self, relation: str) -> list[str] | None:
            return ["customer_id", "email"] if relation == "raw.customers" else None

    delta = analyze_delta(_modified("select_star"), schema=FakeSchema())
    assert not delta.has_unresolved
    assert [(c.kind, c.column) for c in delta.changes] == [
        (ChangeKind.DROP_COLUMN, "phone")
    ]


def test_malformed_sql_raises_with_filename() -> None:
    change = SqlFileChange(
        path="models/broken.sql",
        status=FileStatus.MODIFIED,
        before=_read("simple_drop", "before"),
        after=_read("malformed", "after"),
    )
    with pytest.raises(SqlDeltaError) as exc:
        analyze_delta(change)
    assert "broken.sql" in str(exc.value)
    assert "after" in str(exc.value)


def test_deleted_file_is_drop_table() -> None:
    change = SqlFileChange(
        path="models/orders.sql",
        status=FileStatus.DELETED,
        before=_read("simple_drop", "before"),
        after=None,
    )
    delta = analyze_delta(change)
    assert [c.kind for c in delta.changes] == [ChangeKind.DROP_TABLE]
    assert delta.changes[0].table == "orders"
    assert delta.changes[0].column is None


def test_added_file_is_not_breaking() -> None:
    change = SqlFileChange(
        path="models/new_model.sql",
        status=FileStatus.ADDED,
        before=None,
        after=_read("simple_drop", "after"),
    )
    delta = analyze_delta(change)
    assert delta.changes == ()
    assert not delta.has_unresolved
