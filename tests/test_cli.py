"""Smoke tests for the `blastradar` CLI (click entry point).

These run the real command end-to-end against the recorded fixtures — the session
autouse fixture in ``conftest`` points ``DataHubClient.from_env()`` at the recording,
so no DataHub, network, or API key is involved (architectural rule 3).

They cover the wiring the unit tests can't: option parsing, the diff→report path,
`--json` output, and that argument mistakes fail loudly instead of producing a
false all-clear.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from blastradar.cli import cli

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_PR = REPO_ROOT / "demo-repo" / "demo-pr.json"


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _analyze(runner, *extra):
    """Run `analyze` on the demo changeset, offline and side-effect free."""
    return runner.invoke(cli, [
        "analyze",
        "--changes", str(DEMO_PR),
        "--pr-repo", "order-entry/analytics",
        "--pr-number", "42",
        "--dry-run",            # no LLM, no real write-back
        "--no-post-comment",    # never touch GitHub
        *extra,
    ])


# --------------------------------------------------------------------------- #
# Help / discoverability
# --------------------------------------------------------------------------- #
def test_group_help_lists_analyze(runner):
    res = runner.invoke(cli, ["--help"])
    assert res.exit_code == 0
    assert "analyze" in res.output


def test_analyze_help_documents_the_key_gotcha_options(runner):
    res = runner.invoke(cli, ["analyze", "--help"])
    assert res.exit_code == 0
    for opt in ("--changes", "--dry-run", "--no-llm", "--write-back", "--post-comment"):
        assert opt in res.output


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #
def test_analyze_demo_pr_reports_the_blast_radius(runner):
    res = _analyze(runner)
    assert res.exit_code == 0, res.output
    out = res.output
    assert "ML blast radius" in out
    assert "churn_model_v3" in out                     # the critical, trained-on model
    assert "trained on the changed column" in out      # the differentiator line
    assert "customer_since" in out


def test_analyze_json_output_is_valid_and_structured(runner):
    res = _analyze(runner, "--json")
    assert res.exit_code == 0, res.output
    # stdout must be pure JSON — diagnostics belong on stderr so `--json | jq` works.
    data = json.loads(res.stdout)
    assert isinstance(data, dict)
    impacts = data["impacts"]
    assert impacts, f"expected impacts in JSON payload, got keys={sorted(data)}"
    # Severity must be present and drawn from the documented scale.
    severities = {str(i["severity"]).lower() for i in impacts}
    assert severities <= {"critical", "high", "medium", "low"}
    # The trained-vs-inference distinction is the product's core claim: keep it in the API.
    assert any(i["trained_on"] for i in impacts)
    assert all("severity" in i and "reasons" in i for i in impacts)


def test_dry_run_banner_goes_to_stderr_not_stdout(runner):
    """The banner must never land in stdout, or it corrupts `--json` for piping."""
    res = _analyze(runner, "--json")
    assert "[dry-run]" in res.stderr
    assert "[dry-run]" not in res.stdout


def test_no_llm_flag_is_accepted_and_still_reports(runner):
    res = _analyze(runner, "--no-llm")
    assert res.exit_code == 0, res.output
    assert "ML blast radius" in res.output


# --------------------------------------------------------------------------- #
# Argument errors must fail loudly (never a silent all-clear)
# --------------------------------------------------------------------------- #
def test_missing_changes_and_refs_is_a_usage_error(runner):
    res = runner.invoke(cli, ["analyze", "--no-post-comment", "--dry-run"])
    assert res.exit_code != 0
    assert "either --changes FILE or both --base and --head" in res.output


def test_nonexistent_changes_file_is_rejected(runner):
    res = runner.invoke(cli, ["analyze", "--changes", "does-not-exist.json"])
    assert res.exit_code != 0
    assert "does-not-exist.json" in res.output
