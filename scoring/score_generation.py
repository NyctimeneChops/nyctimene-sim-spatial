"""
Reusable per-generation scorer + generation-record writer for the Nyctimene
neuroevolution lineage. Computes each agent's fitness from a run's pg_dump and
writes a durable generation record that supports SEED-FAIR cross-generation
pooling later.

Usage:
  python score_generation.py <dump.sql> <gen_number> <seed|none> <adapters_json> <out.json>

  adapters_json: JSON mapping arm -> adapter id used that generation, e.g.
    '{"flat":"adapter_flat_gen2","tunnel":"adapter_tunnel_gen2"}'  (gen2)
    '{"flat":"base","tunnel":"base"}'                              (gen1, no adapter)

WHY ranks/percentiles are stored (seed-fair pooling): generations run on
DIFFERENT world seeds, so raw_fitness is NOT comparable across generations. This
record stores, per agent, both the raw numbers AND the agent's rank + percentile
WITHIN its own generation's pool. A future gen-N corpus built from gen 1..N-1
elites can then select by cross-generation-comparable percentile (e.g. top P%
within each generation's own world) instead of raw fitness -- making the pooled
elite set seed-fair. This script does NOT pool; it only records what pooling needs.
"""
import json, sys

W = {"rest": 1, "harvest": 3, "drink": 5, "eat": 5, "build": 6, "message": 6,
     "social": 6, "cook": 8, "trade": 10, "cooperative_harvest": 15}
D = 0.30
TILT = 0.15   # soft efficiency tilt magnitude

# --- SPACE MILESTONE pass 4: circumstance-aware fitness normalization ---------
# On SPATIAL runs, raw fitness is partly a function of WHERE an agent spawned (near
# resources = cheap to act; stranded in a corner = burns energy just travelling). Correct
# for that so selection rewards POLICY not lucky geography -- but only PARTIALLY: some
# spawn variance is signal we WANT (a difficulty spread -> an outcome spread = the fitness
# diversity the loop feeds on). GOAL = prevent spawn-luck DOMINANCE, not achieve neutrality.
FOOD_NODES  = {"apple", "potato", "grain", "hunting"}
WATER_NODES = {"river", "well"}
MOVE_COST_PER_UNIT = 3   # mirrors the sim's constants.MOVE_COST_PER_UNIT (spatial move cost)
# Correction STRENGTH (named + tunable). 0.15 matches the efficiency-tilt magnitude: the
# worst spawn in a pool is scaled up to x1.15, the best down to x0.85 (max swing ~1.35x).
# That flips equal-fitness / close calls toward the worse spawn (crediting a good policy
# despite a bad spawn) but PRESERVES raw-fitness gaps larger than ~35% (a vastly-better
# lucky agent still wins). Partial correction, NOT erasure.
CIRCUMSTANCE_CORRECTION_WEIGHT = 0.15


def parse_actions(dump_path):
    lines = open(dump_path, encoding="utf-8", errors="replace").read().split("\n")
    s = next(i for i, l in enumerate(lines) if l.startswith("COPY public.actions "))
    hdr = lines[s].split("(", 1)[1].split(")")[0].split(", ")
    idx = {c: i for i, c in enumerate(hdr)}
    rows = []
    for l in lines[s + 1:]:
        if l == "\\.":
            break
        rows.append(l.split("\t"))
    return idx, rows


def parse_models(dump_path):
    """SPACE MILESTONE pass 1: {model_id: [spawn_x, spawn_y]} from the models COPY
    block, IF the spawn columns are present. Returns {} for pre-space dumps (no
    coordinates), so spawn_location stays null on uniform-world generations."""
    lines = open(dump_path, encoding="utf-8", errors="replace").read().split("\n")
    try:
        s = next(i for i, l in enumerate(lines) if l.startswith("COPY public.models "))
    except StopIteration:
        return {}
    hdr = lines[s].split("(", 1)[1].split(")")[0].split(", ")
    idx = {c: i for i, c in enumerate(hdr)}
    if "spawn_x" not in idx or "spawn_y" not in idx:
        return {}
    out = {}
    for l in lines[s + 1:]:
        if l == "\\.":
            break
        r = l.split("\t")
        try:
            out[r[idx["model_id"]]] = [float(r[idx["spawn_x"]]), float(r[idx["spawn_y"]])]
        except (ValueError, IndexError):
            pass
    return out


def parse_nodes(dump_path):
    """SPACE pass 4: per-group node layout {group: [(node_type, x, y)]} from node_state,
    IF pos_x/pos_y are present. {} for pre-space dumps (no coordinates)."""
    lines = open(dump_path, encoding="utf-8", errors="replace").read().split("\n")
    try:
        s = next(i for i, l in enumerate(lines) if l.startswith("COPY public.node_state "))
    except StopIteration:
        return {}
    hdr = lines[s].split("(", 1)[1].split(")")[0].split(", ")
    idx = {c: i for i, c in enumerate(hdr)}
    if "pos_x" not in idx or "pos_y" not in idx:
        return {}
    from collections import defaultdict
    out = defaultdict(list)
    for l in lines[s + 1:]:
        if l == "\\.":
            break
        r = l.split("\t")
        try:
            out[r[idx["experiment_group"]]].append(
                (r[idx["node_type"]], float(r[idx["pos_x"]]), float(r[idx["pos_y"]])))
        except (ValueError, IndexError):
            pass
    return dict(out)


