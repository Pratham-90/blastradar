"""Command-line entry point (click): diff → delta → resolve → walk → score → narrate → report.

    blastradar analyze --base <ref> --head <ref> [--repo-dir DIR]
    blastradar analyze --changes changeset.json          # offline / CI: JSON before-after

Then, for the PR under review, it writes findings back into DataHub (incident, tag,
document) and posts/updates a single PR comment:

    blastradar analyze --changes demo-repo/demo-pr.json \
        --pr-repo acme/analytics --pr-number 42 --write-back --post-comment

The analysis + assembly live in ``blastradar.pipeline`` (shared with the demo,
the fixture recorder, and the tests, so they cannot drift). This module only wires
CLI input to that pipeline and posts the comment. The LLM is called at most once,
inside ``finalize`` (architectural rule 1). Write-back requires
TOOLS_IS_MUTATION_ENABLED=true; without it the PR comment still posts and the
write-back section says so.

Set ``BLASTRADAR_REPLAY=<recording.json>`` to run the whole command offline against
recorded fixtures — no DataHub, network, or credentials (this is how ``make demo``
drives the real CLI).
"""

from __future__ import annotations

import json as _json
import logging
import os
import sys

import click

from blastradar.datahub.client import DataHubClient, DataHubClientError
from blastradar.datahub.resolver import DataHubSchemaProvider, Resolver
from blastradar.diff.extract import ExtractError, extract_from_git, extract_from_json
from blastradar.github import (
    DEFAULT_API_URL,
    PRTarget,
    post_or_update_comment,
    pr_context_from_env,
)
from blastradar.models import PRContext
from blastradar.pipeline import empty_message, finalize, run_analysis

logger = logging.getLogger(__name__)


def _resolve_pr(pr_repo: str, pr_number: int | None, pr_url: str,
                pr_sha: str, pr_title: str) -> PRContext:
    """Merge explicit --pr-* flags over anything discoverable in the Actions env."""
    env_ctx = pr_context_from_env() or PRContext()
    return PRContext(
        repo=pr_repo or env_ctx.repo,
        number=pr_number if pr_number is not None else env_ctx.number,
        url=pr_url or env_ctx.url,
        sha=pr_sha or env_ctx.sha,
        title=pr_title or env_ctx.title,
        branch=env_ctx.branch,
    )


@click.group()
def cli() -> None:
    """Blastradar — review data PRs for downstream ML impact."""


@cli.command()
@click.option("--base", help="Base git ref (e.g. main, HEAD~1). With --head; omit if --changes.")
@click.option("--head", help="Head git ref (e.g. HEAD, the PR branch). With --base.")
@click.option("--changes", "changes_json", type=click.Path(exists=True, dir_okay=False),
              help="JSON changeset file ([{path,before,after}]) instead of a git diff.")
@click.option("--repo-dir", default=".", show_default=True, help="Git work tree to diff.")
@click.option("--dialect", default="snowflake", show_default=True, help="SQL dialect for parsing.")
@click.option("--max-hops", default=6, show_default=True, type=int, help="Lineage hop cap.")
@click.option("--no-llm", is_flag=True, help="Skip the LLM; use the templated narration.")
@click.option("--json", "as_json", is_flag=True, help="Emit the machine-readable JSON.")
@click.option("--dry-run", is_flag=True,
              help="Read-only: skip the LLM, plan (don't perform) write-back, don't post.")
# --- write-back + PR comment ------------------------------------------------ #
@click.option("--write-back/--no-write-back", "do_writeback", default=True, show_default=True,
              help="Write incident/tag/document into DataHub (needs TOOLS_IS_MUTATION_ENABLED=true).")
@click.option("--post-comment/--no-post-comment", "do_comment", default=True, show_default=True,
              help="Post/update the PR comment (needs --pr-repo/--pr-number + a GitHub token).")
