"""SQL delta analyzer: diff two versions of a model to find changed columns.

Uses sqlglot (NOT regex) to parse before/after SQL and compute which output
columns were dropped, renamed, or retyped. Expands SELECT * using DataHub schema
metadata rather than guessing.

STUB — populated in Phase 1A.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
