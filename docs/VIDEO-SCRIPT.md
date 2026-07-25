# Blastradar — 3-minute demo script

Target: **under 3:00.** Each beat has the **voiceover**, exactly what's **on screen**,
and any **⚠️ retake risk** (slow or non-deterministic — pre-stage these before you hit
record). Read the "Before you record" checklist first; it removes every retake risk so
the whole thing can be one clean take.

## Before you record (pre-stage everything)

- [ ] `make demo-live` **already run to completion** and DataHub healthy — never film the
      first-run image pull (several minutes). The UI at `:9002` is logged in
      (`datahub` / `datahub`).
- [ ] Write-back **already performed** and the **index has caught up** (~2–3 min): open
      the `customers` dataset → Incidents tab, a model's tags, and the document, and
      confirm they render *now*. New edges lag the search/graph index, so a cold click
      during recording can show nothing.
- [ ] The PR comment is real and visible: either an actual GitHub PR with the Action run
      (set up ahead of time), **or** use `make demo`'s terminal output as the "comment"
      (deterministic, offline, ~0.5s — the safe choice).
- [ ] Narration is the **deterministic templated** output (`make demo` / `--no-llm`). If
      you show LLM prose, it changes every run — record that panel once and don't re-run.
- [ ] Terminal font large; browser zoom up; `demo-repo/demo-pr.patch` open in the editor.

---

## 0:00–0:25 — The problem

**Voiceover:** "Someone opens a data PR that drops a column called `customer_since`. It
looks completely harmless — cleaning up an unused field. It passes CI. It merges. And
nothing errors. But `customer_since` is what a churn model in production was *trained*
on. The feature pipeline quietly starts emitting nulls, and the model degrades for weeks
before anyone connects it back to this PR."

**On screen:** The dbt model file in the editor; cursor highlights the
`c.customer_since,` line, then it's deleted (show `demo-repo/demo-pr.patch`). A red
subtitle: *"No error. No test failure. Silent."*

**⚠️ Retake risk:** none — static editor view.

## 0:25–0:50 — The PR is opened

**Voiceover:** "So we put a reviewer on every data PR: Blastradar. When this PR opens, it
parses the SQL diff with sqlglot, finds the exact changed column, and walks DataHub's
**column-level** lineage downstream — looking for machine learning."

**On screen:** The PR "Files changed" view (or `git diff`) showing the one-line drop,
then cut to the terminal running the command:
```
blastradar analyze --changes demo-repo/demo-pr.json --pr-repo order-entry/analytics --pr-number 42
```

**⚠️ Retake risk:** if run live against DataHub, keep it snappy (~seconds). Safe
alternative: `make demo` (offline fixtures, ~0.5s, identical output).

## 0:50–1:50 — The comment, and the trained-on finding

**Voiceover:** "Seconds later, the comment. Two critical, one high, two medium. Follow
the top one: `customer_since` feeds the feature `days_since_signup`, which feeds
`churn_model_v3` — and here's the key line: **trained on the changed column**, and it's
**deployed, serving live predictions**. That's the difference that matters. Blastradar
separates a model that was *trained* on the column — drop it and the model is quietly
wrong — from one that only *reads* it at inference. The second critical,
`reactivation_model_v1`, is exactly that inference-only case. Every finding shows the
lineage path and a one-line reason for its severity — it's fully deterministic, so you
get the same answer every time."

**On screen:** The rendered comment. Slowly scroll/highlight in order:
1. the `⚠️ ML blast radius: 2 critical, 1 high, 2 medium` header,
2. the `churn_model_v3` block — box-highlight **"trained on the changed column"** and
   **IN_SERVICE**,
3. the path `customers.customer_since → days_since_signup → churn_model_v3`,
4. the `reactivation_model_v1` block — highlight **"reads it at inference only"**.

**⚠️ Retake risk:** use the deterministic (templated) comment so the wording matches the
voiceover exactly. LLM narration would drift.

## 1:50–2:25 — Into DataHub: incident, tag, document

**Voiceover:** "It doesn't stop at a comment — it closes the loop back into DataHub, using
open-source DataHub Core only. For every critical and high model it opens an **incident**,
tags the model **pending-upstream-change**, and saves the full report as a knowledge-base
**document** — all idempotent, so re-running never duplicates anything."

**On screen:** DataHub UI, three quick cuts (all pre-loaded, index caught up):
1. the `customers` dataset → **Incidents** tab, showing the open incidents with
   CRITICAL/HIGH priority badges,
2. `churn_model_v3` → the **`pending-upstream-change`** tag on it,
3. the saved **document** listing the impacted models.

**⚠️ Retake risk (highest):** index lag. The incident/tag/document must already be
written **and indexed** before recording — verify each panel renders before you start.
Do not perform the write-back live on camera.

## 2:25–2:50 — Architecture + the OSS contributions

**Voiceover:** "One design choice makes this trustworthy: the lineage walk and the impact
scoring are plain, deterministic Python — the language model is called exactly once, at
the end, only to write the explanation. It never decides what's impacted. And we're
giving two things back to DataHub open source: a **skill** so anyone can ask 'what ML
breaks if I change this column?', and an **ml-showcase datapack** — since DataHub's sample
data ships no ML entities today."

**On screen:** The README architecture diagram (the mermaid flow, with the purple
**Narrate — the ONE LLM call** node highlighted). Then a quick cut to the
`skills/datahub-ml-impact/` and `contrib/ml-showcase/` directory trees.

**⚠️ Retake risk:** none — static diagram + file tree.

## 2:50–3:00 — Close

**Voiceover:** "Blastradar: catch the silent ML break at review time, not six weeks into
a production incident. `make demo` runs the whole thing in under a minute — no DataHub
required."

**On screen:** Terminal: `make demo` completing, the timer showing ~0.5s; end card with
the repo URL and "Apache 2.0".

**⚠️ Retake risk:** none — `make demo` is deterministic and fast.

---

## One-take summary of what to have open

Editor (dbt model) → PR diff → terminal (`make demo`) → the rendered comment → DataHub UI
(incident / tag / document, pre-indexed) → README architecture diagram → `make demo`
timer. Total spoken content is paced for ~2:55.
