"""Diff extraction: recover the before/after content of changed ``.sql`` files.

Two input modes (both yield ``list[SqlFileChange]``):

  * ``extract_from_git(base_ref, head_ref)`` — the real path. Uses ``git diff
    --name-status`` to list changed files and ``git show <ref>:<path>`` to pull full
    before/after content. Handles added, deleted, and modified files.
  * ``extract_from_json(stream)`` — a trivial, unambiguous mode for tests / piping:
    a JSON array of ``{"path", "before"?, "after"?}`` objects on stdin. Status is
    inferred from which of before/after is present (or given explicitly).

This module does not interpret SQL — it only produces the pairs the SQL delta
analyzer consumes.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Sequence
from typing import IO

from blastradar.models import FileStatus, SqlFileChange

logger = logging.getLogger(__name__)

DEFAULT_SUFFIXES: tuple[str, ...] = (".sql",)

# git --name-status single-char codes we map to a FileStatus.
_STATUS_MAP = {"A": FileStatus.ADDED, "D": FileStatus.DELETED,
               "M": FileStatus.MODIFIED, "T": FileStatus.MODIFIED}


class ExtractError(Exception):
    """Raised when git extraction fails (bad repo, bad ref, git error). Loud by design."""


def _run_git(args: Sequence[str], repo_dir: str) -> str:
    """Run a git command in ``repo_dir`` and return stdout, raising on failure."""
    cmd = ["git", "-C", repo_dir, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError as e:
        raise ExtractError("git executable not found on PATH") from e
    except subprocess.CalledProcessError as e:
        raise ExtractError(
            f"git {' '.join(args)} failed (exit {e.returncode}): {e.stderr.strip()}"
        ) from e
    return proc.stdout


def _git_show(ref: str, path: str, repo_dir: str) -> str:
    """Return the full content of ``path`` at ``ref`` (``git show ref:path``)."""
    return _run_git(["show", f"{ref}:{path}"], repo_dir)


def _has_suffix(path: str, suffixes: Sequence[str]) -> bool:
    return any(path.lower().endswith(s.lower()) for s in suffixes)


def extract_from_git(
    base_ref: str,
    head_ref: str,
    *,
    repo_dir: str = ".",
    suffixes: Sequence[str] = DEFAULT_SUFFIXES,
) -> list[SqlFileChange]:
    """Return the before/after content of every changed matching file between two refs.

    Assumes ``repo_dir`` is a git work tree and both refs resolve. Renames are split
    into delete+add (``--no-renames``) so callers only ever see ADDED / DELETED /
    MODIFIED. Non-matching suffixes are skipped.

    Raises :class:`ExtractError` on any git failure.
    """
    out = _run_git(
        ["diff", "--name-status", "--no-renames", base_ref, head_ref], repo_dir
    )
    changes: list[SqlFileChange] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code, path = parts[0].strip(), parts[-1].strip()
        status = _STATUS_MAP.get(code[0]) if code else None
        if status is None:
            logger.debug("skipping unhandled git status %r for %s", code, path)
            continue
        if not _has_suffix(path, suffixes):
            continue
        before = None if status is FileStatus.ADDED else _git_show(base_ref, path, repo_dir)
        after = None if status is FileStatus.DELETED else _git_show(head_ref, path, repo_dir)
        changes.append(SqlFileChange(path=path, status=status, before=before, after=after))
    return changes


def _status_from_content(before: str | None, after: str | None) -> FileStatus:
    """Infer a FileStatus from which of before/after is present."""
    if before is None and after is not None:
        return FileStatus.ADDED
    if before is not None and after is None:
        return FileStatus.DELETED
    return FileStatus.MODIFIED


def extract_from_json(
    stream: IO[str] | None = None,
    *,
    suffixes: Sequence[str] = DEFAULT_SUFFIXES,
) -> list[SqlFileChange]:
    """Read changes from a JSON array on ``stream`` (default stdin).

    Each element is ``{"path": str, "before": str|null, "after": str|null,
    "status"?: "added"|"deleted"|"modified"}``. When ``status`` is omitted it is
    inferred from which of before/after is present. Non-matching suffixes are skipped.

    Raises :class:`ExtractError` on malformed JSON or missing ``path``.
    """
    stream = stream if stream is not None else sys.stdin
    try:
        payload = json.load(stream)
    except json.JSONDecodeError as e:
        raise ExtractError(f"invalid JSON on input: {e}") from e
    if not isinstance(payload, list):
        raise ExtractError("expected a JSON array of file-change objects")

    changes: list[SqlFileChange] = []
    for i, item in enumerate(payload):
        if not isinstance(item, dict) or "path" not in item:
            raise ExtractError(f"item {i}: expected an object with a 'path' key")
        path = item["path"]
        before, after = item.get("before"), item.get("after")
        if "status" in item:
            try:
                status = FileStatus(item["status"])
            except ValueError as e:
                raise ExtractError(f"item {i}: invalid status {item['status']!r}") from e
        else:
            status = _status_from_content(before, after)
        if not _has_suffix(path, suffixes):
            continue
        changes.append(SqlFileChange(path=path, status=status, before=before, after=after))
    return changes
