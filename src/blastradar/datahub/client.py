"""Thin wrapper around the DataHub client / MCP tools.

Centralizes connection config and the read/write calls the rest of the package
uses, so the SDK surface is touched in exactly one place. Read docs/API-NOTES.md
before writing anything here.

STUB — populated in Phase 0/1B once the SDK version is verified.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
