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
      (deterministic, offline, ~1–2s — the safe choice).
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
alternative: `make demo` (offline fixtures, ~1–2s, identical output).

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

**On screen:** Terminal: `make demo` completing, the timer showing ~1–2s; end card with
the repo URL and "Apache 2.0".

**⚠️ Retake risk:** none — `make demo` is deterministic and fast.

---

## One-take summary of what to have open

Editor (dbt model) → PR diff → terminal (`make demo`) → the rendered comment → DataHub UI
(incident / tag / document, pre-indexed) → README architecture diagram → `make demo`
timer. Total spoken content is paced for ~2:55.

---

# Recording cut (teleprompter)

The tightened one-/two-take version. Read the **VO** column verbatim; do the **On screen**
column exactly. Spoken total ≈ **2:14** of voiceover across ~334 words (≈150 wpm); with the
DataHub pans and natural pauses this lands **~2:45–2:55 — under 3:00**. The two long beats
(3 and 4) are flagged; if you run over, trim the *italic* clauses in beat 3 first.

> **Claims verified against live `make demo` output (2026-08-02):** `2 critical, 1 high, 2
> medium`; `churn_model_v3` = trained-on + IN_SERVICE; `reactivation_model_v1` =
> inference-only; path `customers.customer_since → days_since_signup → churn_model_v3`;
> write-back covers the 2 critical + 1 high + one document. All match the VO below.

### Beat 1 — The silent break · 0:00–0:22 · ~22s / 55 words
- **VO:** "A data engineer drops one column in a pull request — `customer_since`. Looks
  harmless: an unused field, cleaned up. CI passes, it merges, nothing errors. But a
  production churn model was *trained* on that column. The feature pipeline quietly serves
  nulls, and the model rots for weeks before anyone blames this PR."
- **On screen:** Editor on `demo-repo/demo-pr.patch` (or `demo-repo/models/marts/customers.sql`).
  Cursor highlights the `c.customer_since,` line; delete it. Overlay a red subtitle:
  *"No error. No test failure. Silent."*
- **Retake risk:** none (static editor).

### Beat 2 — Enter Blastradar · 0:22–0:40 · ~18s / 44 words
- **VO:** "Blastradar reviews every data PR. It parses the SQL diff with sqlglot, pins the
  exact changed column, then walks DataHub's *column-level* lineage downstream — hunting for
  machine learning. One command, offline against recorded fixtures, in about a second."
