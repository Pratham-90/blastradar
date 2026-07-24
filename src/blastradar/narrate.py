"""LLM narration — the ONLY place the LLM is called (architectural rule 1).

Called exactly once per run, at the very end, given a fully-resolved structured
impact graph. Asked only to write prose and suggest a migration. It never decides
what is impacted.

STUB — populated in Phase 1C.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
