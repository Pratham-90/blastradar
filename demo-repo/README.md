# order_entry — analytics dbt project

The analytics warehouse for the **Order Entry** e-commerce business. These dbt
models are ingested into DataHub (as the `dbt` platform), which is how
[Blastradar](../README.md) knows their column-level lineage into the feature
store and the ML models downstream.

This is the project Blastradar reviews in the demo. It is deliberately small but
structured like a real dbt project.

```
demo-repo/
  dbt_project.yml                 project config (profile, materializations)
  profiles.example.yml            example Snowflake profile
  models/
    staging/
      _order_entry__sources.yml   raw source definitions
      stg_customers.sql           cleaned customers
      stg_orders.sql              cleaned orders
      stg_order_items.sql         cleaned line items
    marts/
      customers.sql               ⭐ customer dimension — upstream of the ML features
      orders.sql                  orders fact
      schema.yml                  tests + column docs (note the customer_since warning)
  demo-pr.json                    the demo PR as a runnable changeset
  demo-pr.patch                   the same PR as a human-readable git patch
```

> The `.sql` files are shown in their **compiled** form (plain SQL) so Blastradar's
> sqlglot parser reads them directly. The authored models use dbt `{{ ref() }}` /
> `{{ source() }}`; in CI the action runs `dbt compile` first (or diffs
> `target/compiled`). See [`.github/workflows/blastradar.yml`](../.github/workflows/blastradar.yml).

## The demo PR

[`demo-pr.patch`](demo-pr.patch) drops the **`customer_since`** column from
`models/marts/customers.sql`. It looks harmless — "removing an unused column" —
but `customer_since` feeds `customer_features.days_since_signup`, which five ML
models consume:

| Model | Uses `customer_since` | Deployed | Owner | Blastradar severity |
|---|---|---|---|---|
| `churn_model_v3` | trained on it | ✅ prod + canary | @ml-platform | 🔴 critical |
| `reactivation_model_v1` | inference only | ✅ prod + canary | @growth-ml | 🔴 critical (high, escalated by owner) |
| `churn_model_v1` | trained on it | — | @ml-platform | 🟠 high (medium, escalated by owner) |
| `ltv_model_v1` | trained on it | — | @analytics-ml | 🟠 high (medium, escalated by owner) |
| `churn_model_v2` | trained on it | — | unowned | 🟡 medium |

Write-back acts on the **critical and high** rows: an incident + a `pending-upstream-change`
tag for each of the top four models, plus one knowledge-base document holding the full report.

Dropping the column does not raise an error — the feature silently emits nulls and
the models degrade in production. That is the whole point of Blastradar.

## Run Blastradar against this PR

From the repo root (`blastradar/`), with a local DataHub seeded (`make seed`):

```bash
# Offline-friendly: analyze the PR from the JSON changeset (no git checkout needed).
blastradar analyze \
  --changes demo-repo/demo-pr.json \
  --pr-repo order-entry/analytics --pr-number 42 \
  --pr-url https://github.com/order-entry/analytics/pull/42 \
  --dry-run                      # preview write-back + comment without writing

# For real write-back into DataHub (incident + tag + document):
export TOOLS_IS_MUTATION_ENABLED=true
blastradar analyze --changes demo-repo/demo-pr.json \
  --pr-repo order-entry/analytics --pr-number 42 \
  --pr-url https://github.com/order-entry/analytics/pull/42 \
  --no-post-comment              # skip the GitHub call when running locally
```

Re-run either command — it is idempotent: no duplicate incidents, the tag is a
set-union, and the document and PR comment update in place.
