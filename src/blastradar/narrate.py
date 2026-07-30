"""LLM narration — the ONE place Blastradar calls an LLM (architectural rule 1).

Called exactly once per run, at the very end, given the fully-scored impact list.
The model writes prose and a suggested migration only; it never adds, removes, or
re-ranks impacts (the system prompt in ``prompts/narrate.md`` says so explicitly,
and ``report.py`` slots the prose into a deterministic template keyed by asset id,
so the model *structurally cannot* change the impact set).

If no API is available or the call fails, we fall back to a fully-templated
narration — the tool must still produce a useful comment with no LLM at all, so a
judge without an API key still sees it work.

Model is pinned to ``claude-opus-4-8``. ``temperature`` was removed on that model
(sending it is a 400), so low-variance narration is requested via
``output_config={"effort": "low"}`` plus no extended thinking. Verified against
docs/API-NOTES (Anthropic SDK section).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from blastradar.datahub.urns import short_name, simple_name
from blastradar.models import ChangeEvent, ScoredImpact

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"
MAX_TOKENS = 1500
_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "narrate.md"

# Optional Groq (OpenAI-compatible) provider. Selected at runtime when GROQ_API_KEY
# is set; otherwise the Anthropic path (``MODEL``) is used. The deterministic core is
# untouched — this only swaps which service writes the prose (architectural rule 1).
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


@dataclass(frozen=True)
class Narration:
    """Prose slots for the report. ``explanations`` is keyed by asset id (a1, a2, …)."""

    change_summary: str
    explanations: dict[str, str] = field(default_factory=dict)
    migration: str = ""
    used_llm: bool = False
    model: str | None = None
    note: str = ""   # e.g. why the LLM path was skipped or fell back


def asset_id(index: int) -> str:
    """Stable id used to key prose to a scored asset (order is deterministic)."""
    return f"a{index + 1}"


def _path_names(change: ChangeEvent, scored: ScoredImpact) -> list[str]:
    names = [f"{change.table}.{change.column}"]
    if scored.asset.paths:
        names.extend(short_name(h.to_urn) for h in scored.asset.paths[0].hops)
    return names


def _payload(change: ChangeEvent, scored: list[ScoredImpact]) -> dict:
    return {
        "change": {
            "kind": change.kind.value, "table": change.table,
            "column": change.column, "new_column": change.new_column,
        },
        "impacts": [
            {
                "id": asset_id(i),
                "model": s.asset.name,
                "severity": s.severity.value,
                "deployed": s.deployed,
                "trained_on": s.trained_on,
                "deployments": [short_name(d.urn) for d in s.asset.deployments],
                "owner": ", ".join(simple_name(o) for o in s.asset.owners) or None,
                "tags": [simple_name(t) for t in s.asset.tags],
                "path": _path_names(change, s),
                "reasons": list(s.reasons),
            }
            for i, s in enumerate(scored)
        ],
    }


# --------------------------------------------------------------------------- #
# Templated fallback (no LLM)
# --------------------------------------------------------------------------- #
def _template_narration(
    change: ChangeEvent, scored: list[ScoredImpact], *, note: str = "",
) -> Narration:
    col = f"{change.table}.{change.column}"
    verb = {"DROP_COLUMN": "drops", "RENAME_COLUMN": "renames",
            "TYPE_CHANGE": "changes the type of", "DROP_TABLE": "drops the table for"}.get(
        change.kind.value, "changes")
    summary = (
        f"This PR {verb} `{col}`, which feeds {len(scored)} downstream ML "
        f"model(s) — the change will not raise an error, so the impact is silent."
    )
    explanations: dict[str, str] = {}
    for i, s in enumerate(scored):
        rel = ("was trained on this column" if s.trained_on
               else "reads this column at inference time")
        depl = ("is currently deployed and serving predictions" if s.deployed
                else "is not currently deployed")
        explanations[asset_id(i)] = (
            f"`{s.asset.name}` {rel} and {depl}. Dropping or renaming the column "
            f"does not fail the pipeline; the feature silently emits nulls or stale "
            f"values, so predictions degrade without any error surfacing."
        )
    migration = (
        f"Avoid an in-place change to `{col}`. Prefer a deprecate-then-drop: add the "
        f"replacement column alongside the old one, backfill it, migrate every "
        f"downstream feature and training pipeline, verify the feature store, then "
        f"remove `{change.column}` in a follow-up PR. Coordinate with the owning "
        f"team(s) before merging."
    )
    return Narration(change_summary=summary, explanations=explanations,
                     migration=migration, used_llm=False, model=None, note=note)


# --------------------------------------------------------------------------- #
# LLM path
# --------------------------------------------------------------------------- #
def _parse_llm_json(text: str) -> dict:
    """Extract the JSON object from the model's reply (tolerates code fences)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in model reply")
    return json.loads(text[start : end + 1])


