# Clean-machine test checklist

The one Phase 2 task that needs a human: prove a stranger can run this from a cold
start. Follow the steps **literally** — do not use knowledge from building the repo,
do not fix things as you go. Instead, note **every** place a step fails, hangs, is
ambiguous, or contradicts the README, in the "Findings" table at the bottom. Then
hand that table back and it all gets fixed.

The goal from the top of Phase 2: **runnable by a stranger in under 60 seconds
(`make demo`), and by a determined stranger in full (`make demo-live`) in under 15
minutes.** Time both.

---

## Part A — Wipe (start genuinely clean)

```sh
# 1. Tear down any existing DataHub stack and DELETE its volumes (fresh state).
.venv/bin/datahub docker nuke        # or: datahub docker nuke, if datahub is on PATH
docker volume ls | grep -i datahub   # expect: no rows (volumes gone)
docker ps | grep -i datahub          # expect: no rows (no containers)

# 2. Move the existing checkout aside so the clone below is truly fresh.
cd ~/Desktop/Datahub            # the parent of the current blastradar/ checkout
mv blastradar blastradar.old    # keep the old one; we clone fresh next to it
```

> If Blastradar is not yet pushed to a git remote, instead copy the working tree to a
> new directory and `rm -rf` its `.venv`, `tests/fixtures/recorded/` is kept (it is
> committed), `examples/` is kept, and any local `.env`:
> ```sh
> rsync -a --exclude .venv --exclude '__pycache__' --exclude '.pytest_cache' \
>       --exclude '.env' blastradar.old/ blastradar-fresh/
> cd blastradar-fresh
> ```

## Part B — Clone fresh and read the README literally

```sh
# 3. Clone into a NEW directory (skip if you used the rsync fallback above).
cd ~/Desktop/Datahub
git clone <REPO_URL> blastradar-fresh
cd blastradar-fresh

# 4. Open README.md and do EXACTLY what "Quick start" / setup says — nothing more.
#    Record the first instruction that is missing, wrong, or assumes prior knowledge.
```

Checkpoints while following the README:
- [ ] Does the README tell you which Python to use and how to create the venv?
- [ ] Does it tell you how to install (`pip install -e ".[dev]"`) before `make`?
- [ ] Does `make help` list the targets and match reality?

## Part C — The 60-second path (`make demo`)

```sh
# 5. Set up the environment exactly as the README says, then:
time make demo
```

- [ ] Completes in **under 60 seconds** (note the real time): ____
- [ ] Needs **no** DataHub, **no** network, **no** API key. (Try it with your
      network off / airplane mode to be sure.)
- [ ] Prints a readable PR comment (2 critical, 3 medium) to the terminal.
- [ ] Wrote / matches `examples/impact-critical-trained-on.md`.
- [ ] `make test` is green with Docker NOT running:
      ```sh
      docker ps    # (still empty from Part A)
      make test    # expect: all green, ~1s
      ```

## Part D — The full path (`make demo-live`), under 15 minutes

```sh
# 6. Start Docker Desktop. Then, from a cold DataHub (Part A wiped it):
time make demo-live
```

- [ ] Stands up DataHub (first run pulls images — this is the slow part).
- [ ] Waits for health, ingests sample data, seeds the ML graph — **no manual steps**.
- [ ] Runs the pipeline with write-back and does **not** make you discover
      `TOOLS_IS_MUTATION_ENABLED` yourself (the target sets it to `true`).
- [ ] Prints where to look in the DataHub UI, and the incidents/tags/document are
      actually there.
- [ ] Total wall-clock from cold start (note it): ____  (target: < 15 min)

## Part E — Regenerating fixtures (optional, for the determined)

```sh
# 7. With the live DataHub from Part D still up and seeded:
make seed              # ensure a clean baseline
make record-fixtures   # re-capture live responses into tests/fixtures/recorded/
git status             # note whether the recording changed (it should be stable)
make test              # still green against the fresh recording
```

- [ ] `make record-fixtures` succeeds and `make test` stays green afterward.

---

## Findings

**Driven cold-clone run (automated, 2026-08-02).** Fresh `git clone` of the pushed repo
into `/tmp/blastradar-clean`, then the offline path (Parts B–C) was executed:

- Editable install (`pip install -e ".[dev]"`) — **OK**, `acryl-datahub==1.6.0.15` (matches pin).
- `make test` equivalent — **74 passed**, offline (Docker not running, no network, no key).
- `make demo` equivalent — **OK**, printed `2 critical, 3 medium`, timed **~1.8 s**
  (budget 60 s). Offline is enforced in code (replay client via `conftest`), so no
  DataHub / network / API key / env var is needed — confirmed.

Parts A, D, E (Docker wipe + `make demo-live`, second machine) are human-only — see the
hand-off checklist in the session report. Rows below are the offline-path findings; all
"FIXED" rows are doc-only edits (no feature code changed) committed with this update.

| # | Step | What happened (fail / hang / ambiguous / contradicts README) | Suggested fix |
|---|------|--------------------------------------------------------------|---------------|
| 1 | B/C — README quick start | `python3.11` is hardcoded; on a machine with only 3.12/3.13 it's `command not found` (exit 127). It isn't actually required — pyproject needs `>=3.11` and CI runs **both** 3.11 and 3.12. | **FIXED**: state "Python 3.11 or 3.12", command `python3.12 … # or python3.11`. |
| 2 | B/C — install path | `.venv/bin/pip` is POSIX-only; on Windows the path is `.venv\Scripts\`. No Windows guidance existed. | **FIXED**: added a "Windows, or no `make`" `<details>` block with the `Scripts\` paths. |
| 3 | C — `make demo` / `make test` | `make` is required but never listed as a prerequisite and has no fallback; `make: command not found` where GNU make isn't installed (common on Windows, minimal macOS). | **FIXED**: README now names GNU make as a prereq and gives the direct no-`make` commands. |
| 4 | C — `make demo` on a non-UTF-8 locale | Report prints `✅`/`→`; on Windows' cp1252 default this raises `UnicodeEncodeError` (exit 1). Green everywhere the default encoding is UTF-8 (macOS/Linux). | **FIXED (doc)**: README says set `PYTHONUTF8=1` on Windows. Recommended code follow-up: reconfigure stdout to UTF-8 in the CLI/demo entry point. |
| 5 | C — timing claim | README said the demo "completes in ~0.5s"; measured **~1.8 s** cold on a fresh clone (still ≪ 60 s). | **FIXED**: softened to "~2s". |
| 6 | C — `make demo` writes `examples/` | The demo rewrites `examples/*.md/.json`; on Windows it writes CRLF, leaving the clone's tree dirty after a run. Content is identical (rot-guarded by tests); cosmetic only. | Optional (not committed): add `.gitattributes` with `* text=auto eol=lf`. |

When this table comes back, every row gets fixed and the checklist is re-run until it
is clean end-to-end.
