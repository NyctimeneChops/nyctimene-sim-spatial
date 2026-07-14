# LN-002 — gen1_space_v2: The Fix Lands, and the Tunneling Hypothesis Is Confirmed

**Run:** `gen1_space_v2` · commit `5900fc4` · **seed 3141592653 (SAME seed as `gen1_space_clean`)**
**Config:** Llama-3.1-8B base, no adapters, 14 days, 32 agents, 4 sealed groups
**Result:** 4530 actions, decision-log ratio 1.0, 32/32 alive, $1.65, auto-teardown self-reaped
**Verdict: VALID BASELINE. Elite selection is unblocked.**

This was a **controlled comparison**: identical world (same node placements, same spawns) as the
failed `gen1_space_clean`. The only variable is the v2 fix.

---

## 1. The pre-registered test PASSED (and beat its own forecast)

Predicted from replay-001 **before** the run: ~10.6% redundant-move rate.

| | v1 (`gen1_space_clean`) | **v2** |
|---|---|---|
| **redundant-move rate (strict)** | **64.3%** | **4.7%** |
| — flat | 73.1% | 3.7% |
| — tunnel | 49.7% | 6.4% |
| total moves in run | 3212 | 439 |
| moves that were rewarded no-ops | 92.4% (SUCCEEDED) | 0 (now **FAILED**) |

**The single-shot replay predicted live behavior to within 6 points.** This validates the replay
methodology itself: prompt changes can now be tested for **cents** instead of a 7-hour run.
This is a permanent capability gain.

## 2. The soft-lock is GONE

| | v1 | v2 |
|---|---|---|
| agents soft-locked (<1200 energy) | **20/32** | **0/32** |
| agents ending at exactly 0 energy | 18/32 | **0/32** |
| median end energy | 0 | **12,597** |
| day-checks ending at 0 energy | 35.8% | 4.1% |
| successful harvests | 255 | **632** |
| agents that never ate or drank | 9/32 | **1/32** |
| agents that never harvested | 2/32 | **0/32** |

---

## 3. HEADLINE: the tunneling hypothesis is CONFIRMED — first clean measurement

The confound is finally gone. The move-first procedure that compression used to "helpfully"
delete no longer exists in **either** arm, so the arms differ only in compression.

| | flat | **tunnel** |
|---|---|---|
| median end energy | 7,030 | **24,460** |
| **food requirement met** | **4.3%** | **44.7%** |
| water requirement met | 36.1% | 61.5% |
| harvests | 313 | 319 |
| **consumed (eat + drink)** | **125** | **304** |
| median tokens / agent | 302,966 | **213,936 (−29%)** |

**Both arms harvest the SAME amount. The tunnel arm EATS what it gathers; the flat arm HOARDS it.**

Tunnel dominates on every axis — energy, food, water, consumption — **while spending 29% fewer
tokens.** Compression under stress does not merely preserve function. Here it *improves* it.

Per-group (sealed replicates, both directions consistent):

| group | alive | median energy | harvests | consumed |
|---|---|---|---|---|
| flat_C1 | 8/8 | 6,533 | 169 | 52 |
| flat_C2 | 8/8 | 8,461 | 144 | 73 |
| tunnel_C1 | 8/8 | 25,088 | 170 | **176** |
| tunnel_C2 | 8/8 | 22,956 | 149 | **128** |

---

## 4. The new dominant failure mode: ACQUIRE ≠ CONSUME

With the move bug gone, the next layer surfaced. In the agent's own words (flat arm, thirsty):

> *"I should harvest from the river node to replenish my water and **reduce my thirst level**,
> which is currently contributing to my high tension. **I have 26 water in my inventory, but I
> should aim to collect more** to be prepared for future actions."*

The agent is thirsty, is holding 26 water, and believes **harvesting more water reduces thirst**.
It has conflated *acquiring* a resource with *resolving* the need.

Evidence across the run:
- acquire (harvest): **632** vs consume (eat + drink): **429**
- 14/32 agents end **holding food** (190 unconsumed units) while food was met only 24.5% of the time
- 25/32 end holding water (424 units) while water was met 48.8% of the time
- only **0.26 meals per agent per day**
- **rest = 37.7% of ALL ticks**, chosen at a *median energy of 11,027* — they are not resting
  because they are broke

