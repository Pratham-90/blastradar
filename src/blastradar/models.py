"""Domain models shared across the pipeline.

Frozen dataclasses (or pydantic models) describing column changes, resolved URNs,
the blast-radius graph, impacted ML assets, severity scores, and the final report.

STUB — populated in Phase 1A onward. No feature logic in the skeleton session.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# TODO(Phase 1A): ColumnChange, ChangeKind (dropped / renamed / retyped)
# TODO(Phase 1B): ResolvedColumn (URN), BlastEdge, ImpactedAsset
# TODO(Phase 1C): SeverityScore, BlastRadius (the fully-resolved structured graph
#                 handed to the narrator)
