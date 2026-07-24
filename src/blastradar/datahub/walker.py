"""Blast-radius walker: traverse column-level lineage downstream to ML entities.

Deterministic, fixed-algorithm multi-hop traversal of DataHub's column-level
lineage graph, stopping at ML entities (mlFeatureTable, mlModel,
mlModelDeployment). No LLM involvement — see architectural rule 1. Read
docs/API-NOTES.md first.

STUB — populated in Phase 1B.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
