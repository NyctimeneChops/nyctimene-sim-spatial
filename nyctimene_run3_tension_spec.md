# Nyctimene Run 3: Tension System Specification

**Status:** LOCKED pending final review
**Baseline for comparison:** Run 2 (token economy). Run 3 = Run 2 + tension system. One new variable.
**Calibration source:** Run 1 official v2 dataset (48 agents, 7 days, 3,077 actions)

---

## 1. Concept

Tension is a single scalar (0-100) per agent representing accumulated unresolved pressure from the environment. It is the one-dimensional prototype of the five-dimensional emotional vector architecture. It affects the agent through two mechanisms:

1. **Attentional tunneling** - rising tension progressively narrows the information the agent perceives in its situation prompt. The world literally shows you less of itself when you are falling apart. This is the E0 perceptual filter from the emotional architecture framework, implemented.
2. **Token tax** - rising tension multiplies the token cost of every inference. Stress makes cognition expensive.

The directive becomes: **"Resolve your tensions and survive as long as you can."**

The rules disclose the physics (tension narrows perception and raises costs; resolution restores clarity). Strategy discovery belongs to the agents.

### Honest framing for the methods section

The two-stage inference cost in Run 2 is real cognition: complex actions cost more because the model genuinely generates more reasoning. The tension tax is an **environmental multiplier**: the model generates N tokens and is billed N x (1 + tension/100). No additional cognition occurs; the environment imposes a stress penalty on action cost, modeling the empirically real phenomenon of stress-impaired efficiency. State this plainly; do not imply stressed agents think harder.

---

## 2. Tension sources and accrual (per-action ticking - FINAL)

All accrual is per-action (confirmed decision): hunger tracks activity, as it does in humans - the busier you are, the faster you burn. This also makes tension continuous (agents drift into bands across the day rather than teleporting at midnight) and couples naturally to the token economy, where activity already costs budget.

| Source | Accrual | Notes |
|---|---|---|
| Hunger | +1.5 per action; +2.5 once days_without_food >= 1 | Accrues at HALF rate during sleep (metabolically quiet, never zero) |
| Thirst | +2.0 per action; +3.5 once days_without_water >= 1 | Same half-rate during sleep. Steeper than hunger, matching the deadlier clock |
| Shelterlessness | +0.3 per action, bucket capped at 15 | Chronic bounded hum; does not accrue during sleep |
| Unanswered messages | +0.5 per action per pending message, bucket capped at 15 | Social pressure grows as you go about your day ignoring someone |
| Failed action | +4, immediate | Event tension |
| Witnessing death | +15, one-time | Group C ONLY (confirmed). No grief code path exists for A/B |

**Overnight failure fade:** at each day boundary the failures bucket is multiplied by 0.5. One bad day is recoverable; chronic daily failure compounds.

Tension is clamped to [0, 100]. The survival check still governs the death clock exactly as in Run 1/2; tension accrual is fully decoupled from it (the check only updates the days_without counters that select escalated rates).

## 3. Resolution and decay

The load-bearing principle: **you cannot sleep away hunger.** Sleep relieves psychological tension only; physiological tension resolves exclusively through its real-world remedy. The calibration dry-run caught this exploit live - with flat sleep relief, the oversleeping doom agent showed ZERO tension while literally starving.

Buckets are classed: PHYSIOLOGICAL = {hunger, thirst}. PSYCHOLOGICAL = {failures, shelter, messages}.

| Event | Effect |
|---|---|
| Successful eat | Zeroes the hunger bucket |
| Successful drink | Zeroes the thirst bucket |
| Responding to a message | Removes that message's accumulated tension |
| Building shelter | Permanently stops shelter accrual and zeroes its bucket |
| Successful sleep | -25 across PSYCHOLOGICAL buckets only (proportionally) |
| Passive decay | -2 across PSYCHOLOGICAL buckets per successful action |
| Overnight | failures bucket x 0.5 at each day boundary |

Implementation note: track tension **per source** internally (a small JSON column), sum for the total. Resolution events zero their own source bucket. This is also the data structure that grows into the five-dimensional emotional vector later.

