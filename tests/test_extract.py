"""Tests for diff extraction (Phase 1A): JSON stdin mode and the real git mode."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

from blastradar.diff.extract import ExtractError, extract_from_git, extract_from_json
from blastradar.models import FileStatus


# --------------------------------------------------------------------------- #
# JSON stdin mode
# --------------------------------------------------------------------------- #
def test_json_infers_status_from_content() -> None:
    payload = """[
        {"path": "models/a.sql", "before": "select 1", "after": "select 2"},
        {"path": "models/b.sql", "after": "select 1"},
        {"path": "models/c.sql", "before": "select 1"},
        {"path": "notes.txt", "before": "x", "after": "y"}
    ]"""
    changes = extract_from_json(io.StringIO(payload))
    # notes.txt filtered out by suffix.
    assert [(c.path, c.status) for c in changes] == [
        ("models/a.sql", FileStatus.MODIFIED),
        ("models/b.sql", FileStatus.ADDED),
        ("models/c.sql", FileStatus.DELETED),
    ]
    assert changes[1].before is None
    assert changes[2].after is None


def test_json_explicit_status_wins() -> None:
    payload = '[{"path": "m.sql", "before": "a", "after": "b", "status": "deleted"}]'
    (change,) = extract_from_json(io.StringIO(payload))
    assert change.status is FileStatus.DELETED


def test_json_malformed_raises() -> None:
    with pytest.raises(ExtractError):
        extract_from_json(io.StringIO("{not json"))


def test_json_missing_path_raises() -> None:
    with pytest.raises(ExtractError):
        extract_from_json(io.StringIO('[{"before": "x"}]'))


# --------------------------------------------------------------------------- #
# Git mode (real temp repo)
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A real git repo: base commit, then a commit that adds/deletes/modifies .sql."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    models = tmp_path / "models"
    models.mkdir()
    (models / "keep.sql").write_text("select a, b from t\n")
    (models / "gone.sql").write_text("select x from y\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    # head: modify keep, delete gone, add fresh, add a non-sql file
    (models / "keep.sql").write_text("select a from t\n")
    (models / "gone.sql").unlink()
    (models / "fresh.sql").write_text("select 1 as one\n")
    (tmp_path / "README.md").write_text("hi\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "head")
    return tmp_path


def test_extract_from_git_handles_add_delete_modify(repo: Path) -> None:
    changes = extract_from_git("HEAD~1", "HEAD", repo_dir=str(repo))
    by_path = {c.path: c for c in changes}
    # README.md excluded by suffix.
    assert set(by_path) == {"models/keep.sql", "models/gone.sql", "models/fresh.sql"}

    assert by_path["models/keep.sql"].status is FileStatus.MODIFIED
    assert by_path["models/keep.sql"].before == "select a, b from t\n"
    assert by_path["models/keep.sql"].after == "select a from t\n"

    assert by_path["models/gone.sql"].status is FileStatus.DELETED
    assert by_path["models/gone.sql"].before == "select x from y\n"
    assert by_path["models/gone.sql"].after is None

    assert by_path["models/fresh.sql"].status is FileStatus.ADDED
    assert by_path["models/fresh.sql"].before is None
    assert by_path["models/fresh.sql"].after == "select 1 as one\n"


def test_extract_from_git_bad_ref_raises(repo: Path) -> None:
    with pytest.raises(ExtractError):
        extract_from_git("HEAD", "no-such-ref", repo_dir=str(repo))
