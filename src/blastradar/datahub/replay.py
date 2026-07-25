"""Record and replay DataHub calls so the pipeline runs with no network (Phase 2).

Architectural rule 3 (two reproduction paths) rests on this module. Every read the
pipeline makes goes through :class:`~blastradar.datahub.client.DataHubClient._call`,
which already returns plain JSON-able structures and invokes an optional
``observer`` after each call. Phase 2 plugs into that hook from both ends:

  * **Record** — :class:`Recorder` is an observer that captures every
    ``(method, kwargs, result)`` and writes them to a fixture file. Wire it into a
    live client (``DataHubClient.from_env(observer=recorder)``), run the pipeline,
    and save. See ``scripts/record_fixtures.py``.
  * **Replay** — :class:`ReplayClient` is a drop-in ``DataHubClient`` that never
    connects. It overrides ``_call`` to serve the recorded result for a call's
    *signature* — ``(method, canonicalised kwargs)`` — instead of hitting the SDK.

Selection is by **request signature, not call order** (order-dependent replay is
brittle: a refactor that reorders two independent reads would break it). A call
whose signature was never recorded raises :class:`ReplayMiss` loudly, naming the
call and pointing at ``make record-fixtures`` — a missing fixture must never look
like an empty "all-clear" result.

Because every recorded read is idempotent (the same ``(method, kwargs)`` always
returns the same value against a static DataHub), signatures deduplicate cleanly
and the recording is a plain signature→result map.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from blastradar.datahub.client import DataHubClient

logger = logging.getLogger(__name__)

REPLAY_ENV = "BLASTRADAR_REPLAY"  # set to a recording path -> from_env() replays it


def call_signature(method: str, kwargs: dict[str, Any]) -> str:
    """Canonical signature for one client call: method + order-independent kwargs.

    ``kwargs`` are the identifying arguments each client method passes to ``_call``
    (all JSON-able: str / int / list[str]). Keys are sorted so the signature is
    independent of argument order, and the whole thing is a single string so it can
    key a dict and round-trip through JSON.
    """
    canon = json.dumps(kwargs, sort_keys=True, ensure_ascii=False, default=str)
    return f"{method}::{canon}"


class ReplayMiss(Exception):
    """A replayed call had no recorded fixture — loud by design (never a silent miss)."""

    def __init__(self, method: str, kwargs: dict[str, Any], source: str) -> None:
        self.method = method
        self.kwargs = kwargs
        super().__init__(
            f"no recorded fixture for {method}({kwargs}) in '{source}'. "
            f"The recording is stale or incomplete — regenerate it with "
            f"`make record-fixtures` (needs a live DataHub)."
        )


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #
class Recorder:
    """A :class:`CallObserver` that captures client calls for later replay.

    Deduplicates by signature (idempotent reads recur across a run). Attach with
    ``DataHubClient.from_env(observer=recorder)``, drive the pipeline, then
    :meth:`save`.
    """

    def __init__(self) -> None:
        self._by_sig: dict[str, dict[str, Any]] = {}

    def __call__(self, method: str, kwargs: dict[str, Any], result: Any) -> None:
        sig = call_signature(method, kwargs)
        # Last write wins; identical for a static instance, so order is irrelevant.
        self._by_sig[sig] = {"method": method, "kwargs": kwargs, "result": result}

    def __len__(self) -> int:
        return len(self._by_sig)

    def calls(self) -> list[dict[str, Any]]:
        """Recorded calls, sorted by (method, signature) for stable diffs."""
        return sorted(self._by_sig.values(),
                      key=lambda c: (c["method"], call_signature(c["method"], c["kwargs"])))

    def to_document(self, *, description: str = "") -> dict[str, Any]:
        return {
            "_meta": {
                "description": description or "Recorded DataHub responses (Phase 2 fixtures).",
                "generator": "scripts/record_fixtures.py",
                "call_count": len(self._by_sig),
            },
            "calls": self.calls(),
        }

    def save(self, path: Path, *, description: str = "") -> int:
        """Write the recording to ``path`` (pretty JSON). Returns the call count."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_document(description=description), indent=2) + "\n")
        logger.info("recorded %d DataHub call(s) -> %s", len(self._by_sig), path)
        return len(self._by_sig)


def load_recording(path: Path) -> dict[str, Any]:
    """Load a recording file into a signature→result map."""
    doc = json.loads(Path(path).read_text())
    calls = doc["calls"] if isinstance(doc, dict) and "calls" in doc else doc
    mapping: dict[str, Any] = {}
    for entry in calls:
        sig = call_signature(entry["method"], entry["kwargs"])
        mapping[sig] = entry["result"]
    return mapping


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #
class ReplayClient(DataHubClient):
    """A ``DataHubClient`` that serves recorded fixtures instead of the network.

    It inherits every read/write method verbatim; only ``_call`` (the single point
    all of them funnel through) is overridden to look the result up by signature.
    ``_ensure`` is a no-op, so no SDK/connection is ever created. This is the whole
    of the offline ``make demo`` / test path.
    """

    def __init__(self, recording: dict[str, Any], *, source: str = "<memory>", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._recording = recording
        self._source = source
        self.hits = 0

    @classmethod
    def from_file(cls, path: str | Path, **kwargs: Any) -> ReplayClient:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"recording not found: {p}. Generate it with `make record-fixtures` "
                f"(needs a live DataHub), or run `make demo-live` for the live path."
            )
        return cls(load_recording(p), source=str(p), **kwargs)

    def _ensure(self) -> None:  # never connect in replay
        return

    def _call(self, method: str, fn: Any, **kwargs: Any) -> Any:  # noqa: ARG002 - fn unused
        sig = call_signature(method, kwargs)
        try:
            result = self._recording[sig]
        except KeyError:
            raise ReplayMiss(method, kwargs, self._source) from None
        self.hits += 1
        logger.debug("replay %s args=%s (hit %d)", method, kwargs, self.hits)
        return result
