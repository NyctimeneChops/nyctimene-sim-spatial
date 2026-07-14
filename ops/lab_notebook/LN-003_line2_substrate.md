# LN-003 — Line 1 Closed. Line 2 Substrate Design.

**Date:** 2026-07-13
**Decision:** Line 1 is CLOSED at gen-1. No gen-2. Start Line 2 with a new substrate and a fresh baseline.
**Status:** substrate change specified, not yet shipped.

---

## What a "line" is (terminology, now fixed)

A **line** is a sequence of generations in a **frozen environment**: gen-1 → gen-2 → gen-3 → …
until fitness plateaus. The only thing that changes between generations is the adapter.

**The environment is frozen for the life of a line.** Change the world mid-line and every
generation before and after the change becomes incomparable: you can no longer tell whether
fitness rose because the agents improved or because the world got easier. That is the whole
point of the construct.

**A substrate change therefore means a NEW LINE, which means a fresh baseline.**

- **Line 1** = the world of `gen1_space_official` → `gen1_space_clean` → `gen1_space_v2`.
- **Line 2** = the world defined below. New baseline. New generations.

## Why Line 1 is closed at gen-1 (no gen-2)

`gen1_space_v2` is a *valid* baseline and would have supported a legitimate hereditary run. It is
being abandoned anyway, deliberately:

1. **Line 1's world contains known false statements.** The prompt says *"Sleep always reduces
   tension"* — false; sleep touches only the psychological bucket, a median of 7 points out of a
   ~100 tension. Evolving agents here breeds partial competence at *coping with a lie*.
2. **The tunneling result is contaminated by that lie.** Flat rests 49.8% of ticks; tunnel 25.3%.
   Compression wins partly because it *deletes the false sentence*. This is the FOURTH time
   compression has won by deleting bad prompt text (move-first procedure, build-on-node prose,
   hoarding signal, now the sleep sentence). The headline claim cannot be made from a world where
   the uncompressed arm is reading something untrue.
3. **The substrate change was going to happen regardless.** Evolving 5+ generations in a world we
   are about to discard is a tax on the actual goal.

**The pipeline itself is already validated** (pilot DPO: gen2_flat +0.74, gen2_tunnel +0.95
preference accuracy on held-out pairs). Line 1 does not need to re-prove it.

---

## THE LINE-2 SUBSTRATE CHANGE

### Design principle

> **ONE RULE: every tension source is removed only by its own remedy.**
> hunger → eat · thirst → drink · failures → succeed · shelter → build · messages → read

No categories. No cross-soothing. This replaces the physiological/psychological split, whose
*entire job* was gating sleep relief. Remove sleep and the split is scaffolding around a hole.

### 1. Remove `sleep` entirely

Sleep was never used. **Zero sleeps in 4530 actions.** And the agents were right to ignore it:
sleep's −25 relief applies only to psychological tension, which had a median of 7, while
physiological tension alone (median 78.5, mean 143.7) already exceeded the cap of 100. **Sleeping
would have gained them nothing.**

The prompt's claim that sleep relieves tension is what produced the rest loop (see LN-002, F9):
agents reached for the semantically adjacent action they *did* have, and rested. 84.9% of rests
cited "reduce tension" as the reason. Rest does not reduce tension. **37.7% of every agent's life
was spent on this.**

### 2. Collapse the physiological / psychological categories

Keep the **per-source buckets** — the tunneling exit logic needs the dominant source to know what
to compress *toward*. It is the *category* that goes, not the buckets.

`TENSION_SUCCESS_DECAY` (−2, currently psych-only) is reassigned to the **failures** bucket alone:
succeeding *is* the remedy for failure. Everything else stays remedy-locked.

### 3. Rest relieves tension — slightly, uniformly, and safely

**Rationale (Chops).** Tension *narrows* perception and raises token cost. Without a way to reduce
it, tunneling is a **one-way door**: once stressed, the agent is locked into narrow perception and
the only exit is solving a problem it can no longer see the whole of. That is a model of panic,
not of focus.

With rest-relief, the agent faces a real strategic choice: **stay narrow** (cheap, focused, blind)
or **spend a tick to widen** (costly, but you can see the whole board again). *That is precisely
the question the real work-task test is about:* when should an LLM stay tunneled on the subtask
versus step back and reconsider the whole problem? **Rest is where that choice lives.** It is the
counterweight that makes tunneling a dial instead of a trapdoor.

**The invariant, enforced by arithmetic rather than by category:**

