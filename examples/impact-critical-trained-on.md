### ⚠️ ML blast radius: 2 critical, 3 medium

This PR drops `customers.customer_since`, which feeds 5 downstream ML model(s) — the change will not raise an error, so the impact is silent.

**🔴 critical — `churn_model_v3`** (owner: @ml-platform · tags: Tier1)
- Deployment: churn_model_v3-canary (IN_SERVICE), churn_model_v3-prod (IN_SERVICE)  ·  Training: trained on the changed column
- Path: `customers.customer_since` → `days_since_signup` → `churn_model_v3`

`churn_model_v3` was trained on this column and is currently deployed and serving predictions. Dropping or renaming the column does not fail the pipeline; the feature silently emits nulls or stale values, so predictions degrade without any error surfacing.
- _Why this severity: mlModel with an active deployment AND trained on the changed column; escalated one level: carries tag Tier1 (already at maximum severity)_

**🔴 critical — `reactivation_model_v1`** (owner: @growth-ml)
- Deployment: reactivation_model_v1-canary (IN_SERVICE), reactivation_model_v1-prod (IN_SERVICE)  ·  Training: reads it at inference only
- Path: `customers.customer_since` → `days_since_signup` → `reactivation_model_v1`

`reactivation_model_v1` reads this column at inference time and is currently deployed and serving predictions. Dropping or renaming the column does not fail the pipeline; the feature silently emits nulls or stale values, so predictions degrade without any error surfacing.
- _Why this severity: mlModel with an active deployment (inference-time consumption only); escalated one level: owner group set (growth-ml) on an active deployment_

**🟡 medium — `churn_model_v1`** (owner: @ml-platform · tags: Tier2)
- Deployment: not deployed  ·  Training: trained on the changed column
- Path: `customers.customer_since` → `days_since_signup` → `churn_model_v1`

`churn_model_v1` was trained on this column and is not currently deployed. Dropping or renaming the column does not fail the pipeline; the feature silently emits nulls or stale values, so predictions degrade without any error surfacing.
- _Why this severity: mlModel with no active deployment_

**🟡 medium — `churn_model_v2`** (unowned)
- Deployment: not deployed  ·  Training: trained on the changed column
- Path: `customers.customer_since` → `days_since_signup` → `churn_model_v2`

`churn_model_v2` was trained on this column and is not currently deployed. Dropping or renaming the column does not fail the pipeline; the feature silently emits nulls or stale values, so predictions degrade without any error surfacing.
- _Why this severity: mlModel with no active deployment_

**🟡 medium — `ltv_model_v1`** (unowned)
- Deployment: not deployed  ·  Training: trained on the changed column
- Path: `customers.customer_since` → `days_since_signup` → `ltv_model_v1`

`ltv_model_v1` was trained on this column and is not currently deployed. Dropping or renaming the column does not fail the pipeline; the feature silently emits nulls or stale values, so predictions degrade without any error surfacing.
- _Why this severity: mlModel with no active deployment_

### Suggested migration

Avoid an in-place change to `customers.customer_since`. Prefer a deprecate-then-drop: add the replacement column alongside the old one, backfill it, migrate every downstream feature and training pipeline, verify the feature store, then remove `customer_since` in a follow-up PR. Coordinate with the owning team(s) before merging.

---
### 📋 Write-back to DataHub
> 🚫 **Write-back skipped — mutations are disabled.** Set `TOOLS_IS_MUTATION_ENABLED=true` to open incidents, tag models, and save the report to DataHub. The following **would** have been written:

| | Action | Target | Status | Detail |
|---|---|---|---|---|
| 🚫 | incident | `churn_model_v3` | disabled | anchored on the changed dataset |
| 🚫 | tag | `churn_model_v3` | disabled | tag `pending-upstream-change` |
| 🚫 | incident | `reactivation_model_v1` | disabled | anchored on the changed dataset |
| 🚫 | tag | `reactivation_model_v1` | disabled | tag `pending-upstream-change` |
| 🚫 | document | `knowledge base` | disabled | full impact report |

_set TOOLS_IS_MUTATION_ENABLED=true to apply_