- **On screen:** Cut to terminal. Type and run:
  ```sh
  make demo
  ```
  Let it complete (the output is the comment you'll walk in beat 3).
- **Retake risk:** none — `make demo` is deterministic, offline, ~1–2s. (No live DataHub call here.)

### Beat 3 — The comment: trained-on + the deep multi-hop path · 0:40–1:45 · ~48s / ~120 words · ⚠️ longest — the highlight
- **VO:** "Here's the comment — two critical, one high, two medium. Look at `churn_model_v3`:
  it's *trained on the changed column* and *in service*, serving live traffic — the
  distinction no plain lineage view gives you. Trained on it, drop it and it's silently
  wrong; versus only reading it at inference, like `reactivation_model_v1`. Now the part
  that shows the engine: `churn_model_v3` is reached by **two distinct lineage routes** from
  the same dropped column. One is direct. The other runs four hops deep — `customer_since`
  into `customer_engagement_daily`, into `customer_ml_features`, into the derived feature
  `customer_tenure_bucket`, into the model. The walker traced that whole chain and kept
  **both** paths — column-level, multi-hop, fully deterministic."
- **On screen:** the rendered `make demo` comment. Highlight **in this order**: (1) the
  `⚠️ ML blast radius: 2 critical, 1 high, 2 medium` header; (2) `churn_model_v3` — box
  **"trained on the changed column"** + **IN_SERVICE**; (3) **the `Paths (2 distinct — every
  route preserved):` block** — the money shot; run the cursor along the DEEP line first:
  `customers.customer_since → customer_engagement_daily → customer_ml_features →
  customer_tenure_bucket → churn_model_v3`, then the short line beneath it; (4)
  `reactivation_model_v1` — box **"reads it at inference only"**.
- **The exact line to call attention to:** the first bullet under `Paths (2 distinct …)` on
  `churn_model_v3` — the four-hop chain above. That one line is the proof the traversal is
  deep *and* preserves every route (the diamond). Pause on it for a beat.
- **Retake risk:** use the **templated** comment so the wording matches the VO. Needs the
  re-recorded fixtures (deep chain present) — verify the `Paths (2 distinct …)` block renders
  before you record; on the old fixtures `churn_model_v3` shows a single `Path:` line instead.

### Beat 4 — Write-back into DataHub · 1:30–2:05 · ~18s VO + ~15s pans · ⚠️ index-lag beat
- **VO:** "It closes the loop back into DataHub — open-source Core only. For every critical
  and high model it opens an incident, tags it `pending-upstream-change`, and saves the full
  report as a knowledge-base document. All idempotent — re-run it and nothing duplicates."
- **On screen:** DataHub UI, three slow cuts, **all pre-loaded and already indexed**:
  (1) `customers` dataset → **Incidents** tab, CRITICAL/HIGH badges; (2) `churn_model_v3` →
  the **`pending-upstream-change`** tag; (3) the saved **document** listing the impacted models.
- **Retake risk (highest):** index lag. Write-back must be done **and indexed** before you
  record (see setup). **Never** perform write-back live on camera.

### Beat 5 — Why it's trustworthy + OSS give-back · 2:05–2:35 · ~26s / 66 words
- **VO:** "Why trust it? The lineage walk and the severity scoring are plain, deterministic
  Python. The language model is called exactly once, at the very end, only to write the
  explanation — it never decides what's impacted. And we're giving two things back to DataHub
  open source: a skill that answers 'what ML breaks if I change this column?', and an
  ml-showcase datapack, since the sample data ships no ML entities today."
- **On screen:** README mermaid diagram, purple **Narrate — the ONE LLM call** node
  highlighted; then a quick cut to the `skills/datahub-ml-impact/` and `contrib/ml-showcase/`
  file trees.
- **Retake risk:** none — static diagram + file tree.

### Beat 6 — Close · 2:35–2:50 · ~12s / 30 words
- **VO:** "Blastradar catches the silent ML break at review time — not six weeks into a
  production incident. `make demo` runs the whole thing in under a minute, no DataHub required."
- **On screen:** terminal `make demo` completing (timer shows ~1–2s); end card:
  `github.com/Pratham-90/blastradar` + "Apache 2.0".
- **Retake risk:** none.

**Running total:** 22 + 18 + 48 + 33 + 26 + 12 ≈ **2:39** including beat-4 pans; end card to
~2:52. Still under 3:00, but the deeper Beat 3 eats the buffer — if tight, drop beat 5's
datapack sentence (~7s) and trim Beat 3's *italic* "silently wrong / inference" clause.

---

# Pre-record setup checklist (exact commands, in order)

Do **all** of this before you hit record, so no live part stalls. macOS/Linux paths shown;
on Windows use `.venv\Scripts\` and run `set PYTHONUTF8=1` first (else the emoji comment errors).

**1. Populate DataHub (the slow, must-be-pre-staged part).** Start Docker Desktop, then:
```sh
make demo-live        # stands up DataHub, seeds the ML graph, runs the pipeline with
                      # write-back — it sets TOOLS_IS_MUTATION_ENABLED=true for you
```
Let it finish, **then wait ~2–3 min for the search/graph index to catch up.**

**2. Verify the three UI panels render NOW** (log in at `http://localhost:9002`, `datahub`/`datahub`):
- `customers` dataset → **Incidents** tab shows the CRITICAL/HIGH incidents;
- `churn_model_v3` shows the **`pending-upstream-change`** tag;
- the knowledge-base **document** lists the impacted models.
If any panel is empty, the index hasn't caught up — wait, don't record.

**3. Stage the deterministic comment (the on-camera artifact):**
```sh
make demo             # prints the comment offline, ~1–2s; keyless, deterministic
```

**4. (Optional) Live single LLM call — Groq.** The **primary take is keyless** (the templated
comment from step 3); do this only for the bonus "one live call" shot. **Set your Groq key**,
then run with `--llm` (provider is Groq — narration auto-selects Groq whenever `GROQ_API_KEY`
is set). Record it **once** (prose varies run to run):
```sh
export GROQ_API_KEY=...    # required for this shot — Groq gives the fastest visible call
.venv/bin/python scripts/demo.py --scenario critical --llm   # --llm implies --no-write
```

**5. Editors / tabs / display:**
- Editor open on `demo-repo/demo-pr.patch` (the one-line drop) and the `customers` model.
- Terminal: **large font (18–22pt)**, cleared scrollback, working dir = repo root.
- Browser zoom **125–150%**; pre-open tabs: (a) `customers` → Incidents, (b) `churn_model_v3`,
  (c) the document, (d) README rendered at the mermaid diagram.

---

# Slow / non-deterministic moments — how to cut around them

| Moment | Why it hurts | Pre-stage / cut |
|---|---|---|
| First `make demo-live` **image pull** | Several minutes of docker pulls | Run to completion **before** recording; never film the first run. |
| **Index lag** after write-back (~2–3 min) | A cold click on Incidents/tag/document shows nothing | Do write-back in setup step 1; verify each panel renders (step 2) before rolling. Never write-back live. |
| **LLM latency + drift** | A live call is slow and re-wording breaks VO sync | Show the **templated** comment (keyless). If you insist on a live call, use **Groq** and record once. |
| `make demo` **timing** | Varies by machine (~1–2s here) | Don't promise a specific sub-second number on the end card; "under a minute / about a second" is safe. |
| **Windows console encoding** | Emoji comment raises `UnicodeEncodeError` on cp1252 | If recording on Windows, `set PYTHONUTF8=1` before any `demo`/`pytest`. |
