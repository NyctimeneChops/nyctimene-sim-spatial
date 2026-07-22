# LN-004 — line2_gen1: Two Predictions Refuted, and the Tunneling Result Confirmed Robust

**Run:** `line2_gen1` · commit `189659e` · **seed 3141592653 (THIRD run in the controlled series)**
**Config:** Llama-3.1-8B base, no adapters, Line-2 substrate, 14 days, 32 agents
**Result:** 4496 actions, ratio 1.0, 32/32 alive, **0 sleep actions (substrate confirmed applied)**, $1.44
**Verdict:** the substrate change did NOT do what was predicted. That is the finding.

This is the third run in an identical world (`gen1_space_clean` → `gen1_space_v2` → `line2_gen1`),
seed 3141592653 throughout, each isolating one change: v1 prompt → v2 arrival fix → Line-2 substrate.

---

## THE CONTROLLED SERIES

| metric | v1 (clean) | v2 (arrival fix) | **L2 (substrate)** |
|---|---|---|---|
| rest rate | 8.1% | 37.7% | **35.3%** |
| redundant-move (at-node) | 64.3% | 4.7% | **4.6%** |
| consumed (eat+drink) | 205 | 429 | **390** |
| harvests | 255 | 632 | **581** |
| food met | 12.5% | 24.5% | **23.1%** |
| water met | 29.3% | 48.8% | **48.1%** |
| median end energy | 0 | 12,597 | **14,644** |
| soft-locked (<1200) | 20/32 | 0/32 | **7/32** |

Note the v1→v2 rest JUMP (8.1% → 37.7%): the arrival fix, by making the null move FAIL, pushed
agents toward rest as the always-affordable fallback. That was invisible until now.

---

## PREDICTIONS vs OUTCOME (LN-003, committed to git BEFORE the run)

| # | prediction | outcome | verdict |
|---|---|---|---|
| P1 | rest rate collapses from 37.7% | 37.7% → 35.3% (−2.5) | **REFUTED** |
| P2 | consumption rises from 429 | 429 → 390 (−39) | **REFUTED** |
| P3 | tunneling advantage shrinks | **unchanged** | **REFUTED** |
| P4 | redundant-move ≤ ~5% | 4.6% | CONFIRMED |

**Two of the four predictions failed, and the most important one (P3) failed decisively.**
This entry exists to record that honestly, per the append-only convention. The pre-registration
was committed to git at 189659e before the run; the refutation is real, not retrofitted.

---

## F12 (MAJOR). The tunneling advantage is REAL and ROBUST — it was never the sleep-lie artifact.

Claude claimed FOUR times this session that the tunneling result was "contaminated" because
compression deleted the false "Sleep always reduces tension" line. **The data refutes that claim.**
The sleep lie was removed from BOTH arms. The tunnel advantage is unchanged:

| | v2 flat | v2 tunnel | **L2 flat** | **L2 tunnel** |
|---|---|---|---|---|
| food met | 4.3% | 44.7% | 1.4% | **44.7%** |
| consumed | 125 | 304 | 87 | **303** |
| median tokens | 302,966 | 213,936 | 302,049 | **186,450** |
| end energy | 7,030 | 24,460 | 2,458 | **25,846** |

Tunnel food-met is **44.7% in both runs, to the decimal.** Consumption 304 → 303. The effect did
not shrink; it is invariant to the substrate change. **This is a STRONGER result than the "clean
measurement" that was hoped for:** the tunneling advantage survived an intervention specifically
predicted to reduce it. Compression under stress produces better resource behaviour AND ~38% fewer
tokens, and this is now demonstrated across two different substrates in an identical world.

The mechanism (per LN-002 F4) stands: the flat arm gathers as much as the tunnel arm (harvest 244
vs 337, same order) but does not CONSUME it (87 vs 303). Prompt bloat buries the "eat what you are
holding" signal; compression surfaces it. That mechanism is orthogonal to the sleep lie, which is
why removing the lie changed nothing.

## F13. Why the rest rate did NOT collapse: the prompt was never the main cause.

Predicted: removing "Sleep always reduces tension" collapses resting. It did not (37.7% → 35.3%).

The reason: agents rest because tension is high, and tension is high because they are not eating —
NOT because a sentence told them sleep helps. In L2, 84.6% of rests still cite tension relief.
But now there is a twist that vindicates the invariant:

- In v2, rest did **nothing** to tension.
- In L2, rest **does** drain tension (1.0/tick) — but hunger/thirst refill it at 1.5–2.0/tick.
- **Median tension change the tick after a rest: +0.0. Only 1.8% of rests are followed by lower
  tension.**

**The invariant works exactly as designed.** You cannot rest away hunger; arithmetic outruns
intent. The agents try anyway, every time, and the world correctly refuses. The rest behaviour is
downstream of the eating failure, and no prompt edit could fix it because the prompt was never the
cause. This is the arrival-bug lesson one level deeper: *when a behaviour has a structural cause,
changing the prompt that mentions it does nothing.*

Also observed (the acquire/consume confusion, third variant): an agent at **30000/30000 energy**
resting "to maintain my energy reserves." Banking a resource that is already maxed.

## F14 (process). A refuted pre-registration is worth more than a confirmed one.

P3's failure corrected a claim Claude had asserted four times and was confident in. Without the
pre-registration committed to git, that error would have been quietly absorbed ("the tunnel result
is a bit contaminated") instead of decisively refuted ("no, it is robust across substrates"). The
discipline of writing the prediction down first, in version control, is what converted Claude's
repeated wrong intuition into a hard result. **Keep pre-registering. The value is highest exactly
when the prediction is wrong.**

---

## WHAT THIS MEANS FOR THE PROGRAM

- **The core claim is now well-supported.** Tunnel ablation produces materially better behaviour at
  ~38% lower token cost, demonstrated across two substrates in one controlled world. This is the
  result the survival sim existed to test, and it held.
- **The pipeline is validated** (pilot DPO already showed gen-2 adapters beat base). Heredity has
  not been run on this line, but the mechanism it would train on is real.
- **The remaining failure modes (resting, acquire≠consume) are STRUCTURAL, not prompt bugs**, and
  are downstream of the eating failure. They are the honest limits of an 8B under this pressure.

## OPEN QUESTIONS CARRIED FORWARD

- **The acquire≠consume failure is the ROOT.** Resting, hoarding, and low food-met all descend from
  it. It is the highest-value thing to understand next, and a candidate for the replay harness (a
  world-side signal: "you hold 26 water and you are thirsty" is perception, not instruction).
- **Does the tunnel advantage transfer to a real work task?** That is the actual test the sim was
  instrumentation for. F12 says the effect is real and robust; the next real question is whether it
  survives leaving the survival domain entirely.
- **F8 (materials/building) unresolved**, deferred to a scarcity line.

## BUDGET

**$1.62 of Vast credit remains.** One more short run or a modest adapter job, not both. Gen-2 on
this line would roughly exhaust it. This is a natural pause point: the program is stopping on a
confirmed core result, not mid-line.
