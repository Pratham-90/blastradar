"""Severity scorer for impacted ML assets.

Deterministic scoring over the blast-radius graph, including whether a model was
*trained* on the changed column vs. merely reads it at inference. No LLM.

STUB — populated in Phase 1C.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
