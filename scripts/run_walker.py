"""Run the Phase 1B walker against the live DataHub and pretty-print the ImpactGraph.

Usage:
    .venv/bin/python scripts/run_walker.py                 # demo target (customers.customer_since)
    .venv/bin/python scripts/run_walker.py <table> <column>

Deterministic: same inputs -> same output (architectural rule 1).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from blastradar.datahub.client import DataHubClient  # noqa: E402
from blastradar.datahub.resolver import Resolver  # noqa: E402
from blastradar.datahub.urns import short_name  # noqa: E402
from blastradar.datahub.walker import walk  # noqa: E402
from blastradar.models import ChangeEvent, ChangeKind, ImpactGraph  # noqa: E402


def render(graph: ImpactGraph) -> None:
    r = graph.resolution
    print("=" * 74)
    print("BLASTRADAR — downstream ML impact (Phase 1B walker)")
    print("=" * 74)
    print(f"Change        : {graph.change.kind.value}  {graph.change.table}.{graph.change.column}")
    print(f"Resolution    : {r.status.value}  ({r.note})")
    print(f"Source column : {r.schema_field_urn}")
    print(f"Terminals     : {len(graph.terminals)}  "
          f"({len(graph.models)} models, {len(graph.deployments)} deployments)")
    print(f"Visited nodes : {graph.visited_count}   truncated={graph.truncated}"
          f"{' — ' + graph.truncation_reason if graph.truncated else ''}")
    if graph.notes:
        print(f"Notes         : {'; '.join(graph.notes)}")
    print()

    for a in graph.models:
        t = a.training
        train = "TRAINED-ON" if (t and t.trained_on) else "inference-only"
        deployed = "DEPLOYED" if a.deployments else "not deployed"
        print(f"■ mlModel {a.name}  (v{a.version}, group={short_name(a.model_group) if a.model_group else '?'})"
              f"  [{train}, {deployed}]")
        if t:
            run = t.training_run_urn.split(':')[-1][:12] if t.training_run_urn else "?"
            if t.trained_on:
                print(f"    training evidence: run {run} trained on "
                      f"{short_name(t.matched_input_dataset)}  ← the changed dataset")
            else:
                inputs = ", ".join(short_name(d) for d in t.input_datasets) or "(none)"
                print(f"    training evidence: run {run} inputs = [{inputs}] — "
                      f"changed dataset NOT present")
        for d in a.deployments:
            print(f"    deployment: {short_name(d.urn)}  status={d.status}")
        if a.owners:
            print(f"    owners: {', '.join(short_name(o) for o in a.owners)}")
        if a.tags:
            print(f"    tags: {', '.join(short_name(x) for x in a.tags)}")
        for i, p in enumerate(a.paths, 1):
            chain = f"{graph.change.table}.{graph.change.column}"
            for h in p.hops:
                col = f"[{h.column}]" if h.column else ""
                tx = f" {{{h.transform}}}" if h.transform else ""
                chain += f"  --{h.edge_kind}-->  {short_name(h.to_urn)}{col}{tx}"
            print(f"    path {i}: {chain}")
        print()


def main() -> int:
    table = sys.argv[1] if len(sys.argv) > 1 else "customers"
    column = sys.argv[2] if len(sys.argv) > 2 else "customer_since"

    client = DataHubClient.from_env()
    client.test_connection()
    resolver = Resolver(client)
    change = ChangeEvent(kind=ChangeKind.DROP_COLUMN, table=table, column=column,
                         source_file=f"models/{table}.sql")
    graph = walk(change, client=client, resolver=resolver)
    render(graph)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