```
REST_TENSION_RELIEF = 1.0
assert REST_TENSION_RELIEF < min(TENSION_HUNGER_PER_ACTION,    # 1.5
                                 TENSION_THIRST_PER_ACTION)    # 2.0
```

| agent state | accrual/tick | rest relief | net |
|---|---|---|---|
| hungry | +1.5 | −1.0 | **+0.5 — the alarm still rises** |
| hungry + thirsty | +3.5 | −1.0 | **+2.5 — rises faster** |
| needs met | 0 | −1.0 | **−1.0 — drains to calm** |

**You cannot rest your way out of hunger** — not because a category forbids it, but because
**hunger fills faster than rest drains.** The invariant stops being a hardcoded gate and *emerges
from the rates*. The substrate philosophy applied to the substrate itself: minimal rules, the
property falls out.

### 4. NOT in this change (deliberately)

**Scarcity is deferred.** Reduced inference energy, reduced water, and meaningful shelter tension
would make wells and shelters valuable — but that is a *building* experiment, and building is not
the focus. The focus is tunnel ablation and heredity. Bundling six changes into one new world means
a misbehaving baseline cannot be attributed. Scarcity gets its own line, when building is the
question being asked.

Selection pressure survives without it: **elites are selected on EFFICIENCY, not survival.**

---

## PRE-REGISTERED PREDICTIONS FOR THE LINE-2 BASELINE

Recorded **before** the run, so the result is a test and not a rationalisation.

1. **Rest rate collapses** from 37.7%. It was driven by a false belief that is now gone.
2. **The freed ticks go to real actions** — harvest, eat, drink. Consumption rises.
3. **The tunneling advantage SHRINKS.** Much of it was compression deleting the sleep lie. If a
   tunnel advantage *survives* on focus alone, that is the real result and the first uncontaminated
   measurement of it. **If it collapses entirely, we needed to know that more than we needed a
   headline.**
4. Redundant-move rate stays at or below ~5%.
5. **GENUINELY OPEN:** does rest-relief create a *new* strategic behaviour — agents deliberately
   resting to widen perception before a hard decision? That would be the mechanic working as
   intended, and it has never been observed.

## OPEN QUESTIONS CARRIED FORWARD

- **F8 (LN-002) is unresolved and is now a Line-3 question.** Agents never gather stone (zero
  attempts, ever), so nothing requiring stone can be built. Two competing explanations remain
  untested: (a) *the environment is too easy* — no scarcity, so infrastructure has no value
  (Chops); (b) *the tension architecture cannot generate instrumental goals* — no tension source
  points at materials, so materials never enter attention (Claude). **Introducing scarcity is the
  experiment that decides between them.**
- **The acquire ≠ consume confusion is untouched by this change.** Agents still believe harvesting
  water reduces thirst. Watch whether it persists in the Line-2 baseline; it is a candidate for
  the replay harness.

---

## EMERGENT PROPERTIES (recorded after shipping the substrate change, 7605190)

Two properties fell out of the arithmetic and were not designed. Every rate below is verified
against constants.py and mechanics/tension.py.

### F10 (emergent). The physiological/psychological split re-derived itself from the accrual rates.

The hardcoded category was deleted. It reappeared as a CONSEQUENCE of the arithmetic, in a
sharper form than the original:

| source | accrual / tick | vs REST_TENSION_RELIEF (1.0) |
|---|---|---|
| failures | 4.0 | cannot be soothed |
| thirst | 2.0 | cannot be soothed |
| hunger | 1.5 | cannot be soothed |
| messages | 0.5 | CAN be soothed |
| shelter | 0.3 | CAN be soothed |

The old binary split classified `failures` as PSYCHOLOGICAL and therefore sleep-soothable. The
rates say otherwise: failures accrue at 4.0, four times the rest relief, so a track record of
failure cannot be rested away. **The emergent taxonomy is more correct than the hardcoded one it
replaced.**

### F11 (emergent). Proportional drain means a worry is only soothable once it dominates.

`rest_relieved()` scales every non-zero bucket by the same factor, so a bucket receives relief in
proportion to its share of total tension. A starving agent therefore cannot rest away its shelter
tension either: with hunger 80 and shelter 5, a rest drains 0.94 from hunger and only 0.06 from
shelter, while shelter still accrues 0.3. Shelter becomes soothable ONLY once hunger and thirst
are answered and it is the largest remaining source.

**You can only soothe your minor troubles once the major ones are answered.** This was not
designed. It fell out of one constant and a proportional drain.

Both findings are small, clean instances of the program's central thesis: minimal rules, and the
structure emerges rather than being specified.
