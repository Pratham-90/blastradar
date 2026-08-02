# Example impact reports

Three sample Blastradar reports covering the shapes a data PR can take. Each is
committed as both the rendered PR comment (`.md`) and the machine-readable finding
(`.json`). All three are **generated**, not hand-written — `make examples`
regenerates them from the recorded fixtures, and a test (`test_examples_do_not_rot`)
fails if a committed file drifts from what the pipeline produces.

| Report | Input PR | Shape | Top severity |
|---|---|---|---|
| [impact-critical-trained-on](impact-critical-trained-on.md) | [`demo-repo/demo-pr.json`](../demo-repo/demo-pr.json) — drop `customers.customer_since` | A deployed model was **trained** on the dropped column | 🔴 2 critical, 1 high, 2 medium |
| [impact-medium-non-deployed](impact-medium-non-deployed.md) | [`demo-repo/medium-pr.json`](../demo-repo/medium-pr.json) — drop `order_details.order_total` | One impacted model, **not in production** yet | 🟡 1 medium |
| [impact-clean-no-impact](impact-clean-no-impact.md) | [`demo-repo/clean-pr.json`](../demo-repo/clean-pr.json) — drop `customers.phone_number` | No ML feature/model depends on the column | ✅ no impact |

## What each shape demonstrates

- **Critical, trained-on** — the flagship. `customer_since` feeds `days_since_signup`,
  which five models consume. The deployed `churn_model_v3` was *trained* on it
  (critical); the deployed `reactivation_model_v1` only *reads* it at inference
  (high, escalated to critical by its owner); the rest are non-deployed. Because it
  has critical/high impacts, the write-back plan lists incidents, tags, and a
  document (shown as `🚫 disabled` offline — set `TOOLS_IS_MUTATION_ENABLED=true` to
  actually write them via `make demo-live`).
- **Medium, non-deployed** — `order_details.order_total` feeds one model,
  `ltv_model_v1`, which isn't deployed. A real but lower-stakes hit: nothing is
  serving predictions yet, so nothing is written back.
- **Clean, no impact** — `phone_number` resolves to a real column, but nothing
  downstream depends on it. Note this is a *genuine* all-clear (the column resolved);
  Blastradar never reports "no impact" when an analysis was actually incomplete.

## Regenerate

```sh
make examples          # rewrites all six files from the recorded fixtures
```

The narration here is the deterministic **templated** fallback (no API key needed),
so the output is stable and the committed files don't churn. With a narration key set
(`GROQ_API_KEY` — the default provider — or `ANTHROPIC_API_KEY`), the live CLI
(`make demo-live`) writes richer prose via the single LLM narration call.
