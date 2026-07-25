"""Shared test fixtures — the suite runs fully offline on recorded DataHub responses.

Architectural rule 3: the fixtures double as the test suite, and the whole suite
must run green with **no Docker and no network**. To guarantee that, a session-wide
autouse fixture points ``DataHubClient.from_env()`` at the recorded fixtures via
``BLASTRADAR_REPLAY`` — so even a test that forgets and constructs a client the
"live" way gets the offline :class:`ReplayClient` instead of touching the network.

Regenerate the recording with ``make record-fixtures`` against a freshly-seeded
local DataHub when the graph changes (hand-maintained fixtures rot).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from blastradar.datahub.client import DataHubClient
from blastradar.datahub.resolver import Resolver

RECORDING = Path(__file__).resolve().parent / "fixtures" / "recorded" / "datahub_calls.json"


@pytest.fixture(scope="session", autouse=True)
def _force_replay() -> None:
    """Make every from_env() client an offline ReplayClient for the whole session."""
    if not RECORDING.exists():  # pragma: no cover - guard for a misconfigured checkout
        pytest.skip(f"missing recording {RECORDING} — run `make record-fixtures`")
    prev = os.environ.get("BLASTRADAR_REPLAY")
    os.environ["BLASTRADAR_REPLAY"] = str(RECORDING)
    yield
    if prev is None:
        os.environ.pop("BLASTRADAR_REPLAY", None)
    else:
        os.environ["BLASTRADAR_REPLAY"] = prev


@pytest.fixture()
def replay_client() -> DataHubClient:
    """A client that serves DataHub calls from the recorded fixtures (no network)."""
    return DataHubClient.from_env()


@pytest.fixture()
def replay_resolver(replay_client: DataHubClient) -> Resolver:
    return Resolver(replay_client)
