"""Post the Blastradar report as a pull-request comment — update in place, never spam.

On the first run we create one comment carrying a hidden marker
(:data:`COMMENT_MARKER`). On every later run we find that comment by its marker and
**edit it in place** (PATCH) instead of posting a new one, so a PR that is pushed to
ten times still shows exactly one Blastradar comment, always current.

Talks to the GitHub REST API over ``httpx`` (a project dependency). It degrades
rather than failing the build: with no token, no PR number, or ``--dry-run`` it
returns a result describing what it *would* post and writes nothing — the caller has
already printed the report to the log regardless.

In GitHub Actions the caller passes the repo/number/token via :class:`PRTarget`;
:func:`pr_context_from_env` reconstructs the richer :class:`PRContext` (used for
write-back links) from the standard Actions environment.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum

from blastradar.models import PRContext

logger = logging.getLogger(__name__)

# Hidden HTML comment that identifies our comment for in-place updates.
COMMENT_MARKER = "<!-- blastradar:comment -->"

DEFAULT_API_URL = "https://api.github.com"
_API_VERSION = "2022-11-28"


class GitHubError(Exception):
    """A GitHub API call failed (non-2xx, network error, or bad response)."""


class CommentStatus(str, Enum):
    POSTED = "posted"       # new comment created
    UPDATED = "updated"     # existing marker comment edited in place
    DRY_RUN = "dry-run"     # --dry-run: would post, did not
    SKIPPED = "skipped"     # no token / no PR context: cannot post
    FAILED = "failed"       # attempted, errored (caller still succeeds)


@dataclass(frozen=True)
class PRTarget:
    """Where to post: a repo, an issue/PR number, and a token to authenticate."""

    repo: str                       # "owner/name"
    number: int
    token: str = ""
    api_url: str = DEFAULT_API_URL

    @property
    def can_post(self) -> bool:
        return bool(self.repo and self.number and self.token)


@dataclass(frozen=True)
class CommentResult:
    status: CommentStatus
    url: str = ""
    comment_id: int | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status is not CommentStatus.FAILED


def ensure_marker(body: str) -> str:
    """Guarantee the hidden marker is present (prepended) so re-runs can find the comment."""
    return body if COMMENT_MARKER in body else f"{COMMENT_MARKER}\n{body}"


# --------------------------------------------------------------------------- #
# HTTP plumbing (httpx client is injectable for tests)
# --------------------------------------------------------------------------- #
def _client(target: PRTarget, http=None):
    import httpx  # lazy: only when actually posting

    if http is not None:
        return http
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _API_VERSION,
        "Authorization": f"Bearer {target.token}",
    }
    return httpx.Client(base_url=target.api_url, headers=headers, timeout=15.0)


def _find_marker_comment(http, target: PRTarget) -> dict | None:
    """Return the first existing comment containing our marker, else None (paginated)."""
    path = f"/repos/{target.repo}/issues/{target.number}/comments"
    params = {"per_page": 100, "page": 1}
    for _ in range(20):  # hard page cap — safety, not expected to hit
        resp = http.get(path, params=params)
        if resp.status_code >= 300:
            raise GitHubError(f"listing comments failed ({resp.status_code}): {resp.text}")
        batch = resp.json()
        for comment in batch:
            if COMMENT_MARKER in (comment.get("body") or ""):
                return comment
        if len(batch) < params["per_page"]:
            return None
        params["page"] += 1
    return None


def post_or_update_comment(
    target: PRTarget,
    body: str,
    *,
    dry_run: bool = False,
    http=None,
) -> CommentResult:
    """Create or update the Blastradar PR comment. Never raises — degrades to a result.

    ``http`` is an optional pre-built ``httpx.Client`` (tests inject one backed by a
    mock transport). With ``dry_run`` or an un-postable ``target`` no request is made.
    """
    body = ensure_marker(body)

    if dry_run:
        logger.info("github: --dry-run, not posting to %s#%s", target.repo, target.number)
        return CommentResult(CommentStatus.DRY_RUN,
                             detail=f"would post to {target.repo}#{target.number}")
    if not target.can_post:
        missing = "token" if not target.token else "repo/number"
        logger.warning("github: cannot post (missing %s) — comment not sent", missing)
        return CommentResult(CommentStatus.SKIPPED, detail=f"missing {missing}")

    http = _client(target, http)
    try:
        existing = _find_marker_comment(http, target)
        if existing is not None:
            cid = existing["id"]
            resp = http.patch(f"/repos/{target.repo}/issues/comments/{cid}",
                              json={"body": body})
            if resp.status_code >= 300:
                raise GitHubError(f"update failed ({resp.status_code}): {resp.text}")
            data = resp.json()
            logger.info("github: updated comment %s on %s#%s", cid, target.repo, target.number)
            return CommentResult(CommentStatus.UPDATED, url=data.get("html_url", ""),
                                 comment_id=cid, detail="edited existing comment in place")
        resp = http.post(f"/repos/{target.repo}/issues/{target.number}/comments",
                         json={"body": body})
        if resp.status_code >= 300:
            raise GitHubError(f"create failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        logger.info("github: posted new comment on %s#%s", target.repo, target.number)
        return CommentResult(CommentStatus.POSTED, url=data.get("html_url", ""),
                             comment_id=data.get("id"), detail="posted new comment")
    except Exception as e:  # noqa: BLE001 — a failed comment must not fail the run
        logger.warning("github: post/update failed: %s: %s", type(e).__name__, e)
        return CommentResult(CommentStatus.FAILED, detail=f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Environment → PR context (GitHub Actions)
# --------------------------------------------------------------------------- #
def pr_context_from_env(env: dict[str, str] | None = None) -> PRContext | None:
    """Build a :class:`PRContext` from GitHub Actions env vars, or None if not a PR run.

    Reads ``GITHUB_REPOSITORY``, ``GITHUB_SERVER_URL`` and the event payload at
    ``GITHUB_EVENT_PATH`` (``pull_request.number/head.sha/title``). Returns None when
    the number cannot be determined (e.g. a non-PR trigger), so the caller can fall
    back to CLI flags.
    """
    env = env if env is not None else dict(os.environ)
    repo = env.get("GITHUB_REPOSITORY", "")
    server = env.get("GITHUB_SERVER_URL", "https://github.com")

    number: int | None = None
    sha = env.get("GITHUB_SHA", "")
    title = ""
    branch = env.get("GITHUB_HEAD_REF", "")
    event_path = env.get("GITHUB_EVENT_PATH", "")
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, encoding="utf-8") as fh:
                payload = json.load(fh)
            pr = payload.get("pull_request") or {}
            number = pr.get("number") or payload.get("number")
            sha = (pr.get("head") or {}).get("sha") or sha
            title = pr.get("title") or ""
            branch = (pr.get("head") or {}).get("ref") or branch
        except (OSError, json.JSONDecodeError, AttributeError) as e:
            logger.debug("could not parse GITHUB_EVENT_PATH: %s", e)

    if number is None:
        return None
    url = f"{server}/{repo}/pull/{number}" if repo else ""
    return PRContext(repo=repo, number=int(number), url=url, sha=sha,
                     title=title, branch=branch)


def target_from_env(env: dict[str, str] | None = None) -> PRTarget | None:
    """Build a :class:`PRTarget` (repo/number/token) from Actions env, or None."""
    env = env if env is not None else dict(os.environ)
    ctx = pr_context_from_env(env)
    if ctx is None or not ctx.repo or ctx.number is None:
        return None
    token = env.get("GITHUB_TOKEN", "")
    api_url = env.get("GITHUB_API_URL", DEFAULT_API_URL)
    return PRTarget(repo=ctx.repo, number=ctx.number, token=token, api_url=api_url)


__all__ = [
    "COMMENT_MARKER",
    "GitHubError",
    "CommentStatus",
    "PRTarget",
    "CommentResult",
    "ensure_marker",
    "post_or_update_comment",
    "pr_context_from_env",
    "target_from_env",
]
