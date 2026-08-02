# Submission packet — DataHub Agent Hackathon (Devpost)

Everything below is **ready to paste** into the Devpost form field-by-field. The only
values that still need input from you are wrapped in **〈angle brackets〉** — see the list
at the very bottom. Deadline: **2026-08-10, 17:00 EDT** (submit early; you can keep editing
until it closes).

---

## Copy-paste fields

### Project name
```
Blastradar
```

### Elevator pitch (one line)
```
Blastradar reviews data PRs and tells you which production ML models a schema change is about to silently break — using DataHub's column-level lineage to trace the blast radius from a dropped column to the models trained on it.
```

### Repository URL (public)
```
https://github.com/Pratham-90/blastradar
```

### "Try it" URL
```
https://github.com/Pratham-90/blastradar#try-it-in-60-seconds
```
> A judge can run the whole pipeline offline in under a minute with `make demo` — no
> DataHub, no network, no API key. If you later stand up a hosted DataHub, add its URL too.

### Video demo URL
```
〈VIDEO_URL — pending recording; must be public and < 3:00〉
```

### Built With (technology tags)
```
datahub, python, sqlglot, groq, anthropic-claude, github-actions, dbt, docker, pytest, click
```
> Double-check each against Devpost's canonical tag names as you type. Both LLM providers
> are listed on purpose — dual-provider support is a feature (see description).

### Category / track
```
〈CATEGORY — pick the track on the Devpost form, e.g. "Best use of DataHub" / an agents-automation track〉
```

### Description body (paste into "What it does" / project story)

Dropping or renaming a column in a SQL/dbt model doesn't throw an error — the downstream
feature pipeline silently emits nulls and a production model degrades for weeks before
anyone connects it back to the "harmless" cleanup PR. **Blastradar is a CI agent that
catches this at review time.**

On a pull request it parses the SQL diff with **sqlglot**, resolves the changed columns to
**DataHub** URNs, walks DataHub's **column-level lineage** downstream to the ML features,
models, and deployments, and scores each impact — critically, distinguishing a model that
was **trained** on the column (drop it and the model is quietly wrong) from one that only
**reads it at inference**. It posts a plain-English PR comment and writes the finding back
into DataHub Core as an **incident, a tag, and a saved document** — idempotently.

**Deterministic core, one LLM call.** The impact analysis is plain Python over DataHub's
APIs — the lineage walk and severity scoring are fully deterministic, so the same PR always
yields the same answer. The language model is called exactly once, at the very end, only to
write the prose explanation; it never decides what's impacted.

**Dual LLM provider — and keyless by default.** That single narration call auto-selects its
provider at runtime: **Groq** (OpenAI-compatible, fast and cheap) when a Groq key is set,
otherwise **Anthropic Claude** — and with no key at all it falls back to fully-templated
prose. So a judge can run the entire tool with zero API keys, and a team can point it at
whichever LLM they already pay for.

**Runs in under a minute, offline.** `make demo` replays the whole pipeline against recorded
fixtures — no DataHub, no network, no key. `make demo-live` runs it end-to-end against a
real local DataHub with write-back enabled.

**Built on DataHub Core (open source) only** — column-level lineage (`get_lineage`), ML
aspect reads, and training-run provenance (`dataProcessInstance` inputs); write-back via
incidents, tags, and documents. No Cloud-only features on the critical path.

**Contributing back to DataHub open source.** Two upstream PRs:
- a DataHub **skill** for asking "what ML breaks if I change this column?" —
  https://github.com/datahub-project/datahub-skills/pull/78
- an **ml-showcase datapack** of ML entities the sample data currently lacks —
  https://github.com/datahub-project/datahub/pull/18813

**What's next / honest limitations** (judges value candor):
- **Single demo graph.** The seed is one column → one feature → five models → deployments.
  The walker is multi-hop (dataset→dataset column propagation, cycles, a hop cap), but the
  demo graph doesn't exercise deep dataset chains — the ecommerce sample carries no
  transform SQL, so per-hop SQL isn't shown.
- **SDK lineage on non-dataset downstreams.** `datahub.sdk`'s `get_lineage` raises when a
  dataset has a non-dataset (e.g. chart) downstream; affected columns are reported as an
  explicit "incomplete" result, never a false all-clear. Fix: skip non-dataset lineage
  rows, or track an SDK fix.
- **Incidents anchor on the dataset.** This GMS build rejects `mlModel` URNs as an incident
  destination, so the incident is opened on the changed dataset with the model named in the
  title/body; the saved document links each model directly.
- **Severity escalation is potent.** Owning a model escalates its severity one level, which
  can push a deployed inference-only model to critical — faithful to the rule and fully
  traceable in every finding's `reasons`, but a candidate to revisit.
- **PR posting** was validated against a mock GitHub API in the build environment (real
  list/POST/PATCH over the actual httpx path, local server); in CI the same code hits
  github.com.
- **Feature `sources` are dataset-granular** in this GMS, so column precision into features
  is recovered from a `blastradar.source_column` custom property rather than a native
  column edge.

---

## Final pre-submit checklist

Tick every box before you hit submit on Devpost.

- [ ] **Public repo + green CI** — https://github.com/Pratham-90/blastradar is public and
      `main` shows a passing CI run (`.github/workflows/ci.yml`, offline suite on 3.11 + 3.12).
- [ ] **License in About** — the repo's **About** sidebar shows **"Apache-2.0"** (LICENSE is
      the unmodified Apache 2.0 text at the root).
- [ ] **Video public and < 3:00** — recorded from [`docs/VIDEO-SCRIPT.md`](docs/VIDEO-SCRIPT.md),
      uploaded, set **public** (playable without login), and added to the Devpost **Video demo**
      field (not just linked in text). → paste 〈VIDEO_URL〉.
- [ ] **"Try it" URL** — https://github.com/Pratham-90/blastradar#try-it-in-60-seconds is in
      the try-it field; confirmed `make demo` works from a cold clone in < 60s with no Docker.
- [ ] **Category selected** — chose the track on the Devpost form → 〈CATEGORY〉.
- [ ] **Tags added** — `datahub, python, sqlglot, groq, anthropic-claude, github-actions, dbt,
      docker, pytest, click` entered under Built With (matched to Devpost's canonical names).
- [ ] **Feedback survey opted into** — completed/ticked the hackathon feedback survey
      (Devpost often gates a bonus on it — check the rules page).
- [ ] **Teammates added** — every collaborator added to the Devpost project.
- [ ] **Submitted before 2026-08-10 17:00 EDT** — submit early; you can keep editing until
      the deadline closes.

---

## Brackets that still need a value from you

1. **〈VIDEO_URL〉** — the public, sub-3:00 demo video link (not recorded yet — mark pending
   until it's up).
2. **〈CATEGORY〉** — the exact Devpost track/category name to select on the submission form.

Everything else above is filled with real values.
