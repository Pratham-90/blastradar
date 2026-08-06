"""Tests for the single LLM narration call: provider selection, parsing, and fallback.

Nothing here touches the network. The two provider functions are monkeypatched (or
``httpx.post`` is, for the request-shape test), so the suite stays offline per
architectural rule 3.

The behaviour that matters most is the **fallback guarantee**: narration must never
raise, because a failed LLM call must not fail the PR review. Every provider error
path below asserts that a usable templated Narration comes back instead.
"""

from __future__ import annotations

import json

import pytest

from blastradar import narrate as narrate_mod
from blastradar.models import (
    ChangeEvent,
    ChangeKind,
    DeploymentDetail,
    ImpactedAsset,
    TrainingEvidence,
)
from blastradar.narrate import (
    ANTHROPIC_DEFAULT_MODEL,
    GROQ_DEFAULT_MODEL,
    Narration,
    _narration_from_json,
    _parse_llm_json,
    narrate,
)
from blastradar.scoring import score_asset


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _model(name, *, deployed=True, trained=True):
    deployments = (
        (DeploymentDetail(
            urn=f"urn:li:mlModelDeployment:(urn:li:dataPlatform:sagemaker,{name}-prod,PROD)",
            status="IN_SERVICE"),)
        if deployed else ()
    )
    return ImpactedAsset(
        urn=f"urn:li:mlModel:(urn:li:dataPlatform:mlflow,{name},PROD)",
        entity_type="mlModel", name=name, deployments=deployments,
        training=TrainingEvidence(trained_on=trained),
    )


def _change():
    return ChangeEvent(kind=ChangeKind.DROP_COLUMN, table="customers", column="customer_since")


def _scored(n=2):
    return [score_asset(_model(f"m{i}")) for i in range(n)]


