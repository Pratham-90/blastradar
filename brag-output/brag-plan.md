# Brag Plan: Blastradar

## What is this app?
Blastradar is a CI agent that reviews data pull requests and tells you which production ML
models a schema change is about to silently break — tracing DataHub column-level lineage from
a dropped column all the way down to the models trained on it.

## The angle
The horror of the *silent* failure. Every other CI tool brags about catching errors. Blastradar's
entire premise is that **there is no error** — you delete a column, every test passes, the pipeline
stays green, and a production churn model quietly rots for six weeks. The video should feel like a
quiet, well-lit crime scene: the change looks harmless, and that is exactly the problem.

Specific to this project, not generic: we use the *real* deleted SQL line, the *real* model names,
the *real* lineage path, and the *real* PR comment. No invented product.

## Hook (first 2-3 seconds)
A dark editor. One line of SQL slides in and is struck out in red:

```
-    c.customer_since,    -- account-age driver for ML features
```

Then, in the empty space beneath it, three quiet words: **"No error. Nothing fails."**
The hook is the *absence* of an alarm. That earns the next 18 seconds.

## Key moments (the middle)
- Five ML model chips appear one by one — all showing a calm green "passing" state — then, on a
  beat, their values flip to `null` and the green drains to grey. Nothing turns red. Nothing alerts.
- The real PR comment header lands: **"⚠️ ML blast radius: 2 critical, 1 high, 2 medium"**
- The critical finding card for `churn_model_v3`, with the actual lineage path animating
  left-to-right: `customers.customer_since → days_since_signup → churn_model_v3`
- The differentiator line, held longest of anything in the video:
  **"trained on the changed column"** — the distinction no generic lineage view gives you.

## Outro / punchline
The five greyed model chips sit in the dark. The Blastradar name resolves.
Final line: **"Know what breaks. Before you merge."**

## User flow worth showing
Entry → key action → result, as a reviewer actually experiences it:
1. **Entry** — a data engineer deletes one column in `models/marts/customers.sql`.
2. **Key action** — they open the PR; Blastradar walks DataHub's column-level lineage downstream.
3. **Result** — the PR comment appears *before merge*, ranking 5 impacted models by severity and
   naming which were **trained** on the column vs. which only read it at inference.

The centerpiece scenes (3 and 4) are the product doing its thing — the real rendered PR comment —
not a diagram describing it.

## Tone
- Preset: `polished`
- Creative direction: quiet, premium incident-report film — restraint as the creative choice
- Interpretation: 4 scenes, long holds, slow crossfades. No exclamation, no hype, no rapid cuts.
  The threat is communicated by calm and silence, not by urgency. Type is light-weight with
  generous letter-spacing; the only saturated color in the film is the severity red, used sparingly
  so it actually lands.

## Format: landscape — 1920x1080
## Duration: 20s target

