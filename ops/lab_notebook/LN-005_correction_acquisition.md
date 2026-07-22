# LN-005 — Correction: the Flat-Arm Failure Is ACQUISITION, Not Consumption

**Date:** 2026-07-13
**Type:** correction + reframe. Supersedes LN-002 F4. Reframes the tunneling result (F12).
**Trigger:** Chops disputed the consumption diagnosis before spending on heredity. The data agreed with Chops.

---

## What was wrong

LN-002 **F4** claimed: *"Both arms gather the same resources; only the compressed arm consumes them.
The full prompt buries the signal that the need is already satisfiable from inventory."* The
implied fix was "teach eat-what-you're-holding."

This was inferred from harvest **counts** (flat 244, tunnel 337, same order of magnitude) without
checking harvest **composition**. Counts are not mix. The claim is false.

## The data (line2_gen1, verified)

| | flat | tunnel |
|---|---|---|
| harvest that is WATER | **75.0%** (183) | 51.6% (174) |
| harvest that is FOOD | **22.5%** (55) | 46.0% (155) |
| successful EATS (16 agents, 14 days) | **3** | 110 |
| successful drinks | 84 | 193 |
| eat:drink ratio | **0.04** | 0.57 |
| food requirement met | **1.4%** | 44.7% |
| water requirement met | 31.2% | 64.9% |

**The flat arm ate 3 times in 14 days across 16 agents.** Not because it hoarded food and refused
to eat it — because it **never harvested food to hold** (median food in inventory: 2.0). It
fixated on the river, drank adequately, and starved.

## F15 (corrected). The flat-arm failure is ATTENTION ALLOCATION across competing needs.

Without ablation, the model locks onto a single salient need (thirst → the river) and harvests it
to the exclusion of the other need (hunger), then starves while adequately hydrated. "Eat what you
are holding" is vacuous: there is nothing in hand to eat. The bottleneck is **what the agent
chooses to pursue**, upstream of any consume-vs-acquire decision.

## F16 (reframe, MAJOR). This is a REASONING result, not a survival result — the cleanest yet.

Same base model, same world, same seed 3141592653. The only variable is ablation. And:

- **un-ablated (flat): tunnels on ONE need.** 75% of harvest is water; food-met 1.4%.
- **ablated (tunnel): allocates across BOTH needs.** 46% food / 52% water; food-met 44.7%.

Ablation changed **what the model considered**, not merely how efficiently it executed. The flat
arm could not hold two competing needs in view at once; the tunnel arm could. This is direct
evidence that ablation **expands the reasoning frontier** — it is the strongest support the program
has produced for the core thesis, and it is a claim about *reasoning*, not about foraging.

Note the counter-intuition: the arm named "tunnel" is the one that does NOT tunnel on a single
need. "Tunnel ablation" compresses the *prompt* under stress; the behavioural result is that the
agent perceives its situation more completely, not less. The naming is historical; the effect is
the opposite of what the word suggests.

## Consequence for the hereditary experiment (this is why the correction matters NOW)

Chops's prediction is the correct one, and F15 explains why:

- **The flat arm will barely improve under heredity.** Its failure is not a policy it half-has and
  could sharpen; it is a failure to allocate attention that the elites do not cleanly encode as a
  transferable rule. Distilling "consume more" teaches nothing, because consumption was never the
  gap.
- **The tunnel arm is the arm to watch.** The hereditary question is whether inheritance moves the
  TUNNEL ceiling: does gen-over-gen the tunnel arm allocate across needs EARLIER and MORE COMPLETELY?
- **The metric is HARVEST COMPOSITION BALANCE (food:water ratio), not consumption.** That is where
  the reasoning difference lives, so that is where inheritance (if real) will show.

## The real experiment this is all instrumentation for (Chops, recorded verbatim in intent)

The agents, wells, rivers, eating are **symbols** — practice pieces for testing a model's reasoning
under ablation. The actual question:

> **Does ablation limit or increase the amount of reasoning a model can produce?**

The scarcity line (few rivers, low starting energy — a LATER, funded line) is the sharp test:
under real thirst pressure with the river exhausted, does the tunnel agent **reason its way to
building a well** (ablation EXPANDS reasoning → a novel instrumental action inferred under pressure)
or does it **obsessively harvest the empty river** (ablation COLLAPSES reasoning → perseveration on
the salient-but-exhausted option)?

**Both outcomes are results.** If it perseverates, that is not a failure of the experiment — it is
the signal that the ablation mechanism needs tuning before it is applied to real LLM work, which is
the entire point of testing it here first. We do not care about wells. We care whether ablation,
applied to a real model doing real work, expands or limits its reasoning. F16 is the first
affirmative evidence that it expands.

## Method note

This correction cost one offline query and happened BEFORE ~$9 of GPU spend on the wrong hereditary
metric. It is the second time this session that pausing to check a claim against the data (rather
than debating it, or trusting a prior finding) changed the plan. The first was F14 (a refuted
pre-registration). Pattern: **check the cheap thing before spending on the expensive thing.**


---

## CLARIFICATION (design, binding for all generations of this line)

Two points that must not be ambiguous in the record:

**1. Elites are pooled ACROSS THE ENTIRE ARM.** tunnel_C1 and tunnel_C2 are NOT separate lines.
They are one tunnel population; elites are selected from the combined 16 tunnel agents. Likewise
the flat arm is one population of 16. The C1/C2 split is a sealed-subworld replication detail for
variance, not a selection boundary. Any per-group table in earlier entries (LN-002, LN-004) is a
reporting convenience, not the selection unit. **Selection unit = arm.**

**2. The flat arm is a MEASURING STICK, not an experiment.** The tunnel arm is the entire object of
study. The flat arm exists only as an occasional reference point when interpreting the tunnel arm
(e.g. "tunnel allocates across needs; flat does not"). Flat-arm outcomes do NOT drive any decision,
do NOT gate any spend, and the health of the flat hereditary line is irrelevant. We do not train
flat to "work"; we run it so there is a baseline to point at. All hereditary questions, predictions,
and metrics are about the TUNNEL arm.

Consequence: the earlier concern about the flat elite pool being thin (2 of 16 fed themselves) is
NOT a problem to solve. It is expected, and it does not matter. The flat line can be degenerate; it
is still a valid measuring stick. Do not spend effort making the flat line healthy.
