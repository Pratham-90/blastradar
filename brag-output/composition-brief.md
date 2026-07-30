# Hyperframes Composition Brief: Blastradar

## Objective
Create a short launch-style brag video for Blastradar — a CI agent that reviews data pull requests
and reports which production ML models a schema change is about to silently break.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080
- Duration: 20 seconds

## Source Material
- Project root: `/Users/shaliniaggarwal/Desktop/Datahub/blastradar`
- Primary files read: `README.md`, `CLAUDE.md`, `examples/impact-critical-trained-on.md`,
  `demo-repo/demo-pr.json` (the actual PR diff), `src/blastradar/narrate.py`
- Product name: **Blastradar**
- Tagline / strongest claim: "Know what breaks. Before you merge."
- Key UI or visual moment to recreate: **the rendered GitHub PR comment** — its severity header
  and the critical finding card with the column-level lineage path. This project has no website;
  the PR comment IS the product's visible surface.

- Copy that must appear verbatim:
  - `c.customer_since,    -- account-age driver for ML features`   (the deleted SQL line)
  - `No error. Nothing fails.`
  - `Five models keep serving. On nulls.`
  - `⚠️ ML blast radius: 2 critical, 1 high, 2 medium`
  - `churn_model_v3`
  - `customers.customer_since → days_since_signup → churn_model_v3`
  - `trained on the changed column`
  - `Blastradar`
  - `Know what breaks. Before you merge.`

## Creative Direction
- Tone preset: `polished`
- Creative direction: quiet, premium incident-report film — restraint as the creative choice
- Interpretation: 4 scenes, long holds, soft crossfades (0.6–0.8s). No hype, no rapid cuts, no
  exclamation. Light-weight type with generous tracking. The severity red is the only saturated
  color in the film, so it lands when it finally appears.
- Angle: The horror of the *silent* failure. Every other CI tool brags about catching errors.
  Blastradar's premise is that **there is no error** — you delete a column, every test passes, the
  pipeline stays green, and a production churn model quietly rots for six weeks. The film should
  feel like a quiet, well-lit crime scene: the change looks harmless, and that is the problem.
- Hook: a single line of SQL struck out in red, then the words "No error. Nothing fails."
- Outro / punchline: "Blastradar — Know what breaks. Before you merge."
- Avoid:
  - Generic SaaS language
  - Abstract filler visuals
  - Unrelated visual redesign
  - Alarm/siren sounds or riser stingers (they contradict the film's premise)

## Visual Identity
The project ships no website or CSS. Identity is derived from where its output actually lives — a
GitHub PR comment on a dark theme — plus the one real brand color in the repo (the purple `Narrate`
node in the README's mermaid pipeline diagram, `style F fill:#7c3aed`).

- Background: `#0d1117`
- Surface / card: `#161b22`, borders `#30363d`
- Text: `#e6edf3` primary, `#8b949e` secondary
- Accent: `#7c3aed`
- Critical: `#f85149` · High: `#d29922` · Medium: `#e3b341`
- Display font: Inter (light/medium, generous letter-spacing)
- Body/code font: JetBrains Mono — authentic to a CLI that parses SQL and emits markdown
- Visual references from the project: the diff gutter of `models/marts/customers.sql`; the severity
  header line; the `→` lineage chain; the `trained on the changed column` distinction

## Storyboard
Use the storyboard in `brag-output/brag-plan.md` as the creative contract.

Scene summary:
1. **The deletion** — 5s — the real SQL line gains a red `-` gutter and strikes through; "No error. Nothing fails." holds ~1.5s
2. **The silence** — 5s — 5 model chips arrive one by one, all green/serving, then every value flips to `null` and the green drains to grey. Nothing turns red. "Five models keep serving. On nulls."
3. **Blastradar reads the PR** — 6s — the real severity header lands, then the `churn_model_v3` critical card, then the lineage path draws hop by hop; "trained on the changed column" holds the longest beat in the film (~1.6s)
4. **Outro** — 4s — the grey chips return small in the dark; "Blastradar" resolves with a thin `#7c3aed` underline; "Know what breaks. Before you merge." Long hold.

## Audio
- Audio role: sparse professional accents over a restrained bed
- Audio arc: a low, unbothered bed runs under the whole film and never reacts to the damage; three
  sparse motion-matched cues mark the deletion, the null-flip, and the critical finding; the track
  fades to silence for the outro, so the last thing the viewer hears is nothing at all.
- Music: `happy-beats-business-moves-vol-9-by-ende-dot-app.mp3` (114.84 BPM)
- Music treatment: enter ~0.8s, sit low as a bed (not lead) throughout, fade out across the final
  ~1.5s so the tagline lands in near-silence.
- Music cue guidance: bundled preset read from
  `~/.claude/skills/brag/assets/music/cues/happy-beats-business-moves-vol-9-by-ende-dot-app.music-cues.json`.
  Strong cues to target: **6.34s** (the null-flip), **10.54s** (the blast-radius header),
  **12.65s** (the critical card). Beat grid is ~0.52s; sequential text must use **every other beat**
  (~1.05s) to clear the reading floor.
- Audio-reactive treatment: none — restraint is the tone. No waveform bars, no pulsing glow.
- Audio-coupled moments:
  - Scene 1, the strike-through — one dry, soft interface/key tick
  - Scene 2, the flip to `null` — a soft collective cue, quiet, not a stinger
  - Scene 3, the critical card arrival — one restrained card cue
- SFX selection guidance: sparse — at most 3–4 cues in the whole film, motion-matched only. No
  alarms, no risers, no impact stingers on the severity reveal.
- SFX analysis guidance: `~/.claude/skills/brag/assets/sfx/sfx-analysis.md`; prefer low
  high-frequency-risk files for this polished tone.
- Exact SFX choice: Hyperframes chooses filenames, timestamps, density, and volume based on the
  implemented animation.
- Audio files: copy the chosen music and any selected SFX into `brag-output/composition/assets/`

## Hyperframes Instructions
Load the composition-building Hyperframes domain skills — `hyperframes-core`, `hyperframes-animation`,
`hyperframes-creative`, `hyperframes-keyframes`, `hyperframes-cli`. /brag is its own workflow: do not
enter the `hyperframes` entry-point intent interview and do not route into its generic promo /
launch-video workflow. Prefer native Hyperframes conventions.

Requirements:
- Show at least one real UI/copy element from the project — the PR comment (Scene 3) is mandatory.
- Keep all text readable: short label ≥0.8s settled, sentence ≥0.3s/word.
- Keep the video within 15–25 seconds (target 20s).
- Include the music bed and 3–4 sparse SFX.
- Lock 1–3 major reveals to strong cues within ±0.15s; snap sequential chips/cards to the beat grid
  within ±0.10s, using every-other-beat spacing for anything with readable text.
- Honor the final fade-to-silence under the outro.
- Audio-reactive is explicitly **none** for this film; do not add reactive motion.
- Use local assets for audio and any runtime dependencies.
- Run `hyperframes check` before render — it is brag's single gate.
