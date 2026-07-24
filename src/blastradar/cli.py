"""Command-line entry point (click).

Wires the pipeline together: diff extract -> SQL delta -> resolve -> walk ->
score -> narrate -> report / write-back. Also drives `make demo` and
`make demo-live`.

STUB — populated in Phase 1D/2.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