def spawn_circumstance(spawn, group_nodes):
    """SPACE pass 4 SPAWN OPPORTUNITY. From an agent's spawn [x,y] and its SEALED group's
    node layout [(type,x,y)], measure how favorable the spawn was (within the group only):
      d_food  = distance from spawn to the NEAREST food node (apple/potato/grain/hunting)
      d_water = distance from spawn to the NEAREST water node (river/well)
      spawn_cost = round(d_food*MOVE_COST_PER_UNIT) + round(d_water*MOVE_COST_PER_UNIT)
                   = the ENERGY to travel from spawn to the nearest food AND nearest water
      spawn_opportunity = 1 / (1 + spawn_cost)   (HIGHER = better spawn = LOWER cost-to-reach)
    Returns a dict, or None if spawn/nodes are missing (pre-space -> no correction)."""
    import math
    if not spawn or not group_nodes:
        return None
    sx, sy = spawn
    def nearest(types):
        ds = [math.hypot(x - sx, y - sy) for (t, x, y) in group_nodes if t in types]
        return min(ds) if ds else None
    d_food, d_water = nearest(FOOD_NODES), nearest(WATER_NODES)
    if d_food is None or d_water is None:
        return None
    cost = round(d_food * MOVE_COST_PER_UNIT) + round(d_water * MOVE_COST_PER_UNIT)
    return {"nearest_food_dist": round(d_food, 2), "nearest_water_dist": round(d_water, 2),
            "cost_to_reach_food_and_water": cost,
            "spawn_opportunity": round(1.0 / (1.0 + cost), 6)}


def circumstance_adjust(combined, spawn_costs, weight=CIRCUMSTANCE_CORRECTION_WEIGHT):
    """SPACE pass 4 PARTIAL CORRECTION. combined/spawn_costs: {agent: value}. Returns
    {agent: circumstance_adjusted}. BACKWARD-COMPAT: if spawn data is absent (any None) or
    all spawns are equal, returns `combined` UNCHANGED (identical ranking on non-spatial
    runs). Otherwise circ_tilt in [-1,+1] = 2*(cost-min)/(max-min)-1 (+1 = worst spawn /
    highest cost -> UPWARD; -1 = best spawn -> DOWNWARD), adjusted = combined*(1+weight*circ_tilt)."""
    if not spawn_costs or any(v is None for v in spawn_costs.values()):
        return dict(combined)
    cmin, cmax = min(spawn_costs.values()), max(spawn_costs.values())
    if cmax == cmin:
        return dict(combined)
    return {a: combined[a] * (1 + weight * (2 * (spawn_costs[a] - cmin) / (cmax - cmin) - 1))
            for a in combined}


