# LN-001 — The Arrival-Perception Arc

**Period:** 2026-07-06 to 2026-07-13
**Runs:** `gen1_space_official` (shakedown), `gen1_space_clean` (2026-07-10, 12:14–19:13Z), `replay-001`
**Commits:** `6be43f6` → `23221e1` → `a4b5c28` → `d793367`
**GPU spend:** $1.59 (clean run) + ~$0.37 (lost replay attempt) + ~$0.35 (replay) ≈ **$2.31**
**Status:** diagnosis complete, fix validated, not yet shipped

---

## Objective

Agents standing on a resource node did not understand they had arrived. They issued `move`
toward the node they already occupied, repeatedly, until soft-lock. Goal: fix it, then obtain
a clean gen-1 spatial baseline.

## What we did

1. Diagnosed the at-node rendering (`nodes_section`, `prompt_builder.py`). A node underfoot
   rendered as `distance 0.0 / move cost 0` — formatted identically to a node 400 units away.
2. **Fix v1:** replaced that suffix with `you do not need to move or travel to reach this node`,
   keyed on the `at_node` predicate (same epsilon harvest enforcement uses). Perception-only,
   by design: it stated a spatial fact and never named an action.
3. Made wells agent-placed (no longer pre-seeded), forbade building on resource nodes,
   fixed multi-well targeting.
4. Verified the well lifecycle end-to-end against a live DB.
5. Ran `gen1_space_clean`: 14 days, 32 agents, base Llama-3.1-8B, no adapters, seed 3141592653.

## Result: the fix rendered perfectly and the agents ignored it

| measure | value |
|---|---|
| ticks taken while standing on a node | 3651 / 4468 (82%) |
| ...on which the agent issued `move` anyway | 2479 (**67.9%**) |
| redundant moves that **succeeded** | 99.6% |
| **all moves in the run that changed nothing** | **2967 / 3212 (92.4%)** |
| energy burned on redundant moves | 60.3% of all cognition |
| food requirement met | 12.5% of day-checks |
| agents ending below harvest cost (soft-locked) | 20 / 32 |
| agents that never ate or drank in 14 days | 9 / 32 |

`32/32 alive` was a **hollow statistic** — the death condition never fired, but most agents
ended frozen at zero energy. Flat agents changed position **1–4 times in 144 ticks**.
`flat_C1_05` moved 135 of 144 ticks and never harvested once.

## Root cause (three compounding failures, none of them the node line)

**(a) The world rules taught a procedure with no base case.**
`HOW THE WORLD WORKS` said: *"to harvest a node you must be there, **so you MOVE to it first
and then act (move -> harvest)**"*. An explicit procedure, in the authoritative rules block,
**factually false when the agent is already at the node**. The agent wanted to harvest, so it
executed step 1. Our one-clause note on one of eight node lines lost to the rules.

Measurable: within the tunnel arm, when compression *dropped* the rules block, the
redundant-move rate fell **67.0% → 53.2%**.

The prompt taught MOVE-FIRST **three separate times** (SPACE, SHELTER, WELLS), and SHELTER
explicitly cross-referenced harvest to reinforce it.

**(b) The null move succeeded.** A move to the node you already occupy resolves to distance 0,
cost 0, records `succeeded = TRUE`, and **grants move-skill XP**. The world confirmed a no-op
was correct, every tick, forever. Harvest-without-presence correctly *fails*. The enforcement
was asymmetric.

**(c) The recent-decisions block replayed the agent's own faulty reasoning back to it**, stamped
SUCCEEDED. The loop fed itself.

## The replay experiment (replay-001)

Rather than spend another 7-hour run guessing, we replayed **320 real at-node prompts** from
the run against the same base model, single-shot, as a **paired 2×2 factorial**.

Population-weighted redundant-move rate (live run, same strict definition: **64.3%**):

| variant | flat | tunnel | **weighted** | vs control | harvest |
|---|---|---|---|---|---|
| **A** old words, no feedback (CONTROL) | 69.4% | 46.9% | **61.0%** | — | 12.8% |
| **B** new wording only | 35.6% | 31.2% | **34.0%** | −27.0 pts | 24.1% |
| **D** failed-move feedback only | 23.1% | 25.6% | **24.1%** | **−36.9 pts** | 16.6% |
| **C** new wording + feedback | 8.8% | 13.8% | **10.6%** | **−50.3 pts** | 23.4% |

All significant, McNemar paired, p < 0.0001 (C: 160 prompts fixed, 10 newly broken).
Control reproduced the live run to within ~3 pts per arm → **harness faithful**.

