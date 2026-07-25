"""Offline Blastradar demo — the whole pipeline on recorded fixtures (Phase 2).

Runs diff → delta → resolve → walk → score → narrate → report against the recorded
DataHub fixtures with **no DataHub, no network, and no API key** (templated
narration), prints the rendered PR comment, and writes it to ``examples/``. This is
``make demo`` (architectural rule 3), and it must finish in well under 60 seconds.

    make demo                       # the flagship (critical) scenario
    .venv/bin/python scripts/demo.py --scenario medium
    .venv/bin/python scripts/demo.py --scenario all --quiet   # regenerate every example

It works by pointing the client at the recording (``BLASTRADAR_REPLAY``) so the real
``DataHubClient.from_env()`` returns a :class:`ReplayClient`; the pipeline is
otherwise identical to the live CLI. Narration is always the templated fallback so
the output is deterministic and the committed examples don't churn. Write-back is
forced OFF (offline), so the comment shows the '🚫 would write' plan — the honest
offline state.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

RECORDING = REPO_ROOT / "tests" / "fixtures" / "recorded" / "datahub_calls.json"
EXAMPLES = REPO_ROOT / "examples"


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    changes: Path
    out_stem: str
    pr_repo: str
    pr_number: int
    blurb: str


SCENARIOS: dict[str, Scenario] = {
    "critical": Scenario(
        key="critical",
        title="Critical — drop customers.customer_since (trained-on, deployed)",
        changes=REPO_ROOT / "demo-repo" / "demo-pr.json",
        out_stem="impact-critical-trained-on",
        pr_repo="order-entry/analytics", pr_number=42,
        blurb="A dropped account-age column that a deployed churn model was trained on.",
    ),
    "medium": Scenario(
        key="medium",
        title="Medium — drop order_details.order_total (non-deployed model)",
        changes=REPO_ROOT / "demo-repo" / "medium-pr.json",
        out_stem="impact-medium-non-deployed",
        pr_repo="order-entry/analytics", pr_number=57,
        blurb="A dropped column feeding one model that isn't in production yet.",
    ),
    "clean": Scenario(
        key="clean",
        title="Clean — drop customers.phone_number (no ML downstream)",
        changes=REPO_ROOT / "demo-repo" / "clean-pr.json",
        out_stem="impact-clean-no-impact",
        pr_repo="order-entry/analytics", pr_number=63,
        blurb="A dropped column that no ML feature depends on — a clean bill of health.",
    ),
}


def _run(scenario: Scenario, *, write: bool, quiet: bool) -> str:
    # Point the client at the recording and force write-back OFF so the run is fully
    # offline and hermetic regardless of the caller's environment.
    os.environ["BLASTRADAR_REPLAY"] = str(RECORDING)
    os.environ["TOOLS_IS_MUTATION_ENABLED"] = "false"

    from blastradar.datahub.client import DataHubClient
    from blastradar.datahub.resolver import DataHubSchemaProvider, Resolver
    from blastradar.diff.extract import extract_from_json
    from blastradar.models import PRContext
    from blastradar.pipeline import empty_message, finalize, run_analysis

    pr = PRContext(
        repo=scenario.pr_repo, number=scenario.pr_number,
        url=f"https://github.com/{scenario.pr_repo}/pull/{scenario.pr_number}",
        sha="demo0000", title=scenario.title,
    )

    client = DataHubClient.from_env()
    client.test_connection()
    resolver = Resolver(client)
    schema = DataHubSchemaProvider(resolver, client)

    with scenario.changes.open(encoding="utf-8") as fh:
        changes = extract_from_json(fh)
    result = run_analysis(changes, client=client, resolver=resolver, schema=schema)
    msg = empty_message(result, changes)
    if msg is not None:  # pragma: no cover - demo scenarios always produce output
        return msg

    report = finalize(result, pr=pr, use_llm=False, client=client,
                      do_writeback=True, dry_run=False)

    if write:
        EXAMPLES.mkdir(parents=True, exist_ok=True)
        md_path = EXAMPLES / f"{scenario.out_stem}.md"
        json_path = EXAMPLES / f"{scenario.out_stem}.json"
        md_path.write_text(report.markdown.rstrip() + "\n")
        json_path.write_text(json.dumps(report.data, indent=2) + "\n")
        if not quiet:
            print(f"  wrote {md_path.relative_to(REPO_ROOT)} + "
                  f"{json_path.relative_to(REPO_ROOT)}", file=sys.stderr)
    return report.markdown


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline Blastradar demo on recorded fixtures.")
    ap.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="critical",
                    help="Which impact shape to run (default: critical).")
    ap.add_argument("--no-write", action="store_true",
                    help="Print only; do not (re)write files under examples/.")
    ap.add_argument("--quiet", action="store_true",
                    help="Suppress the rendered comment on stdout (still writes files).")
    args = ap.parse_args()

    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(name)s: %(message)s")

    if not RECORDING.exists():
        raise SystemExit(
            f"No recording at {RECORDING.relative_to(REPO_ROOT)}.\n"
            f"Generate it with `make record-fixtures` (needs a live DataHub), or run "
            f"`make demo-live` for the live path.")

    keys = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    for i, key in enumerate(keys):
        scenario = SCENARIOS[key]
        if not args.quiet:
            if i:
                print("\n" + "=" * 78)
            print(f"BLASTRADAR — offline demo (recorded fixtures, no DataHub / network / API key)")
            print(f"Scenario: {scenario.title}")
            print("=" * 78 + "\n")
        markdown = _run(scenario, write=not args.no_write, quiet=args.quiet)
        if not args.quiet:
            print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
