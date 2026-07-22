# LN-006 — line2_gen2: The Hereditary Mechanism Fails. Line 2 Closed.

**Run:** `line2_gen2` · commit `189659e` · seed 3141592653 · **first ADAPTER run of Line 2**
**Config:** base unsloth/Meta-Llama-3.1-8B + per-arm QLoRA adapters (pure-inheritance SFT), 14 days, 32 agents
**Result:** 3795 actions, ratio 1.0, 32/32 alive, adapters loaded and routed correctly, $1.91
**Verdict:** the hereditary mechanism, as built on existing fine-tuning methods, DOES NOT WORK. Line 2 closed.

---

## The pipeline is sound. The failure is methodological, not infrastructural.

This must be stated first, because it isolates the finding. Everything mechanical worked:
- The hard adapter-load gate PASSED: all 4 groups ran on a non-base adapter, correctly routed
  (tunnel adapter to tunnel groups, flat adapter to flat groups), verified from the run logs.
- The gate correctly REFUSED to start a first attempt that was missing peft, rather than silently
  serving base. The safety worked.
- The adapters produced COHERENT, on-policy output: 100% parseable action JSON, 66% unique
  reasoning. This is not a broken model emitting garbage.

So the failure below is not plumbing. It is the method.

## Gen-2 degraded on every behavioral metric (TUNNEL arm, the primary)

| metric | gen1 (base) | gen2 (adapters) | delta |
|---|---|---|---|
| rest (% of ticks) | 12.9% | **36.7%** | +23.8 |
| harvests | 337 | 171 | −166 |
| consumed (eat+drink) | 303 | 138 | −165 |
| eats | 110 | 46 | −64 |
| food requirement met | 44.7% | **18.8%** | −26.0 |
| water requirement met | 64.9% | 38.0% | −26.9 |
| harvest food-balance | 47.1% | 50.0% | +2.9 (flat) |

## F17. The pre-registered favorable-tail test FAILED cleanly.

The prediction (LN-003, committed to git before the run): pure inheritance may raise the average
rest rate via SFT mode-amplification, but the mechanic works if a FAVORABLE TAIL exists — any gen-2
agents resting less / eating more than gen-1's best — for selection to compound.

- gen-1 best: lowest rest **7%**, most eats **12**.
- gen-2 agents resting less than gen-1's best: **0 / 16**.
- gen-2 agents eating more than gen-1's best: **0 / 16**.
- median rest 12% → 37%; median eats 7 → 2.

**No favorable tail. The entire distribution shifted the wrong way.** The prediction is refuted.

## F18. SFT amplified the modal behavior, exactly as flagged.

The pure-inheritance corpus was 22% rest (the plurality action among the tunnel elites). SFT does
maximum-likelihood imitation, which is mode-seeking, so it amplified rest rather than transmitting
the elites' balance. The inherited policy is coherent but stuck in the acquire-without-resolve
trap this line has circled since LN-005: the gen-2 tunnel model EMITTED 801 eats but only 46
SUCCEEDED — it is trying to eat constantly and failing, because it inherited "rest / do less" and
stopped harvesting food to eat. Downsampling rest was declined (deliberately, to test pure
inheritance); the data now argues for it.

## F19. Cumulative pooling has NO RECOVERY PATH — it imports the degradation.

Pooling gen-1 + gen-2 tunnel agents by fitness (directly comparable, identical seed):

- **2 gen-2 agents crack the pooled top 8**: C1_02 (fit 31.3, **rest 70%, eat 2**) and
  C2_08 (fit 28.5, **rest 73%, eat 3**).
- So gen-3 would train on gen-1's balanced foragers PLUS two 70%-rest gen-2 agents that the scorer
  labels elite. That injects the degraded behavior into the gen-3 corpus. **Gen-3 would likely be
  WORSE than gen-2, not a recovery and not a neutral repeat.**

## F20. The fitness metric and the goal have DIVERGED.

The scorer's action-weighted fitness rewards volume of weighted actions, not need-resolution. Its
top gen-2 agent rests 70% and eats twice. **The selection metric now selects FOR the behavior being
bred OUT.** This was a latent blind spot at gen-1 (it ranked the best forager C1_06 last); in a
hereditary loop it becomes actively harmful, because the metric feeds the corpus.

---

## DECISION: Line 2 closed. The SFT-inheritance approach is abandoned.

Two pillars of the program are now ESTABLISHED as working:
1. **Tunnel ablation produces emergent reasoning** (robust across substrates: LN-004 F12/F16).
2. **The spatial substrate works** (agents navigate a 2D world, resolve needs, the mechanics hold).

The third pillar — **hereditary inheritance built on existing fine-tuning methods (SFT on elite
behavior, LoRA adapters as genome, volume-based fitness selection) — does not work.** The failure
is not a bug to patch. It is a mismatch between the tool and the goal:

- SFT does IMITATION, which is mode-seeking. Imitating a parent gives you the parent-plus-noise,
  amplified toward its modes, NOT an improvement on the parent.
- The setup is effectively LAMARCKIAN: it tries to pass acquired lifetime behavior directly to
  offspring by copying it wholesale. That transmits the modes and the noise, not the refinement.
- Cumulative selection on a volume-based fitness has no way to filter this out; it imports it.

Patching the two obvious levers (downsample the corpus; rebuild the fitness metric around
need-resolution) might make a marginally better version, but doing so on the remaining ~$3.75 would
be uninterpretable, and — per the strategic decision — even a patched version is still forcing a
novel goal (hereditary self-improvement) through methods built for a different purpose
(fine-tuning models on data).

**Next direction (recorded as intent, not yet a result):** return to first principles and design a
NOVEL hereditary mechanism, the way tunnel ablation was invented rather than borrowed. The working
hypothesis is that mechanisms which operate WITH the LLM's native grain (in-context reasoning, the
same grain tunneling exploits) succeed, while weight-surgery-via-imitation fights it. A new
inheritance mechanism should therefore likely be in-context / reasoning-native rather than
gradient-based imitation.
