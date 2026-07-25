"""Tests for Phase 1D GitHub integration: post once, update in place, degrade cleanly.

Uses httpx's MockTransport so no network is touched. We assert the create-vs-update
decision keys off the hidden marker, and that missing token / dry-run / API errors
never raise (the PR comment failing must not fail the pipeline).
"""

from __future__ import annotations

import json

import httpx
import pytest

from blastradar.github import (
    COMMENT_MARKER,
    CommentStatus,
    PRTarget,
    ensure_marker,
    post_or_update_comment,
    pr_context_from_env,
)

REPO, NUMBER = "order-entry/analytics", 42
TARGET = PRTarget(repo=REPO, number=NUMBER, token="ghs_faketoken")


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="https://api.github.com")


def test_ensure_marker_prepends_when_missing():
    assert ensure_marker("hello").startswith(COMMENT_MARKER)
    already = f"{COMMENT_MARKER}\nhi"
    assert ensure_marker(already) == already  # not doubled


def test_posts_new_comment_when_none_exists():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])  # no existing comments
        if request.method == "POST":
            seen["body"] = json.loads(request.content)["body"]
            return httpx.Response(201, json={"id": 999, "html_url": "https://gh/c/999"})
        return httpx.Response(500)  # pragma: no cover

    result = post_or_update_comment(TARGET, "the report", http=_mock_client(handler))
    assert result.status is CommentStatus.POSTED
    assert result.comment_id == 999
    assert result.url == "https://gh/c/999"
    assert COMMENT_MARKER in seen["body"]  # marker embedded so next run can find it


def test_updates_existing_marker_comment_in_place():
    calls = {"patched_id": None}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[
                {"id": 1, "body": "someone else's comment"},
                {"id": 7, "body": f"{COMMENT_MARKER}\nold blastradar report"},
            ])
        if request.method == "PATCH":
            assert request.url.path.endswith("/comments/7")  # the marker comment
            calls["patched_id"] = 7
            return httpx.Response(200, json={"id": 7, "html_url": "https://gh/c/7"})
        return httpx.Response(500)  # pragma: no cover — POST must not happen

    result = post_or_update_comment(TARGET, "fresh report", http=_mock_client(handler))
    assert result.status is CommentStatus.UPDATED
    assert result.comment_id == 7
    assert calls["patched_id"] == 7


def test_paginates_to_find_marker_on_second_page():
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        if request.method == "GET" and page == "1":
            return httpx.Response(200, json=[{"id": i, "body": "x"} for i in range(100)])
        if request.method == "GET" and page == "2":
            return httpx.Response(200, json=[{"id": 7, "body": f"{COMMENT_MARKER} here"}])
        if request.method == "PATCH":
            return httpx.Response(200, json={"id": 7, "html_url": "u"})
        return httpx.Response(500)  # pragma: no cover

    result = post_or_update_comment(TARGET, "body", http=_mock_client(handler))
    assert result.status is CommentStatus.UPDATED


def test_dry_run_makes_no_request():
    def handler(request):  # pragma: no cover — must never be called
        raise AssertionError("no HTTP in dry-run")

    result = post_or_update_comment(TARGET, "body", dry_run=True, http=_mock_client(handler))
    assert result.status is CommentStatus.DRY_RUN


def test_missing_token_skips():
    target = PRTarget(repo=REPO, number=NUMBER, token="")
    result = post_or_update_comment(target, "body")
    assert result.status is CommentStatus.SKIPPED
    assert "token" in result.detail


def test_api_error_degrades_to_failed_not_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "rate limited"})

    result = post_or_update_comment(TARGET, "body", http=_mock_client(handler))
    assert result.status is CommentStatus.FAILED
    assert not result.ok


# --------------------------------------------------------------------------- #
# Actions environment → PR context
# --------------------------------------------------------------------------- #
def test_pr_context_from_event_payload(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({
        "pull_request": {"number": 42, "title": "drop customer_since",
                         "head": {"sha": "deadbeef", "ref": "feat/slim-customers"}}}))
    env = {
        "GITHUB_REPOSITORY": "order-entry/analytics",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_EVENT_PATH": str(event),
    }
    ctx = pr_context_from_env(env)
    assert ctx is not None
    assert ctx.repo == "order-entry/analytics"
    assert ctx.number == 42
    assert ctx.sha == "deadbeef"
    assert ctx.branch == "feat/slim-customers"
    assert ctx.url == "https://github.com/order-entry/analytics/pull/42"
    assert ctx.key == "order-entry/analytics#42"


def test_pr_context_none_when_not_a_pr():
    assert pr_context_from_env({"GITHUB_REPOSITORY": "x/y"}) is None
