### ⚠️ ML blast radius: 1 medium

This PR drops `order_details.order_total`, which feeds 1 downstream ML model(s) — the change will not raise an error, so the impact is silent.

**🟡 medium — `ltv_model_v1`** (unowned)
- Deployment: not deployed  ·  Training: trained on the changed column
- Path: `order_details.order_total` → `order_total_avg` → `ltv_model_v1`

`ltv_model_v1` was trained on this column and is not currently deployed. Dropping or renaming the column does not fail the pipeline; the feature silently emits nulls or stale values, so predictions degrade without any error surfacing.
- _Why this severity: mlModel with no active deployment_

### Suggested migration

Avoid an in-place change to `order_details.order_total`. Prefer a deprecate-then-drop: add the replacement column alongside the old one, backfill it, migrate every downstream feature and training pipeline, verify the feature store, then remove `order_total` in a follow-up PR. Coordinate with the owning team(s) before merging.

---
### 📋 Write-back to DataHub
_No critical or high impacts — nothing written back._
