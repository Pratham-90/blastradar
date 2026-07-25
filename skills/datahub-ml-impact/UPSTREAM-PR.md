# Upstream PR prep — `datahub-ml-impact` skill

This skill is written to drop cleanly into
[`datahub-project/datahub-skills`](https://github.com/datahub-project/datahub-skills)
under `skills/datahub-ml-impact/`, matching that repo's existing skill layout
(`SKILL.md` + `README.md` + `references/` + `templates/`, with a small `scripts/`
runner). Nothing here has been pushed anywhere — the steps and PR text below are ready
for you to use once you've reviewed them.

## The diff (focused — one new directory)

```
skills/datahub-ml-impact/
  SKILL.md                                  # frontmatter + workflow
  README.md                                 # human overview
  references/ml-impact-reference.md         # walk, severity rules, trained-on logic, APIs
  templates/ml-impact-report.template.md    # answer structure
  scripts/ml_impact.py                      # thin runner over Blastradar's core
```

No existing files are modified. `.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json` describe the plugin in prose and do **not** enumerate
skills, so no manifest edit is required to register a new skill. (Optional courtesy: add
"ML impact analysis" to the plugin `description`. Left out to keep the diff focused —
mention it in the PR and let a maintainer decide.)

## Steps to open it

```bash
# 1. Fork datahub-project/datahub-skills on GitHub, then:
git clone git@github.com:<you>/datahub-skills.git
cd datahub-skills
git switch -c add-ml-impact-skill

# 2. Copy the skill in (from this Blastradar checkout):
cp -R <blastradar>/skills/datahub-ml-impact skills/datahub-ml-impact

# 3. Replace the <owner> placeholder in SKILL.md / README.md / scripts/ml_impact.py
#    with the real Blastradar install URL (see "review before opening" below).

# 4. Commit + push + open the PR:
git add skills/datahub-ml-impact
git commit -m "Add datahub-ml-impact skill: ML blast-radius analysis for column changes"
git push -u origin add-ml-impact-skill
# open the PR against datahub-project/datahub-skills:main
```

## PR title

```
Add datahub-ml-impact skill: ML blast-radius analysis for column changes
```

## PR description (paste this)

> ### What
> A new skill, `datahub-ml-impact`, that answers interactively: **"what ML systems
> break if I change this column?"** It traces DataHub column-level lineage from a
> changed column to the downstream ML features, models, and deployments, scores each by
> severity, and distinguishes models that were **trained** on the column from those that
> only **read it at inference** — the distinction that turns a "harmless" column drop
> into a silently-degrading production model.
>
> ### Why it fits here / what gap it fills
> The existing `datahub-lineage` skill traces generic upstream/downstream edges. This
> skill goes the last mile *into ML*: it resolves training-run provenance
> (`dataProcessInstance` inputs) and deployment status to score real ML risk. It's a
> natural companion — lineage answers "what connects to X," this answers "how badly does
> changing X hurt, and which live models."
>
> ### How it works
> The skill drives the open-source, Apache-2.0 **Blastradar** library (a CI agent for
> exactly this analysis) rather than reimplementing traversal or scoring — the walk and
> severity are deterministic Python; an LLM is used only for the prose explanation, and
> is optional. `scripts/ml_impact.py` is a thin single-column runner over Blastradar's
> core. Uses DataHub Core only (`get_lineage`, ML aspect reads, `DataProcessInstanceInput`).
>
> ### Testing
> Works fully offline against Blastradar's recorded fixtures (no DataHub needed):
> ```bash
> pip install "blastradar @ git+https://github.com/<owner>/blastradar"
> export BLASTRADAR_REPLAY=/path/to/blastradar/tests/fixtures/recorded/datahub_calls.json
> python skills/datahub-ml-impact/scripts/ml_impact.py --table customers --column customer_since --no-llm
> ```
> …or against a live DataHub via `DATAHUB_GMS_URL`.
>
> ### Note for maintainers
> This skill depends on the `blastradar` package (Apache-2.0). Happy to publish it to
> PyPI, or to discuss vendoring the deterministic core into the skill if you'd prefer no
> external dependency.

## Review before you open it

- [ ] **Replace `<owner>`** in `SKILL.md`, `README.md`, and `scripts/ml_impact.py` with
      the real Blastradar repo/PyPI reference. There is no published package yet — decide
      whether to publish `blastradar` to PyPI first (recommended) or point at the git URL.
- [ ] **Dependency stance.** The other skills wrap the `datahub` CLI and take no pip
      dependency. This one imports Blastradar. Confirm you're comfortable proposing that
      to the maintainers (the PR note raises it explicitly and offers to vendor).
- [ ] **`allowed-tools` scope.** Currently `Bash(python *), Bash(pip *)`. Tighten if the
      maintainers prefer a narrower grant (e.g. a wrapper CLI they can pin).
- [ ] **Run the offline check** in "Testing" above and confirm the output looks right.
- [ ] **License header / attribution** matches the repo's conventions (Apache 2.0).
- [ ] Decide whether to also nudge the plugin `description` (kept out for a focused diff).
