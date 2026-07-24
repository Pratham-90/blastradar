"""Extract changed SQL/dbt model files (and their before/after text) from a PR diff.

Consumes a unified diff or a base/head file pair; produces the inputs the SQL
delta analyzer needs. Does not interpret SQL itself.

STUB — populated in Phase 1A.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