def score(dump_path):
    idx, rows = parse_actions(dump_path)
    spawns = parse_models(dump_path)      # SPACE pass 1: {model_id: [spawn_x, spawn_y]} or {}
    node_layout = parse_nodes(dump_path)  # SPACE pass 4: {group: [(node_type, x, y)]} or {}
    from collections import defaultdict
    succ = defaultdict(lambda: defaultdict(int))
    toks = defaultdict(int)
    for r in rows:
        m = r[idx["model_id"]]
        toks[m] += int(r[idx["tokens_used"]])
        if r[idx["succeeded"]] == "t":
            succ[m][r[idx["action_type"]]] += 1

    def raw_fitness(a):
        f = 0.0
        for t, n in succ[a].items():
            w = W.get(t, 0)
            if w and n > 0:
                f += w * (1 - D ** n) / (1 - D)
        return f

    agents = sorted(toks)
    pools = {"flat":   [a for a in agents if a.startswith("flat")],
             "tunnel": [a for a in agents if a.startswith("tunnel")]}
    out = {}
    for pool, pa in pools.items():
        raw = {a: raw_fitness(a) for a in pa}
        eff = {a: (raw[a] / toks[a] if toks[a] else 0.0) for a in pa}
        emin, emax = min(eff.values()), max(eff.values())
        def tilt(a): return 0.0 if emax == emin else 2 * (eff[a] - emin) / (emax - emin) - 1
        comb = {a: raw[a] * (1 + TILT * tilt(a)) for a in pa}

        # SPACE pass 4: circumstance-aware correction (PARTIAL). Each agent's spawn
        # opportunity comes from its spawn point + its SEALED group's node layout; the
        # dominance-preventing adjustment then nudges equal/near-equal policies at unequal
        # spawns toward each other. On non-spatial runs (gen 1-3) spawn data is absent, so
        # adj == comb EXACTLY -> ranking/elite identical to the pre-pass-4 scorer.
        circ = {a: spawn_circumstance(spawns.get(a), node_layout.get(a.rsplit("_", 1)[0]))
                for a in pa}
        spawn_costs = {a: (circ[a]["cost_to_reach_food_and_water"] if circ[a] else None)
                       for a in pa}
        adj = circumstance_adjust(comb, spawn_costs)

        order = sorted(pa, key=lambda a: -adj[a])   # rank/elite by the circumstance-adjusted score
        n = len(order)
        recs = []
        for rank, a in enumerate(order, 1):
            c = circ[a]
            recs.append({
                "model": a,
                "raw_fitness": round(raw[a], 4),
                "efficiency": round(eff[a], 8),
                "combined": round(comb[a], 4),
                "circumstance_adjusted": round(adj[a], 4),     # SPACE pass 4: rank/elite use THIS
                "rank": rank,                                  # 1 = best in this pool
                "percentile": round(100.0 * (n - rank) / (n - 1), 2) if n > 1 else 100.0,
                "elite": rank <= 10,
                "successful_action_counts": dict(succ[a]),
                "total_tokens": toks[a],
                # SPACE MILESTONE circumstance (sec 7). spawn_location (pass 1) +
                # spawn_opportunity / resource_landscape (pass 4) are POPULATED on spatial
                # runs; all null on pre-space uniform dumps. territorial_position deferred.
                "circumstance": {
                    "spawn_location": spawns.get(a),   # [spawn_x, spawn_y], or None pre-space
                    "spawn_opportunity": (c["spawn_opportunity"] if c else None),
                    "resource_landscape": ({k: c[k] for k in (
                        "nearest_food_dist", "nearest_water_dist", "cost_to_reach_food_and_water")}
                        if c else None),
                    "territorial_position": None,  # settled/claimed position (deferred capture)
                },
            })
        out[pool] = {"agents": recs, "elite": [r["model"] for r in recs if r["elite"]]}
    return out


def main(argv):
    dump, gen, seed, adapters_json, outp = argv[1:6]
    seed_val = None if seed.lower() in ("none", "null", "") else int(seed)
    record = {
        "generation": int(gen),
        "world_seed": seed_val,
        "adapters_by_arm": json.loads(adapters_json),
        "scoring": {"weights": W, "decay_d": D, "efficiency_tilt": TILT,
                    "elite_top_n": 10, "successful_actions_only": True,
                    "circumstance_correction_weight": CIRCUMSTANCE_CORRECTION_WEIGHT,
                    "circumstance_correction": (
                        "SPACE pass 4: circumstance_adjusted = combined * (1 + W * circ_tilt), "
                        "circ_tilt in [-1,+1] = 2*(spawn_cost - min)/(max-min) - 1 within the pool "
                        "(+1 = worst spawn / highest cost -> UP; -1 = best spawn -> DOWN). spawn_cost "
                        "= round(d_food*3)+round(d_water*3) = energy from spawn to the nearest food + "
                        "nearest water in the SEALED group; spawn_opportunity = 1/(1+spawn_cost). "
                        "PARTIAL (W=%s): prevents spawn-luck dominance without erasing the difficulty "
                        "spread. Applied ONLY when spatial data is present; otherwise adjusted == "
                        "combined (identical ranking). rank/elite use circumstance_adjusted."
                        % CIRCUMSTANCE_CORRECTION_WEIGHT),
                    "note": "ranks/percentiles are WITHIN this generation only; "
                            "use them (not raw_fitness) for seed-fair cross-gen pooling"},
        # SPACE circumstance fields (sec 7). spawn_location (pass 1) + spawn_opportunity /
        # resource_landscape (pass 4) are POPULATED on spatial runs; null on pre-space
        # uniform dumps. territorial_position is still deferred (settled-position capture).
        "circumstance_fields": {
            "status": "spawn_location + spawn_opportunity + resource_landscape POPULATED on "
                      "spatial runs (pass 1 + pass 4); null on pre-space uniform dumps. "
                      "territorial_position still deferred.",
            "spec": "nyctimene_space_milestone_design.md sec 7 (circumstance-aware fitness)",
            "per_agent_keys": ["spawn_location", "spawn_opportunity", "resource_landscape",
                               "territorial_position"],
        },
        "pools": score(dump),
    }
    json.dump(record, open(outp, "w"), indent=2)
    print(f"wrote {outp}: gen {record['generation']} seed {record['world_seed']} "
          f"adapters {record['adapters_by_arm']}")
    for pool, d in record["pools"].items():
        print(f"  {pool}: {len(d['agents'])} agents, elite={[e.split('_',1)[1] for e in d['elite']]}")


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print(__doc__); sys.exit(2)
    main(sys.argv)
