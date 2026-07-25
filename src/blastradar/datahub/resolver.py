"""Resolve SQL names to DataHub URNs.

A dbt model file ``fct_orders.sql`` may be registered under several platforms
(dbt, snowflake, s3, postgres, ...). This module searches DataHub, prefers exact
name matches, then a configurable platform priority, and — crucially — when several
candidates remain equally good it returns them ALL as AMBIGUOUS rather than
silently picking one. Nothing here raises for a miss; callers inspect the status.

It also provides :class:`DataHubSchemaProvider`, which implements the Phase 1A
``SchemaProvider`` protocol so ``sql_delta`` can expand external ``SELECT *`` via
live schema — the wire-up point promised in Phase 1A.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from datahub.emitter.mce_builder import make_schema_field_urn

from blastradar.datahub.client import DataHubClient
from blastradar.datahub.urns import last_segment
from blastradar.models import (
    DatasetMatch,
    ResolutionStatus,
    ResolvedColumn,
    ResolvedTable,
)

logger = logging.getLogger(__name__)

# Default platform priority: dbt first (models usually originate there), then the
# warehouses, then everything else. Configurable per resolver.
DEFAULT_PLATFORM_PRIORITY: tuple[str, ...] = (
    "dbt", "snowflake", "bigquery", "redshift", "postgres", "hive", "s3", "kafka",
)


class Resolver:
    """Resolves table names to dataset URNs and columns to schemaField URNs."""

    def __init__(
        self,
        client: DataHubClient,
        *,
        platform_priority: Sequence[str] = DEFAULT_PLATFORM_PRIORITY,
    ) -> None:
        self._client = client
        self._priority = tuple(platform_priority)

    def _rank(self, platform: str) -> int:
        try:
            return self._priority.index(platform)
        except ValueError:
            return len(self._priority)

    def resolve_table(self, table: str) -> ResolvedTable:
        """Resolve a table/model name to a dataset URN.

        Strategy: search by the last name segment, keep only exact last-segment
        matches, rank by platform priority; a unique best -> RESOLVED, a tie at the
        best rank -> AMBIGUOUS (all returned), nothing -> UNRESOLVED. Deterministic.
        """
        query = last_segment(table)
        hits = self._client.search_datasets(query)
        candidates = tuple(
            DatasetMatch(
                urn=h["urn"], platform=h["platform"], name=h["name"],
                exact=last_segment(h["name"]).lower() == query.lower(),
            )
            for h in hits
        )
        exact = [c for c in candidates if c.exact]
        if not exact:
            return ResolvedTable(
                query=table, status=ResolutionStatus.UNRESOLVED, candidates=(),
                note=(f"no exact match for '{query}' among {len(candidates)} fuzzy "
                      f"candidate(s)"),
            )
        ranked = tuple(sorted(exact, key=lambda c: (self._rank(c.platform), c.urn)))
        best_rank = self._rank(ranked[0].platform)
        best = [c for c in ranked if self._rank(c.platform) == best_rank]
        if len(best) == 1:
            return ResolvedTable(
                query=table, status=ResolutionStatus.RESOLVED,
                candidates=ranked, chosen=best[0].urn,
                note=f"resolved to {best[0].platform} (of {len(ranked)} exact match(es))",
            )
        return ResolvedTable(
            query=table, status=ResolutionStatus.AMBIGUOUS,
            candidates=tuple(best),
            note=(f"{len(best)} candidates tie at top platform rank "
                  f"({best[0].platform}) — caller must choose"),
        )

    def resolve_column(self, table: str, column: str | None) -> ResolvedColumn:
        """Resolve a (table, column) to a schemaField URN, validating the column exists.

        UNRESOLVED / AMBIGUOUS statuses propagate from table resolution. If the table
        resolves but the column is absent from its schema, returns UNRESOLVED with a
        note (still surfacing the dataset URN for context).
        """
        rt = self.resolve_table(table)
        if rt.status is ResolutionStatus.UNRESOLVED:
            return ResolvedColumn(table=table, column=column,
                                  status=ResolutionStatus.UNRESOLVED, note=rt.note)
        if rt.status is ResolutionStatus.AMBIGUOUS:
            return ResolvedColumn(table=table, column=column,
                                  status=ResolutionStatus.AMBIGUOUS,
                                  candidates=rt.candidates, note=rt.note)

        dataset_urn = rt.chosen
        assert dataset_urn is not None
        if column is None:  # e.g. DROP_TABLE — dataset resolved, no column
            return ResolvedColumn(table=table, column=None,
                                  status=ResolutionStatus.RESOLVED, dataset_urn=dataset_urn,
                                  note=rt.note)

        fields = self._client.get_schema_fields(dataset_urn)
        match = next((f["field_path"] for f in fields
                      if f["field_path"].lower() == column.lower()), None)
        if match is None:
            return ResolvedColumn(
                table=table, column=column, status=ResolutionStatus.UNRESOLVED,
                dataset_urn=dataset_urn,
                note=f"column '{column}' not found in {dataset_urn} schema "
                     f"({len(fields)} fields)",
            )
        return ResolvedColumn(
            table=table, column=match, status=ResolutionStatus.RESOLVED,
            dataset_urn=dataset_urn,
            schema_field_urn=make_schema_field_urn(dataset_urn, match),
            note=rt.note,
        )


class DataHubSchemaProvider:
    """Live schema provider for Phase 1A ``SELECT *`` expansion (SchemaProvider protocol)."""

    def __init__(self, resolver: Resolver, client: DataHubClient) -> None:
        self._resolver = resolver
        self._client = client

    def get_columns(self, relation: str) -> list[str] | None:
        """Return column names of an external relation, or None if it can't be resolved."""
        rt = self._resolver.resolve_table(relation)
        if rt.status is not ResolutionStatus.RESOLVED or rt.chosen is None:
            logger.debug("schema provider: %s -> %s", relation, rt.status.value)
            return None
        return [f["field_path"] for f in self._client.get_schema_fields(rt.chosen)]