@pytest.fixture(autouse=True)
def _clear_provider_keys(monkeypatch):
    """No test may depend on a real key that happens to be in the developer's env."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# --------------------------------------------------------------------------- #
# JSON parsing
# --------------------------------------------------------------------------- #
def test_parse_llm_json_plain():
    assert _parse_llm_json('{"a": 1}') == {"a": 1}


def test_parse_llm_json_tolerates_code_fences_and_prose():
    reply = 'Sure!\n```json\n{"change_summary": "x"}\n```\nHope that helps.'
    assert _parse_llm_json(reply) == {"change_summary": "x"}


@pytest.mark.parametrize("bad", ["no json here", "", "}{"])
def test_parse_llm_json_raises_without_an_object(bad):
    with pytest.raises(ValueError):
        _parse_llm_json(bad)


def test_narration_from_json_maps_fields_and_drops_malformed_entries():
    data = {
        "change_summary": "  summary  ",
        "migration": "  do it safely  ",
        "explanations": [
            {"id": "a1", "text": "first"},
            {"id": "a2"},              # missing text -> dropped
            {"text": "no id"},         # missing id   -> dropped
            "not-a-dict",              # wrong type   -> dropped
        ],
    }
    n = _narration_from_json(data, model="some-model")
    assert n.used_llm is True
    assert n.model == "some-model"
    assert n.change_summary == "summary"      # stripped
    assert n.migration == "do it safely"      # stripped
    assert n.explanations == {"a1": "first"}  # only the well-formed entry survives


# --------------------------------------------------------------------------- #
# Provider selection
# --------------------------------------------------------------------------- #
def _record_provider(monkeypatch, name):
    """Replace one provider fn with a recorder that returns a minimal Narration."""
    calls = {}

    def _fake(change, scored, *, model):
        calls["model"] = model
        return Narration(
            change_summary="s", migration="m",
            explanations={narrate_mod.asset_id(i): "e" for i in range(len(scored))},
            used_llm=True, model=model,
        )

    monkeypatch.setattr(narrate_mod, name, _fake)
    return calls


def test_groq_is_used_when_its_key_is_set(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    groq = _record_provider(monkeypatch, "_narrate_with_groq")
    monkeypatch.setattr(narrate_mod, "_narrate_with_anthropic", _boom)

    n = narrate(_change(), _scored(), use_llm=True)

    assert n.used_llm is True
    assert groq["model"] == GROQ_DEFAULT_MODEL


def test_anthropic_is_used_when_only_its_key_is_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    anthropic = _record_provider(monkeypatch, "_narrate_with_anthropic")
    monkeypatch.setattr(narrate_mod, "_narrate_with_groq", _boom)

    n = narrate(_change(), _scored(), use_llm=True)

    assert n.used_llm is True
    assert anthropic["model"] == ANTHROPIC_DEFAULT_MODEL


def test_groq_wins_when_both_keys_are_set(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    groq = _record_provider(monkeypatch, "_narrate_with_groq")
    monkeypatch.setattr(narrate_mod, "_narrate_with_anthropic", _boom)

    narrate(_change(), _scored(), use_llm=True)

    assert groq["model"] == GROQ_DEFAULT_MODEL


def test_explicit_model_overrides_the_provider_default(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    groq = _record_provider(monkeypatch, "_narrate_with_groq")

    narrate(_change(), _scored(), use_llm=True, model="pinned-model")

    assert groq["model"] == "pinned-model"


def _boom(*_a, **_k):  # pragma: no cover - only called if provider selection is wrong
    raise AssertionError("the wrong provider was selected")


# --------------------------------------------------------------------------- #
# The fallback guarantee — narration must never raise
# --------------------------------------------------------------------------- #
def test_use_llm_false_returns_templated_narration():
    n = narrate(_change(), _scored(1), use_llm=False)
    assert n.used_llm is False
    assert n.model is None
    assert n.change_summary and n.migration
    assert set(n.explanations) == {"a1"}


@pytest.mark.parametrize("exc", [RuntimeError("api down"), ValueError("bad json")])
def test_provider_failure_falls_back_to_template(monkeypatch, exc):
    monkeypatch.setenv("GROQ_API_KEY", "g")

    def _fail(*_a, **_k):
        raise exc

    monkeypatch.setattr(narrate_mod, "_narrate_with_groq", _fail)

    n = narrate(_change(), _scored(2), use_llm=True)

    assert n.used_llm is False                       # degraded, not crashed
    assert type(exc).__name__ in n.note              # the reason is surfaced
    assert set(n.explanations) == {"a1", "a2"}       # still one per scored asset
    assert n.change_summary and n.migration


def test_missing_groq_key_inside_provider_still_falls_back(monkeypatch):
    """_narrate_with_groq reads os.environ['GROQ_API_KEY']; a race/unset must not crash."""
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)  # provider selection sees no key
    n = narrate(_change(), _scored(1), use_llm=True)
    # With no key at all, no provider is reachable and the template must carry the run.
    assert n.explanations


def test_partial_explanations_are_filled_from_the_template(monkeypatch):
    """A model that skips an asset must not leave a hole in the report."""
    monkeypatch.setenv("GROQ_API_KEY", "g")

    def _partial(change, scored, *, model):
        return Narration(change_summary="only a1 covered", explanations={"a1": "llm text"},
                         migration="llm migration", used_llm=True, model=model)

    monkeypatch.setattr(narrate_mod, "_narrate_with_groq", _partial)

    n = narrate(_change(), _scored(3), use_llm=True)

    assert n.used_llm is True
    assert set(n.explanations) == {"a1", "a2", "a3"}   # gaps filled
    assert n.explanations["a1"] == "llm text"          # the model's text is preserved
    assert n.explanations["a2"]                        # template filled the rest
    assert "template" in n.note


# --------------------------------------------------------------------------- #
# Groq request shape (offline — httpx.post is monkeypatched)
# --------------------------------------------------------------------------- #
def test_groq_request_shape(monkeypatch):
    import httpx

    monkeypatch.setenv("GROQ_API_KEY", "secret-key")
    sent = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "change_summary": "s", "migration": "m",
                "explanations": [{"id": "a1", "text": "t"}],
            })}}]}

    def _fake_post(url, **kwargs):
        sent["url"] = url
        sent.update(kwargs)
        return _Resp()

    monkeypatch.setattr(httpx, "post", _fake_post)

    n = narrate(_change(), _scored(1), use_llm=True)

    assert n.used_llm is True
    assert n.model == GROQ_DEFAULT_MODEL
    assert sent["url"].endswith("/chat/completions")
    assert sent["headers"]["Authorization"] == "Bearer secret-key"
    body = sent["json"]
    assert body["model"] == GROQ_DEFAULT_MODEL
    assert body["temperature"] == 0                              # deterministic narration
    assert body["response_format"] == {"type": "json_object"}    # JSON mode
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