**This failure mode is ARM-DEPENDENT, and that is the mechanism behind Finding 3.** Under tunnel
compression, when hunger dominates, the prompt strips everything except food-relevant state — so
"eat the food you are holding" becomes salient. In the flat arm the same signal is buried in a
full-context prompt. *Prompt bloat causes the misallocation. Compression cures it.*

## 5. The well question: ANSWERED, structurally — and it is not what we asked

**Zero wells built. Zero shelters. ZERO BUILD ATTEMPTS — in either run.**

The cause is upstream of any reasoning about deferred investment:

> **Harvest attempts by node type, whole run: river 931, apple 391, grain 220, forest 61,
> hunting 32, potato 25, ROCK 0, ORE 0.**

**Agents never gather stone. Not once. Zero attempts across 32 agents × 14 days.** A well costs
3 stone + 2 wood, so it is *structurally unreachable* — not because agents cannot plan, but
because they never acquire the input.

### F8 (structural). The tension architecture cannot generate INSTRUMENTAL goals.
Attention is driven entirely by tension, and the tension sources are hunger, thirst, failures,
shelter, messages. **Rock generates no tension.** It addresses no felt need, so it never enters
the agent's attention, so stone is never gathered, so nothing that requires stone can ever be
built. The agents are pure terminal-goal machines. **"Zero wells" is not evidence about deferred
investment — that experiment has still never run.**

---

## FINDINGS

- **F1 (validated).** Single-shot replay predicts live behavior (predicted 10.6%, actual 4.7%).
  Prompt changes are now testable for cents. Use the harness before any prompt change.
- **F2 (confirmed).** *The world is load-bearing for correction.* Failing the no-op move, plus
  deleting the move-first procedure, took redundant moves from 64.3% → 4.7% and eliminated the
  soft-lock entirely.
- **F3 (MAJOR, new).** **The tunneling hypothesis is confirmed.** Compression under stress buys a
  29% token saving AND *better* survival (food met 44.7% vs 4.3%). It is not a cost/function
  tradeoff. It is a strict improvement.
- **F4 (new).** **Prompt bloat causes cognitive misallocation.** Both arms gather the same
  resources; only the compressed arm consumes them. The full prompt buries the signal that the
  need is already satisfiable from inventory.
- **F8 (new, structural).** **The tension architecture cannot generate instrumental goals.** No
  tension source points at materials, so materials are never gathered, so nothing is ever built.

## OPEN QUESTIONS

1. **Is F8 a bug or the finding?** If we want building to be possible, something must direct
   attention at materials. Options: a tension source for shelter/materials (already exists for
   shelter — but it evidently does not reach *rock*); making stone a byproduct; or accepting that
   an 8B under survival pressure is a pure terminal-goal machine and designing around it.
   **Do not "fix" this before deciding what it means.**