def _narration_from_json(data: dict, *, model: str) -> Narration:
    """Map a parsed model reply into a :class:`Narration` (shared by all providers)."""
    explanations = {
        e["id"]: e["text"] for e in data.get("explanations", [])
        if isinstance(e, dict) and "id" in e and "text" in e
    }
    return Narration(
        change_summary=str(data.get("change_summary", "")).strip(),
        explanations=explanations,
        migration=str(data.get("migration", "")).strip(),
        used_llm=True, model=model,
    )


def _narrate_with_groq(
    change: ChangeEvent, scored: list[ScoredImpact], *, model: str,
) -> Narration:
    """Narrate via Groq's OpenAI-compatible chat API (httpx — no extra dependency)."""
    import httpx  # lazy — only when the Groq path is actually taken

    api_key = os.environ["GROQ_API_KEY"]
    system_prompt = _PROMPT_PATH.read_text()
    payload = json.dumps(_payload(change, scored), indent=2)

    resp = httpx.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "max_tokens": MAX_TOKENS,
            "temperature": 0,  # low-variance narration; judges re-run and expect stability
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload},
            ],
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return _narration_from_json(_parse_llm_json(text), model=model)


def _narrate_with_llm(
    change: ChangeEvent, scored: list[ScoredImpact], *, model: str,
) -> Narration:
    import anthropic  # lazy — only when the LLM path is actually taken

    system_prompt = _PROMPT_PATH.read_text()
    payload = json.dumps(_payload(change, scored), indent=2)

    client = anthropic.Anthropic()  # resolves ANTHROPIC_API_KEY / auth profile
    resp = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        output_config={"effort": "low"},   # low-variance (temperature removed on Opus 4.8)
        messages=[{"role": "user", "content": payload}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return _narration_from_json(_parse_llm_json(text), model=model)


def narrate(
    change: ChangeEvent,
    scored: list[ScoredImpact],
    *,
    use_llm: bool = True,
    model: str = MODEL,
) -> Narration:
    """Produce narration prose for the report. The single LLM call of the pipeline.

    With ``use_llm=False`` (or on any API/parse failure) returns a fully-templated
    narration so the tool still produces a useful comment with no LLM available.
    """
    if not use_llm:
        return _template_narration(change, scored, note="LLM disabled (--no-llm/--dry-run)")
    # Provider select: Groq (OpenAI-compatible) when GROQ_API_KEY is set, else Anthropic.
    use_groq = bool(os.environ.get("GROQ_API_KEY"))
    if use_groq and model == MODEL:  # caller didn't pin an Anthropic model → use Groq default
        model = GROQ_DEFAULT_MODEL
    try:
        narration = (
            _narrate_with_groq(change, scored, model=model) if use_groq
            else _narrate_with_llm(change, scored, model=model)
        )
        # If the model skipped any asset, fill the gaps from the template.
        if narration.explanations.keys() != {asset_id(i) for i in range(len(scored))}:
            tmpl = _template_narration(change, scored)
            merged = {**tmpl.explanations, **narration.explanations}
            narration = Narration(
                change_summary=narration.change_summary or tmpl.change_summary,
                explanations=merged,
                migration=narration.migration or tmpl.migration,
                used_llm=True, model=model,
                note="some explanations filled from template",
            )
        logger.info("narration produced by %s", model)
        return narration
    except Exception as e:  # noqa: BLE001 — must never crash the pipeline; fall back
        logger.warning("LLM narration failed (%s: %s); using templated fallback",
                       type(e).__name__, e)
        return _template_narration(
            change, scored, note=f"LLM unavailable ({type(e).__name__}); templated fallback")
