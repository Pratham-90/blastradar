"""Shared connection helpers for the Phase 0 scripts.

Reads DataHub connection settings from a gitignored `.env` at the repo root
(never hardcode the token). Expected keys:

    DATAHUB_GMS_URL=http://localhost:8080
    DATAHUB_GMS_TOKEN=<personal access token>

No third-party dotenv dependency — we parse `.env` ourselves so the Phase 0
scripts stay runnable on a bare `acryl-datahub` install.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"

URL_KEYS = ("DATAHUB_GMS_URL", "DATAHUB_GMS_HOST", "DATAHUB_SERVER")
TOKEN_KEYS = ("DATAHUB_GMS_TOKEN", "DATAHUB_TOKEN")
DEFAULT_URL = "http://localhost:8080"


def load_dotenv(path: Path = ENV_PATH) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file into os.environ (does not overwrite)."""
    values: dict[str, str] = {}
    if not path.exists():
        logger.warning(".env not found at %s — relying on process environment", path)
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        values[key] = val
        os.environ.setdefault(key, val)
    return values


def _first(keys: tuple[str, ...], default: str | None = None) -> str | None:
    for k in keys:
        if os.environ.get(k):
            return os.environ[k]
    return default


def connection_settings() -> tuple[str, str | None]:
    """Return (server_url, token).

    A token is optional: `datahub docker quickstart` runs with metadata auth
    disabled, so tokenless connections work locally. If a token is present in
    `.env`/env it is used (needed once auth is enabled). Only warn when absent.
    """
    load_dotenv()
    server = _first(URL_KEYS, DEFAULT_URL) or DEFAULT_URL
    token = _first(TOKEN_KEYS)
    if not token:
        logger.warning(
            "No DataHub token found (%s / env). Connecting tokenless — fine for a "
            "local quickstart with auth disabled; set DATAHUB_GMS_TOKEN in .env once "
            "auth is enabled.",
            ENV_PATH,
        )
    return server, token


def get_graph():
    """Build a DataHubGraph (low-level: schema reads, GraphQL, MCP emit)."""
    from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig

    server, token = connection_settings()
    graph = DataHubGraph(DatahubClientConfig(server=server, token=token))
    return graph


def get_client():
    """Build the new-SDK DataHubClient (entities + column-level lineage)."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # silence the datahub.sdk ExperimentalWarning
        from datahub.sdk import DataHubClient

    server, token = connection_settings()
    return DataHubClient(server=server, token=token)


def urn_type(urn: str) -> str:
    """Extract the entity type token from a DataHub URN (urn:li:<type>:...)."""
    parts = urn.split(":", 3)
    return parts[2] if len(parts) >= 3 else ""