2. **Is the acquire/consume confusion fixable by the world, per F2?** Consuming from inventory
   already works. The agent simply does not do it. A world-side signal ("you are holding 26 water
   and you are thirsty") is *perception*, not instruction — a candidate for the replay harness.
3. **Rest is 37.7% of ticks at healthy energy.** Rational energy banking, or a degenerate default?
4. The tunnel arm's win is now clean, but is any of its energy advantage merely mechanical
   (cheaper inference → more energy) rather than behavioural? The consumption gap (304 vs 125)
   says behavioural, but this should be isolated.

## DECISIONS

- `gen1_space_v2` **IS a valid baseline.** Proceed to elite selection (human-in-the-loop,
  read from behaviour, per standing principle).
- The tunneling result (F3) is the strongest finding the program has produced. It is a genuine
  result about compressed cognition under pressure, not sim engineering.
- Do NOT chase the residual 4.7% redundant-move rate. It is below the predicted floor.

## ELITE CANDIDATES (read the traces before selecting — do not select from this table)

| agent | harvests | consumed | rest | end energy |
|---|---|---|---|---|
| tunnel_C2_08 | 43 | 22 | 23 | 21,304 |
| tunnel_C1_06 | 27 | **27** | 24 | 27,917 |
| tunnel_C1_02 | 30 | 24 | 33 | 24,676 |
| tunnel_C1_05 | 30 | 23 | 46 | 27,046 |
| flat_C1_03 | 35 | 17 | 29 | 9,000 |

Note `tunnel_C1_06`: harvest 27, consumed 27 — a **1:1 acquire-to-consume ratio**, the only agent
that fully closed the loop. Read its trace first.

---

## 6. WHY ARE THEY RESTING? (37.7% of all ticks) — the move bug, wearing different clothes

**Rest is a deliberate choice, not a parser artifact:** 1513 of 1710 rests (88.5%) were the model
explicitly emitting `rest`.

**They are NOT resting because they are sated.** Only 7.5% of rests follow an eat or drink.
**55.3% of rests follow ANOTHER REST.** And 55.5% of deliberate rests occur while hunger or
thirst is actively pressing.

**Their stated reason, clustered:**

| stated reason | share |
|---|---|
| **"reduce tension / stress"** | **84.9%** |
| "recover / regain energy" | 81.0% |
| "prepare / be ready" | 14.4% |
| **"nothing else to do"** | **0.2%** |

> *flat_C1_02:* "I should rest to replenish energy and **reduce tension**. My current energy level
> is **17,001, which is relatively high**, but I'm feeling **stressed with a tension level of 100**."

### The mechanism

The prompt's TENSION block says:

> *"Resolving the underlying problem removes its tension. **Sleep always reduces tension.** Keep
> your tension low to stay clear-headed and efficient."*

- **`_handle_rest` never touches tension.** The word "rest" does not appear in `tension.py`.
- **`sleep` IS a valid, free, listed action** in AVAILABLE ACTIONS.
- **Sleep count across 4530 actions: ZERO.** Not once, ever.

**The agents conflate REST with SLEEP.** They feel tension, read that sleep relieves it, and reach
for the semantically adjacent action they already have skill in. Then:

1. Rest is free and **ALWAYS SUCCEEDS**, so it **grants rest-skill XP**.
2. The prompt then displays **rest skill 29** — their highest skill by 6x (harvest 5, move 1).
3. Tension is unchanged. So they rest again.

### F9 (unifying). The world must never reward an action that cannot achieve what the agent believes it achieves.

This is the SAME STRUCTURE as the v1 null-move bug, and the same as the hoarding:

| failure | agent believes | reality | world's response |
|---|---|---|---|
| null move (v1) | "moving gets me to the node" | already there; nothing changes | **SUCCEEDED** + skill XP |
| hoarding | "harvesting water reduces thirst" | only drinking does | **SUCCEEDED** |
| resting | "resting reduces tension" | only sleeping does | **SUCCEEDED** + skill XP |

All three: an always-succeeding action that advances nothing, confirmed as correct by the world,
and reinforced by the skill display. **The always-affordable self-rescue floor is also a perfect
cognitive trap.**

### Arm asymmetry — compression wins a THIRD time

| | flat | tunnel |
|---|---|---|
| rest rate | **49.8%** of ticks | **25.3%** |

Compression drops the TENSION block that causes the confusion. This is the third distinct case of
tunnel outperforming because compression **deletes a misleading instruction** (after the
move-first procedure and the hoarding signal).

### DECISION: do NOT fix this before running the line

Running to plateau requires a **FROZEN ENVIRONMENT**. Changing the prompt now invalidates every
cross-generation comparison. The rest confusion becomes part of the world, and *"can selection
overcome a misleading environment?"* is a better experiment than a bugfix.

**PRE-REGISTERED FOR GEN-2:** rest rate FALLS (selection acts on existing variance:
tunnel 25.3% vs flat 49.8% proves the variance exists). **Sleep count stays at ZERO.**
If sleep appears without a prompt change, that is a genuine discovery result.
Selection fights two headwinds: the prompt implies rest relieves tension, and the skill system
actively rewards resting.
