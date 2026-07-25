# Submission checklist — DataHub Agent Hackathon (Devpost)

Work top to bottom. Items with pre-filled content are ready to paste; items in
**〈angle brackets〉** need a real value from you. Deadline: **2026-08-10**.

## 1. Public repository

- [ ] Repo is **public** on GitHub: 〈`https://github.com/<owner>/blastradar`〉
- [ ] `main` is green — CI passing (`.github/workflows/ci.yml`, offline suite).
- [ ] `README.md` renders correctly on GitHub (mermaid diagram shows; sample comment
      block reads well).
- [ ] No secrets committed (`.env` is gitignored; only `.env.example` is tracked).

## 2. LICENSE visible in the GitHub "About" sidebar

- [ ] `LICENSE` exists at the repo root, named exactly `LICENSE` (Apache 2.0).
- [ ] On the repo homepage, the **About** sidebar (right side) shows **"Apache-2.0"** —
      this only appears when GitHub recognizes the license file. If it's missing, confirm
      the file is the unmodified Apache 2.0 text at the root.

## 3. Video demo (under 3 minutes, public)

- [ ] Recorded from [`docs/VIDEO-SCRIPT.md`](docs/VIDEO-SCRIPT.md); runtime **< 3:00**.
- [ ] Uploaded to YouTube/Vimeo and set **public** (or unlisted if the rules allow —
      confirm on the Devpost page); playable without login.
- [ ] Video URL: 〈`https://youtu.be/…`〉
- [ ] Added to the Devpost project (the "Video demo" field, not just linked in text).

## 4. Demo / "try it" URL

- [ ] Provide a link people can act on. For a CLI/CI tool the strongest option is the
      repo with the 60-second path front-and-center:
      〈`https://github.com/<owner>/blastradar#try-it-in-60-seconds`〉
- [ ] (Optional) If you stand up a hosted DataHub, add its URL too — otherwise the
      `make demo` instructions are the "try it."

## 5. Description text (paste into Devpost)

**Elevator pitch (one line):**
> Blastradar reviews data PRs and tells you which production ML models a schema change is
> about to silently break — using DataHub's column-level lineage to trace the blast radius
> from a dropped column to the models trained on it.

**What it does / how (paste into the description body):**
> Dropping or renaming a column in a SQL/dbt model doesn't throw an error — the feature
> pipeline downstream silently emits nulls and a production model degrades for weeks.
> Blastradar is a CI agent that catches this at review time. On a PR it parses the SQL
> diff with sqlglot, resolves the changed columns to DataHub URNs, walks column-level
> lineage downstream to the ML features, models, and deployments, and scores each impact —
> critically, distinguishing a model that was **trained** on the column from one that only
> **reads it at inference**. It posts a plain-English PR comment and writes the finding
> back into DataHub Core as an incident, a tag, and a saved document.
>
> The design keeps the impact analysis fully deterministic (plain Python over DataHub's
> APIs) and calls an LLM exactly once, at the end, only to write the explanation — so the
> same PR always yields the same answer. It runs offline in under a minute against
> recorded fixtures (`make demo`), or live against a real DataHub (`make demo-live`).
>
> We also contribute two things back to DataHub open source: a **skill** for asking "what
> ML breaks if I change this column?", and an **ml-showcase datapack** of ML entities
> (which DataHub's sample data currently lacks).

- [ ] Pasted the pitch + description above.
- [ ] "What's next / limitations" filled from the README's **Limitations & future work**
      (judges value honesty here).

## 6. Category selection

- [ ] Selected the hackathon **category/track** on Devpost: 〈pick the track that fits —
      e.g. an "agents / automation" or "best use of DataHub" track〉. Confirm the exact
      category names on the Devpost submission form.

## 7. Technology tags ("Built With")

Add these on Devpost:

- [ ] `datahub` · `python` · `sqlglot` · `anthropic-claude` · `github-actions` · `dbt`
      · `docker` · `pytest` · `click`
- [ ] Double-check the tags match Devpost's canonical tag names as you type them.

## 8. Feedback survey opt-in

- [ ] Completed / opted into the hackathon **feedback survey** (Devpost usually gates a
      prize or bonus on this — check the rules page and tick the opt-in on the submission
      form).

## 9. Final pre-submit sweep

- [ ] Ran the **clean-machine checklist** ([`docs/CLEAN-MACHINE-CHECKLIST.md`](docs/CLEAN-MACHINE-CHECKLIST.md))
      end-to-end and fixed any findings — a judge cloning fresh must succeed.
- [ ] `make demo` works from a cold clone in < 60s; `make test` is green with no Docker.
- [ ] Team members added to the Devpost project; submitted **before** the deadline (submit
      early — you can keep editing until it closes).