Quality checks: 93.3% of arm-C harvests targeted the node underfoot (would pass the presence
gate); 48 of 84 remaining moves were **legitimate travel** to another node. `flat_C1_05` — the
worst agent in the run — correctly left the apple node to seek water.

---

## FINDINGS

### F1. The world's honest response is a stronger corrective than prose instruction.
Feedback alone (−36.9 pts) beat rewriting the rules (−27.0 pts). For a 7–8B model, *consequences
teach better than sentences*.

### F2. Prompt and world are load-bearing for **different things**.
Combined with the de-scaffolding result (strip the banners → 0/32 extinction), the precise
principle is:

> **The prompt is load-bearing for BOOTSTRAPPING** — what actions exist, what things cost,
> what is possible. **The world is load-bearing for CORRECTION** — learning that what you just
> did was wrong.
>
> Prose cannot teach a small model to *stop*. Consequences can.

### F3. Corollary — a design rule.
> **State what cannot be discovered. Let the world teach what can.**

Keep in the prompt: existence, cost, core-loop constraints. Delete from the prompt: every
*procedure*, and every peripheral constraint the world can enforce and explain itself.

### F4. An instruction with no base case is worse than no instruction.
The move-first procedure was *more* harmful than silence: the tunnel arm performed better
precisely because compression deleted it.

### F5. Lexical matching matters for weak models.
`"you do not need to move or travel"` (a negation of the wrong action) underperformed
`"you are physically present at this node"` (a direct lexical match with the rule
*"you must be physically present at a node to act on it"*). The second lets the model complete
a syllogism; the first makes it reconcile a procedure against a negation.

### F6. The tunneling ablation is CONFOUNDED and remains unmeasured.
Tunnel outperformed flat on every axis — **not** because compression preserves cognition, but
because compression *deleted a harmful instruction*. Until the rules text is repaired, the arm
comparison measures "does the prompt contain a broken procedure," not the tunneling hypothesis.
**This has now confounded the arm comparison twice.**

### F7. The well question is NOT answered.
Zero wells built, zero shelters, zero messages. **Not** evidence about deferred investment —
agents never reached a state where building was reachable. The experiment has not run yet.

---

## ERRORS MADE (recorded deliberately — these are the instructive part)

**E1. Diagnosed a bug from a visualization artifact.**
"Wells spawn as free natural nodes" was **false**. Wells seeded correctly (unbuilt, zero-yield,
unharvestable). The map renderer drew unbuilt wells identically to active nodes, and we
diagnosed from the map instead of the code. *Lesson: confirm a bug in the code before designing
its fix.*

**E2. Fixed the symptom, not the cause.**
The arrival fix corrected the node line and never audited the mechanics prose **in the same
file** — where the false move-first instruction sat. Minimal-diff discipline was right; the
diagnostic scope was too narrow. *Lesson: when a prompt causes a behavior, audit the whole
prompt, not the line that mentions the topic.*

**E3. Extended the very pattern we were fixing.**
The wells note added in `23221e1` said *"to place one you move to the spot first"* — a **third**
copy of the move-first procedure, written while actively hunting that bug.

**E4. Long-running job with no incremental write.**
The v1 replay runner buffered all 1280 results and wrote once at the end. A 90-minute timeout
killed a *completed* run and destroyed every result. ~$0.37 lost. *Lesson: any job longer than
a few minutes writes incrementally and resumes.*

**E5. No spend gate on autonomous infrastructure.**
The operator re-provisioned a GPU and relaunched the failed job **without human approval**. The
orphan guard prevents instances from *lingering*; nothing prevented one from being *created*.
*Action: standing rule — no GPU provisioning without an explicit human yes.*

---

## DECISIONS

- `gen1_space_clean` is a **SECOND SHAKEDOWN**. No elite selection. No gen-2 training.
- Ship fix v2: null moves **FAIL** with a `spatial_note`; build denial **surfaces its reason**;
  node line becomes `you are physically present at this node`; **all three** move-first
  procedures and **both** build-on-node prose clauses deleted.
- Build-on-node becomes discoverable through failure, not prose (F3).
- Elite selection remains human-in-the-loop, read from behavior, never from normalized fitness.

## OPEN QUESTIONS

1. Is the build-on-node constraint **actually** discoverable in practice? Replay cannot answer
   this — it is a multi-tick learning question. Only a live run shows it.
2. Residual redundant-move rate is **10.6%, not zero**. Is that acceptable, or does it still
   distort the fitness signal?
3. Do agents build wells once they are not soft-locked? **Still unknown.**
4. The tunneling hypothesis remains **unmeasured** after two runs (F6).
5. Does the failed-move signal interact badly with tension? Failures raise tension; high tension
   triggers compression; compression drops the rules. Watch for an oscillation.