## Visual identity (from the project)
The project ships no website or CSS, so identity is derived from where its output actually lives —
a GitHub PR comment on a dark theme — plus the one real brand color in the repo (the purple
`Narrate` node in the README's mermaid pipeline diagram).

- Background: `#0d1117` (GitHub dark canvas — the PR comment's native home)
- Surface / card: `#161b22` with `#30363d` borders
- Accent: `#7c3aed` (purple — taken from the README mermaid `Narrate` node, `style F fill:#7c3aed`)
- Critical: `#f85149` · High: `#d29922` · Medium: `#e3b341`
- Text: `#e6edf3` primary, `#8b949e` secondary
- Display font: Inter (light/medium, generous tracking)
- Body/code font: JetBrains Mono — authentic; this is a CLI that reads SQL and writes markdown
- Strongest visual element: the rendered PR comment with its severity blocks and the
  `→ days_since_signup →` lineage path

## Share copy (draft)
Deleting a column doesn't throw an error — it just quietly poisons every ML model trained on it.
Blastradar reads your data PR, walks DataHub's column-level lineage, and tells you which
production models you're about to break. Before you merge.

## Audio direction
- Role: sparse professional accents over a restrained bed — the audio must never become a thriller
- Music: `happy-beats-business-moves-vol-9-by-ende-dot-app.mp3` (114.84 BPM), used at low volume
- Music treatment: enter at ~0.8s under the hook, sit low (bed, not lead) through the film,
  gentle fade-out across the final 1.5s so the outro lands in near-silence (polished outro = silence)
- Music cue guidance: preset cue file read. Target strong cues at **6.34s** (the null-flip moment),
  **10.54s** (the blast-radius header lands), **12.65s** (the critical card arrives). Sequential
  reveals use every-other-beat spacing (~1.05s apart at this tempo), never the raw 0.52s grid —
  the model chips and finding cards carry text and must clear the reading floor.
- Audio-reactive treatment: none. Restraint is the whole tone; no waveform bars, no pulsing glow.
- SFX posture: sparse. At most 3-4 cues in the entire film. Motion-matched only.
- Audio-coupled moments: the strike-through of the deleted SQL line; the flip of model values to
  `null`; the arrival of each severity card.
- Restraint rule: no alarm sounds, no risers, no impact stingers on the severity reveal. The film's
  argument is that nothing alarms you — an alarm sound would contradict the premise.

## Storyboard

### Scene 1 — The deletion — 5s
Dark editor pane, mono type, subtle line numbers. The `customers.sql` SELECT list is already on
screen, calm and grey. The single line `c.customer_since,    -- account-age driver for ML features`
is highlighted, gains a red `-` gutter and a deletion wash, and strikes through. Beneath it,
after a hold, light display type fades up: **"No error. Nothing fails."**
Sequential/interaction: yes — the deletion applies to the one line only (gutter marker, then wash,
then strike), a simulated diff being applied. Hold the hook line ~1.5s fully settled.
Audio intent: quiet, matter-of-fact. The bed enters underneath; the world is normal.
Audio-coupled idea: one dry, soft key/interface tick on the strike-through. Nothing dramatic.
Music: low bed, enters ~0.8s.
Transition mood: soft → Scene 2

### Scene 2 — The silence — 5s
Five model chips arrive one by one on the every-other-beat grid: `churn_model_v3`,
`reactivation_model_v1`, `churn_model_v1`, `churn_model_v2`, `ltv_model_v1` — each with a calm
green "serving" dot and a plausible feature value. On the 6.34s strong cue, every value flips to
`null` in unison and the green dots drain to grey. Crucially: **nothing turns red, nothing alerts.**
Caption holds: **"Five models keep serving. On nulls."**
Sequential/interaction: yes — 5 chips in, ~1.05s apart, then a single synchronized flip to `null`.
Audio intent: the drain. Absence where an alarm should be.
Audio-coupled idea: a soft collective interface cue on the flip — quiet, not a stinger.
Music: bed continues, unchanged — deliberately indifferent to the failure.
Transition mood: soft → Scene 3

### Scene 3 — Blastradar reads the PR — 6s
The GitHub PR comment composes itself on the dark canvas. First the real header lands on the
10.54s cue: **"⚠️ ML blast radius: 2 critical, 1 high, 2 medium"**. Then, on 12.65s, the critical
finding card for `churn_model_v3` arrives — severity dot in `#f85149`, owner `@ml-platform`,
tag `Tier1` — and the lineage path draws left-to-right beneath it:
`customers.customer_since → days_since_signup → churn_model_v3`.
The line **"trained on the changed column"** is the last element to settle and holds the longest
beat in the film (~1.6s). A second card (`reactivation_model_v1`, "reads it at inference only")
sits behind it, dimmer, to make the distinction visible.
Sequential/interaction: yes — header, then card, then the path drawing hop by hop, then the
trained-on line. Every-other-beat spacing; each text element clears its reading floor.
Audio intent: arrival and clarity. The one moment of resolution in the film.
Audio-coupled idea: one restrained card-arrival cue on the critical card. No alarm.
Music: bed lifts very slightly, then settles.
Transition mood: soft → Scene 4

### Scene 4 — Outro — 4s
The finding card recedes. The five model chips from Scene 2 return, still grey, small, in the dark.
**Blastradar** resolves in light display type with the accent `#7c3aed` as a thin underline rule.
Tagline settles beneath: **"Know what breaks. Before you merge."** Long hold on the empty space.
Sequential/interaction: none — a single settled composition, held.
Audio intent: near-silence. Confidence.
Audio-coupled idea: none. Deliberately unscored at the end.
Music: fade out across the final ~1.5s to silence under the tagline.
Transition mood: hold to end

**Total duration:** 5 + 5 + 6 + 4 = **20s**

**Music mood for this video:** restrained / professional bed (not upbeat — held low and indifferent)
**Audio summary:** A low, unbothered bed runs under the whole film and never reacts to the damage;
three sparse motion-matched cues mark the deletion, the null-flip, and the critical finding; the
track fades to silence for the outro, so the last thing the viewer hears is nothing at all.