@click.option("--pr-repo", default="", help="PR repo 'owner/name' (else GITHUB_REPOSITORY).")
@click.option("--pr-number", type=int, default=None, help="PR number (else the Actions event).")
@click.option("--pr-url", default="", help="PR URL to link findings back to.")
@click.option("--pr-sha", default="", help="Head commit SHA (recorded on the document).")
@click.option("--pr-title", default="", help="PR title (context only).")
@click.option("--github-token", default="", help="GitHub token (else GITHUB_TOKEN env).")
@click.option("-v", "--verbose", is_flag=True, help="DEBUG logging to stderr.")
def analyze(base: str | None, head: str | None, changes_json: str | None, repo_dir: str,
            dialect: str, max_hops: int, no_llm: bool, as_json: bool, dry_run: bool,
            do_writeback: bool, do_comment: bool, pr_repo: str, pr_number: int | None,
            pr_url: str, pr_sha: str, pr_title: str, github_token: str, verbose: bool) -> None:
    """Analyze the ML blast radius of a PR's SQL changes, then write back + comment."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING,
                        stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    if dry_run:
        click.echo("[dry-run] read-only: LLM, DataHub write-back, and PR comment are simulated.",
                   err=True)

    pr = _resolve_pr(pr_repo, pr_number, pr_url, pr_sha, pr_title)

    # 1. Diff → the before/after of every changed .sql file (git refs OR a JSON changeset).
    try:
        if changes_json:
            with open(changes_json, encoding="utf-8") as fh:
                changes = extract_from_json(fh)
        elif base and head:
            changes = extract_from_git(base, head, repo_dir=repo_dir)
        else:
            raise click.UsageError("provide either --changes FILE or both --base and --head.")
    except ExtractError as e:
        raise click.ClickException(f"diff extraction failed: {e}") from e

    # 2. Connect to DataHub (read + write use the same client). A failure must not
    #    become a false all-clear. BLASTRADAR_REPLAY yields an offline ReplayClient.
    client: DataHubClient | None = None
    resolver: Resolver | None = None
    schema: DataHubSchemaProvider | None = None
    connect_note = ""
    try:
        client = DataHubClient.from_env()
        client.test_connection()
        resolver = Resolver(client)
        schema = DataHubSchemaProvider(resolver, client)
    except (DataHubClientError, OSError) as e:
        connect_note = f"DataHub unreachable ({type(e).__name__}: {e})"
        logger.warning(connect_note)

    # 3. Analyze (delta → walk). The only DataHub-reading step.
    result = run_analysis(changes, client=client, resolver=resolver, schema=schema,
                          dialect=dialect, max_hops=max_hops, connect_note=connect_note)
    msg = empty_message(result, changes)
    if msg is not None:
        click.echo(msg)
        return

    # 4. Score, narrate once, render, and write findings back (idempotent; gated).
    report = finalize(result, pr=pr, use_llm=not (no_llm or dry_run),
                      client=client, do_writeback=do_writeback, dry_run=dry_run)

    # 5. Post or update the single PR comment (degrades to SKIPPED with no token).
    comment = None
    if do_comment:
        token = github_token or os.environ.get("GITHUB_TOKEN", "")
        api_url = os.environ.get("GITHUB_API_URL", DEFAULT_API_URL)
        target = PRTarget(repo=pr.repo, number=pr.number or 0, token=token, api_url=api_url)
        comment = post_or_update_comment(target, report.markdown, dry_run=dry_run)
        click.echo(f"[comment] {comment.status.value}"
                   f"{' — ' + comment.url if comment.url else ''}"
                   f"{' (' + comment.detail + ')' if comment.detail else ''}", err=True)

    # 6. Output.
    if as_json:
        data = dict(report.data)
        if comment is not None:
            data["comment"] = {"status": comment.status.value, "url": comment.url,
                               "comment_id": comment.comment_id, "detail": comment.detail}
        click.echo(_json.dumps(data, indent=2))
    else:
        click.echo(report.markdown)


def main() -> None:
    """Console-script entry point (``blastradar``)."""
    cli()


if __name__ == "__main__":
    main()
