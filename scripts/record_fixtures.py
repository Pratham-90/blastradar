"""Record live DataHub responses into fixtures for the offline paths (Phase 2).

Runs the real pipeline against a live DataHub with an ``observer`` attached to the
client, capturing every DataHub call + response by request signature. The result
drives both the 60-second offline ``make demo`` and the whole test suite
(architectural rule 3 — the fixtures double as the tests).

    make record-fixtures            # or: .venv/bin/python scripts/record_fixtures.py

Regenerating is a Makefile target on purpose: hand-maintained fixtures rot. When the
seed or the graph changes, re-run this against a freshly-seeded local DataHub
(`make seed`) and commit the updated recording.

What it records (one combined, signature-keyed file — unioning scenarios is free):
  * the three demo/example PRs (critical, medium, clean) driven through the SAME
    ``pipeline.run_analysis`` the demo/tests use, so every read they make is captured;
  * ``test_connection`` (the CLI calls it on startup);
  * a couple of edge-case walks the test suite asserts on (an unresolvable table).

Read docs/API-NOTES.md before touching anything DataHub-shaped.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from blastradar.datahub.client import DataHubClient  # noqa: E402
from blastradar.datahub.replay import Recorder  # noqa: E402
from blastradar.datahub.resolver import DataHubSchemaProvider, Resolver  # noqa: E402
from blastradar.datahub.walker import walk  # noqa: E402
from blastradar.diff.extract import extract_from_json  # noqa: E402
from blastradar.models import ChangeEvent, ChangeKind  # noqa: E402
from blastradar.pipeline import run_analysis  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("record_fixtures")

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "tests" / "fixtures" / "recorded" / "datahub_calls.json"

# The demo + example PRs, driven through the real pipeline (this is what the demo
# and the generated examples replay).
CHANGESET_SCENARIOS: list[tuple[str, Path]] = [
    ("critical (drop customers.customer_since)", REPO_ROOT / "demo-repo" / "demo-pr.json"),
    ("medium   (drop order_details.order_total)", REPO_ROOT / "demo-repo" / "medium-pr.json"),
    ("clean    (drop customers.phone_number)", REPO_ROOT / "demo-repo" / "clean-pr.json"),
]

# Extra edge-case walks the test suite asserts on but that aren't a demo PR.
DIRECT_WALKS: list[tuple[str, str]] = [
    ("totally_made_up_xyz", "foo"),   # unresolvable table -> clean result, never an error
]


def main() -> int:
    if os.environ.get("BLASTRADAR_REPLAY"):
        raise SystemExit(
            "BLASTRADAR_REPLAY is set — unset it to record against the LIVE DataHub.")

    recorder = Recorder()
    client = DataHubClient.from_env(observer=recorder)
    try:
        client.test_connection()
    except Exception as e:  # noqa: BLE001 — a live DataHub is required to record
        raise SystemExit(
            f"Cannot reach DataHub to record fixtures ({type(e).__name__}: {e}).\n"
            f"Start one with `make demo-live` (or `datahub docker quickstart` + `make seed`) "
            f"and retry.") from e

    resolver = Resolver(client)
    schema = DataHubSchemaProvider(resolver, client)

    for label, path in CHANGESET_SCENARIOS:
        with path.open(encoding="utf-8") as fh:
            changes = extract_from_json(fh)
        result = run_analysis(changes, client=client, resolver=resolver, schema=schema)
        n_impacts = sum(len(a.graph.terminals) for a in result.analyses)
        logger.info("  recorded scenario %-42s -> %d change(s), %d ML terminal(s)",
                    label, len(result.analyses), n_impacts)

    for table, column in DIRECT_WALKS:
        change = ChangeEvent(kind=ChangeKind.DROP_COLUMN, table=table, column=column,
                             source_file=f"models/{table}.sql")
        graph = walk(change, client=client, resolver=resolver)
        logger.info("  recorded edge-case walk %-30s -> resolution=%s",
                    f"{table}.{column}", graph.resolution.status.value)

    count = recorder.save(
        OUT_PATH,
        description=("Recorded DataHub reads for the offline demo + test suite. "
                     "Regenerate with `make record-fixtures` against a freshly-seeded "
                     "local DataHub."),
    )
    logger.info("\nWrote %d unique DataHub call(s) -> %s",
                count, OUT_PATH.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