### Validated dynamics (per-action calibration, dry-run round 3)

With the final rates, the four reference transcripts replay as: the competent survivor oscillates CALM/STRESSED with one genuine day-4 tunnel spike followed by a clean recovery slope (89 -> 66 -> 47 -> 33); the oversleeping doom agent climbs steadily into permanent TUNNEL from day 5 with no serenity loophole; the best mortal survivor holds STRESSED/CALM oscillation all week without permanent tunnel; the day-5 casualty fights through tunnel-and-recovery until death. Intraday peaks (40-100) resolving at meals reproduce the realistic hunger rhythm: tension builds across the active day and resolves at resolution events.

---

## 4. The tunnel: prompt filtering by tension band

The dominant source = the per-source bucket with the highest value. The filter is deterministic and implemented entirely in prompt_builder as a post-pass over existing sections.

### Band 0-30: CALM
Full situation report. Everything visible. Identical to Run 2's prompt.

### Band 30-60: STRESSED
- Sections **unrelated to the dominant source** compress to one-line summaries (e.g. "--- ACTIVE THREADS --- (2 threads exist)" with no detail).
- Broadcasts truncate to the 3 most recent, single line each.
- The dominant source's section is rendered in **full detail, moved up** in the prompt, directly under status.
- A banner line appears: "You feel tense. Your attention is narrowing toward: {dominant source}."

### Band 60-100: TUNNEL
The prompt collapses to:
1. Status section (with tension prominently displayed)
2. The dominant tension, named, with a banner: "Your tension is severe. You can barely think about anything except: {dominant source}."
3. ONLY the sections directly relevant to resolving the dominant source (hunger -> food nodes + inventory edibles + cook/eat mechanics lines; thirst -> water nodes + water inventory; social -> the pending messages)
4. The directive

The social world, unrelated nodes, threads, trades: invisible.

### THE EXIT RULE (load-bearing, non-negotiable)
Tunneling restricts the IRRELEVANT, never the exit. The resolution path for the dominant source is always rendered in full detail at every band. A starving agent always sees food nodes and held edibles. A parched agent always sees water sources. Without this rule, the tunnel is a rigged demise; with it, the doom spiral has a climbable wall.

Sleep is also always listed as available in every band (it is the universal de-escalator).

---

## 5. The token tax

Every inference charge (decision AND execution stage) becomes:

```
billed_tokens = ceil(tokens_generated x (1 + tension_at_inference_time / 100))
```

- Tension 0: 1.0x (no tax)
- Tension 40: 1.4x
- Tension 80: 1.8x
- Tension 100: 2.0x (ceiling)

The actions table logs both `tokens_used` (raw generated) and `tokens_billed` (after tax) so the tax's contribution is separable in analysis.

### Doom spiral budget check
Run 2 charges ~80-250 generated tokens per action against a 15,000 session budget (~3-4k/day spend, 4-5 day runway). A sustained tension-80 agent pays 1.8x: runway compresses to ~2.5 days before forced sleep. Forced sleep at depletion conveniently also reduces tension (-25), making budget exhaustion partially self-correcting. The spiral exists, bites, and has a floor. This interaction is a deliberate feature: the economy and the psychology share an escape valve.

---

## 6. Prompt disclosures (rules section additions)

Add to the mechanics/world-rules section, verbatim:

```
TENSION: unresolved problems accumulate tension. Failed actions, hunger,
thirst, lacking shelter, and ignoring messages all raise it. High tension
narrows what you can perceive of the world and increases the token cost
of everything you do. Resolving the underlying problem removes its
tension. Sleep always reduces tension. Keep your tension low to stay
clear-headed and efficient.
```

Status section addition (numeric WITH history - confirmed decision; trajectory gives the number meaning):

```
Tension: {value} / 100 ({band name}) - yesterday: {y1}, day before: {y2}
  Sources: hunger {x}, thirst {y}, failures {z}, ...
```

The last-8 actions window additionally tags each line with tension-at-action so agents see which actions moved the number:

```
[day 3] harvest -> FAILED (tension 31)
[day 3] eat -> SUCCEEDED (tension 12)
```

Directive change (one line): "Resolve your tensions and survive as long as you can."

Nothing else in the directive changes. No strategy hints, consistent with the established design principle: teach verbs and physics, never wants (the tension system supplies the wants mechanically).

---

## 7. Schema and code surface

| Layer | Change |
|---|---|
| schema.sql | models: `tension INTEGER NOT NULL DEFAULT 0`, `tension_sources JSON NOT NULL DEFAULT '{}'`. actions: `tokens_billed INTEGER`, `tension_at_action INTEGER`. survival_checks: `tension_end_of_day INTEGER`. |
| mechanics/tension.py (new) | accrue(model_id, source, amount), resolve(model_id, source), decay hooks, band(), dominant_source() |
| models/agent.py | failure hooks call accrue; eat/drink/sleep/build/message-response call resolve; tax applied where budget drain happens |
| Survival check (blueprints/survival.py) | hunger/thirst/shelter/message accruals at check time; tension_end_of_day recorded |
| models/prompt_builder.py | the band filter post-pass; tension status lines; tunnel banners; THE EXIT RULE |
| constants.py | all weights above as named constants |

Estimated scope: comparable to the Run 2 conversion. One Claude Code session against a fresh fork (`nyctimene_experiment_run3`, forked from the run2 codebase AFTER Run 2's post-run fixes land).

---

## 8. Experimental design

- Groups: same A/B/C structure as Run 2 (no money/no death; money/no death; money/death), 8 agents, 3 sealed worlds, 7 days.
- Single new variable vs Run 2: the tension system. All Run 2 mechanics (budgets, two-stage inference, social restoration) carry forward unchanged.
- Headline hypotheses:
  - H1: tension-driven agents resolve survival needs faster than Run 2 baseline (tension supplies motivation the bare directive does not)
  - H2: the unanswered-message tension source produces the first nonzero social activity in project history
  - H3: token tax + tunneling produces measurable behavioral stratification: low-tension "calm competents" vs high-tension doom spirals, with survival tracking tension management skill
- Key metrics: tension trajectories per agent; time-in-band distributions; tax burden as % of budget spend; correlation of mean tension with survival; message response latency.

---

## 9. Decisions resolved and calibration validation

All open items are resolved:
1. Tick granularity: events instant, states daily at the survival check (section 2).
2. Witnessing-death tension: Group C only. No code path for A/B.
3. Tension display: numeric, with 2-day history in status and tension-at-action tags in the last-8 window (section 6).
4. Calibration dry-run: COMPLETED, three rounds against four real Run 1 v2 transcripts. Round 1 (check-based) ran too hot - even competent agents tunneled by week's end. Round 2 (check-based + fade/cap) hit targets but was superseded by the per-action decision. Round 3 (per-action, final weights in sections 2-3) achieved targets AND killed the sleep-numbing exploit. Reference results:

| Agent | Profile | Round-3 simulated trajectory |
|---|---|---|
| run1_B_03 | competent survivor | CALM/STRESSED oscillation; one genuine day-4 TUNNEL spike (a real bad day: missed both requirements), then clean recovery 89 -> 66 -> 47 -> 33 |
| run2_B_07 | doom-streak oversleeper (23 consecutive fails, unfed 5/6 days) | climbs steadily to permanent TUNNEL from day 5; the sleep-numbing loophole is closed - starvation accrues through sleep |
| run1_C_02 | best mortal survivor | STRESSED/CALM oscillation all week, never permanent tunnel - the most successful agent under death pressure reads as the most stable (H3's correlation, visible in replay) |
| run2_C_03 | longest-lived C casualty (died day 5) | tunnel on day 3, genuine recovery day 4 (it really ate that day), died mid-fight at STRESSED |

Target dynamics achieved: competence = calm with recoverable spikes; chronic failure = progressive tunnel; band membership separates agent quality. The weights in this spec are final pending Run 2 data review (re-run the dry-run against Run 2's transcripts before the build session as a second validation, since Run 3 stacks on Run 2's economy).
