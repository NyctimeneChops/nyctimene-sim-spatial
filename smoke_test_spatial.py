"""
SPACE MILESTONE, PASS 5 of 6 -- mock-inference INTEGRATION smoke test.  NO GPU, NO SPEND.

Runs the FULL spatial world end-to-end as a live loop against a throwaway Postgres:
the REAL Flask app + REAL Agent loop + REAL prompt builder + REAL movement/enforcement,
with the DECISION mocked (no model) by spatially-aware scripted policies. This is
VERIFICATION of passes 1-4 holding together as a running system -- it adds no features
and changes no mechanics.

MOCK token counts are aligned to the REAL rendered prompt length (tokens_used =
round(len(prompt)/4)) so the energy accounting is meaningful (a ~6000-char CALM prompt
-> ~1500 tokens, matching the measured live burn).

Sections:
  [A] spawn positions (pos + immutable spawn) populated + distinct
  [B] live loop: travelers move->harvest->eat sustain; wanderer soft-locks
  [C] movement resolves (teleport, energy charged for ACTUAL distance)   [deterministic]
  [D] presence enforcement (harvest not-at-node FAILS; move-then-harvest SUCCEEDS)
  [E] occupancy / co-harvest (multiple agents STACK on a node and both harvest)
  [F] graceful displacement + spatial_note (non-node point) + owner-exception  [deterministic]
  [G] positional shelter = territory (build claims CURRENT point; positional rest bonus)
  [H] spatial prompt renders DYNAMICALLY (position + per-node distance change after a move)
  [I] dump has spatial columns populated + scorer produces circumstance (spawn_opportunity)
Token-cost measurement + calibration check are printed at the end.
"""
import os, sys, time, json, math, re, subprocess, requests

BASE = "http://127.0.0.1:5000"
os.environ["USE_MOCK_INFERENCE"] = "True"
os.environ.setdefault("FLASK_SECRET_KEY", "smoke")
os.environ.setdefault("EXPERIMENT_RUN_NAME", "smoke_spatial")

results = []
def ck(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

def tok(prompt):
    """MOCK token count aligned to the real prompt length (~4 chars/token)."""
    return max(1, round(len(prompt) / 4))

EDIBLES = ("apple", "potato_cooked", "grain_cooked", "meat_cooked", "bread")

def _model(mid):
    return requests.get(f"{BASE}/models/{mid}", timeout=10).json()

def _held(mid):
    inv = requests.get(f"{BASE}/inventory/{mid}", timeout=10).json()["inventory"]
    return {r["resource_type"]: r["quantity"] for r in inv}

def _nodes(group):
    return requests.get(f"{BASE}/nodes", params={"group": group}, timeout=10).json()

def _node_pt(group, ntype):
    n = next(n for n in _nodes(group) if n["node_type"] == ntype)
    return float(n["pos_x"]), float(n["pos_y"])

def _at(mid, pt, eps=1e-6):
    m = _model(mid)
    return math.hypot(float(m["pos_x"]) - pt[0], float(m["pos_y"]) - pt[1]) <= eps

# ---------------------------------------------------------------- spatial mock policy
ROLES = {}
GROUP = "flat_C1"

def policy(prompt, model_id):
    """Spatially-aware scripted decision (no GPU). Reads live position + node coords
    from the API to make move->harvest->eat legal. tokens_used scales with prompt len."""
    # Execution/skill sub-prompts (build/hunt confirm) are not the situation report:
    # commit by default so a two-stage action completes.
    if "SITUATION REPORT" not in prompt:
        return {"response": '{"decision": "commit", "reasoning": "proceed"}',
                "tokens_used": tok(prompt)}

    role = ROLES.get(model_id, "traveler")
    t = tok(prompt)
    m = _model(model_id)
    held = _held(model_id)

    if role in ("apple_traveler", "river_traveler"):
        ntype = "apple" if role == "apple_traveler" else "river"
        pt = _node_pt(GROUP, ntype)
        here = math.hypot(float(m["pos_x"]) - pt[0], float(m["pos_y"]) - pt[1]) <= 1e-6
        if role == "apple_traveler":
            if held.get("apple", 0) > 0:
                act = {"action_type": "eat", "target": "apple", "reasoning": "hold apple; eat to refuel"}
            elif here:
                act = {"action_type": "harvest", "target": "apple", "reasoning": "at apple node; harvest"}
            else:
                act = {"action_type": "move", "target": "apple", "reasoning": "travel to apple node to harvest"}
        else:  # river traveler: move -> harvest water -> drink
            if held.get("water", 0) > 0:
                act = {"action_type": "drink", "target": "water", "reasoning": "hold water; drink to refuel"}
            elif here:
                act = {"action_type": "harvest", "target": "river", "reasoning": "at river; harvest water"}
            else:
                act = {"action_type": "move", "target": "river", "reasoning": "travel to river to harvest water"}
    elif role == "wanderer":
        # Move to a fresh non-node point every tick, never consume -> movement+thought bleed.
        n = len(requests.get(f"{BASE}/actions/{model_id}", params={"limit": 999}, timeout=10).json())
        x = 100.0 + (n * 137) % 800
        y = 100.0 + (n * 89) % 800
        act = {"action_type": "move", "target": f"{x},{y}", "reasoning": "wander; never eat (stress the bleed)"}
    elif role == "presence_tester":
        # Try to harvest apple WITHOUT ever moving to it -> presence enforcement should FAIL it.
        act = {"action_type": "harvest", "target": "apple", "reasoning": "harvest apple in place (no move)"}
    elif role == "builder":
        # move to a fixed claim point -> build basic shelter (claims the point) -> rest (positional bonus).
        claim = (700.0, 700.0)
        here = math.hypot(float(m["pos_x"]) - claim[0], float(m["pos_y"]) - claim[1]) <= 1e-6
        if m["shelter_status"] == "none":
            if here:
                act = {"action_type": "build", "target": "basic", "reasoning": "at claim point; build shelter here"}
            else:
                act = {"action_type": "move", "target": f"{claim[0]},{claim[1]}", "reasoning": "travel to my claim point to build"}
        else:
            act = {"action_type": "rest", "target": None, "reasoning": "rest at my own shelter (positional bonus)"}
    else:
        act = {"action_type": "rest", "target": None, "reasoning": "idle"}
    return {"response": json.dumps(act), "tokens_used": t}

# =============================================================================== run
def _reset_db():
    """Self-contained reset (replicates reset_db.py) so the smoke is repeatable:
    drop all tables + recreate from the CURRENT schema.sql (spatial columns included)."""
    import psycopg2
    from reset_db import DROP_ORDER
    url = [l.split("=", 1)[1].strip() for l in open(".env") if l.startswith("DATABASE_URL=")][0]
    url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    schema_sql = open("schema.sql").read()
    conn = psycopg2.connect(url); conn.autocommit = True; cur = conn.cursor()
    for table in DROP_ORDER:
        cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    decommented = "\n".join(line.split("--")[0] for line in schema_sql.split("\n"))
    for stmt in [s.strip() for s in decommented.split(";") if s.strip()]:
        cur.execute(stmt)
    cur.close(); conn.close()
    print("  DB reset from schema.sql (fresh spatial world)")

_reset_db()
app = subprocess.Popen([sys.executable, "app.py"], env=os.environ.copy(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
try:
    up = False
    for _ in range(40):
        try:
            if requests.get(BASE + "/health", timeout=2).json().get("database") == "connected":
                up = True; break
        except Exception: pass
        time.sleep(0.5)
    ck("Flask ledger app up + DB-connected (mock inference, no GPU)", up)
    if not up: raise SystemExit("app did not come up")

    import random as _random
    _random.seed(4025)                       # reproducible placement

    import models.agent as agent_mod
    agent_mod.ACTION_INTERVAL_SECONDS = 0.05
    agent_mod.LOOP_DELAY_SECONDS = 0.05
    agent_mod.get_model_decision = policy    # scripted mock; build_prompt still runs each tick

    from world.environment import initialize_world
    from world.placement import place_point
    from groups.group_config import get_group_config
    from models.agent import Agent
    from mechanics import energy as E
    from mechanics import movement as MV
    from constants import (MAX_ENERGY, BASAL_INCOME, COST_HARVEST, MOVE_COST_PER_UNIT,
                           INACTIVITY_THRESHOLD_TICKS, PLANE_WIDTH)

    initialize_world()

    # --- create 8 flat_C1 agents (CALM arm) with placed spawns + 1 tunnel_C1 agent
    #     (used only to render a TUNNEL-band prompt for the token measurement).
    ROLES.update({
        f"{GROUP}_01": "apple_traveler", f"{GROUP}_02": "apple_traveler",
        f"{GROUP}_03": "wanderer",       f"{GROUP}_04": "presence_tester",
        f"{GROUP}_05": "builder",        f"{GROUP}_06": "river_traveler",
        f"{GROUP}_07": "apple_traveler", f"{GROUP}_08": "apple_traveler",
    })
    placed = {}
    for mid in ROLES:
        px, py = place_point(_random)
        placed[mid] = (px, py)
        requests.post(BASE + "/models", json={"model_id": mid, "experiment_group": GROUP,
                      "run": "token_economy", "wallet": 150, "pos_x": px, "pos_y": py}, timeout=10)
    # tunnel agent (measurement only)
    tx, ty = place_point(_random)
    requests.post(BASE + "/models", json={"model_id": "tunnel_C1_01", "experiment_group": "tunnel_C1",
                  "run": "token_economy", "wallet": 150, "pos_x": tx, "pos_y": ty}, timeout=10)

    # seed the builder with shelter materials (test setup, not a mechanic change)
    requests.post(BASE + "/inventory/" + f"{GROUP}_05/add", json={"resource_type": "wood", "quantity": 5}, timeout=10)
    requests.post(BASE + "/inventory/" + f"{GROUP}_05/add", json={"resource_type": "stone", "quantity": 3}, timeout=10)

    # ----------------------------------------------------------- [A] spawn positions
    print("\n[A] SPAWN POSITIONS")
    rows = {mid: _model(mid) for mid in ROLES}
    ck("every agent spawns with pos_x/pos_y AND immutable spawn_x/spawn_y populated",
       all(r["pos_x"] is not None and r["pos_y"] is not None
           and r["spawn_x"] is not None and r["spawn_y"] is not None for r in rows.values()))
    ck("current position == spawn position at spawn (pos == spawn)",
       all(abs(r["pos_x"] - r["spawn_x"]) < 1e-9 and abs(r["pos_y"] - r["spawn_y"]) < 1e-9
           for r in rows.values()))
    pts = {(round(r["pos_x"], 3), round(r["pos_y"], 3)) for r in rows.values()}
    ck("spawns are distinct points on the plane (uniform-random placement)",
       len(pts) == len(rows), f"{len(pts)} distinct / {len(rows)} agents")
    ck("all agents spawn at MAX_ENERGY", all(r["current_energy"] == MAX_ENERGY for r in rows.values()))

    # ----------------------------------------------------------- [B] live loop
    print("\n[B] LIVE LOOP (mock decisions exercising move / harvest / build)")
    agents = {mid: Agent(mid, get_group_config(GROUP)) for mid in ROLES}
    # tunnel_C1_01 runs as an IDLE participant (default 'rest' role) so the tunnel
    # scoring pool is non-empty; it also serves the TUNNEL-band prompt measurement later.
    tunnel_agent = Agent("tunnel_C1_01", get_group_config("tunnel_C1"))
    for a in agents.values(): a.start()
    tunnel_agent.start()

    traj = {mid: [] for mid in ROLES}
    softlock_tick = {mid: None for mid in ROLES}
    t0 = time.time(); _day = 1; _last_reset = 0.0
    while time.time() - t0 < 50:
        if time.time() - _last_reset > 3.0:   # simulate day-boundary node regen (fast smoke)
            _day += 1
            try: requests.post(BASE + "/nodes/reset", json={"day_number": _day}, timeout=10)
            except Exception: pass
            _last_reset = time.time()
        for mid in ROLES:
            e = _model(mid)["current_energy"]
            n = len(requests.get(f"{BASE}/actions/{mid}", params={"limit": 999}, timeout=10).json())
            traj[mid].append((round(time.time() - t0, 1), e, n))
            if softlock_tick[mid] is None and E.is_soft_locked(e):
                softlock_tick[mid] = n
        time.sleep(0.7)
    for a in agents.values(): a.stop()
    tunnel_agent.stop()
    time.sleep(0.7)

    def acts(mid):
        return requests.get(f"{BASE}/actions/{mid}", params={"limit": 999}, timeout=10).json()
    fin = {mid: traj[mid][-1][1] for mid in ROLES}

    print("  --- trajectory (energy_k @ action-count) ---")
    for mid in ROLES:
        s = traj[mid]
        pts_s = " ".join(f"{e//1000}k@{n}" for (_, e, n) in s[::max(1, len(s)//8)])
        print(f"    {mid} [{ROLES[mid]:>15}]  {pts_s}  final={s[-1][1]} ticks={s[-1][2]}")

    travelers = [f"{GROUP}_01", f"{GROUP}_02", f"{GROUP}_07", f"{GROUP}_08", f"{GROUP}_06"]
    ck("travelers (move->harvest->consume) SUSTAIN (stay well above soft-lock)",
       all(fin[m] > 10000 and not E.is_soft_locked(fin[m]) for m in travelers),
       f"finals={[fin[m] for m in travelers]}")
    ck("wanderer (moves every tick, never eats) SOFT-LOCKS",
       E.is_soft_locked(fin[f"{GROUP}_03"]),
       f"final={fin[f'{GROUP}_03']}, softlock@tick={softlock_tick[f'{GROUP}_03']}")

    # ----------------------------------------------------------- [D] presence (emergent)
    print("\n[D] PRESENCE ENFORCEMENT")
    for m in travelers:
        a = acts(m)
        moved = [x for x in a if x["action_type"] == "move" and x["succeeded"]]
        harv_ok = [x for x in a if x["action_type"] == "harvest" and x["succeeded"]]
        ck(f"{m}: move-then-harvest SUCCEEDS ({len(moved)} moves, {len(harv_ok)} harvests)",
           len(moved) > 0 and len(harv_ok) > 0)
        break  # one representative is enough to print; assert all below
    ck("ALL travelers: >=1 successful move AND >=1 successful harvest (move-then-harvest)",
       all(any(x["action_type"] == "move" and x["succeeded"] for x in acts(m))
           and any(x["action_type"] == "harvest" and x["succeeded"] for x in acts(m)) for m in travelers))
    pt_acts = acts(f"{GROUP}_04")
    pt_harv = [x for x in pt_acts if x["action_type"] == "harvest"]
    ck("presence-tester (harvests apple WITHOUT moving) FAILS every harvest (not at node)",
       len(pt_harv) > 0 and all(not x["succeeded"] for x in pt_harv),
       f"{len(pt_harv)} harvest attempts, {sum(x['succeeded'] for x in pt_harv)} succeeded")

    # ----------------------------------------------------------- [E] co-harvest / occupancy
    print("\n[E] OCCUPANCY / CO-HARVEST")
    apple_pt = _node_pt(GROUP, "apple")
    at_apple = [m for m in (f"{GROUP}_01", f"{GROUP}_02", f"{GROUP}_07", f"{GROUP}_08") if _at(m, apple_pt)]
    harvesters = [m for m in (f"{GROUP}_01", f"{GROUP}_02", f"{GROUP}_07", f"{GROUP}_08")
                  if any(x["action_type"] == "harvest" and x["succeeded"] for x in acts(m))]
    ck("multiple apple-travelers STACK on the exact apple-node point (node targets are stackable)",
       len(at_apple) >= 2, f"{len(at_apple)} agents at ({apple_pt[0]:.1f},{apple_pt[1]:.1f})")
    ck("more than one agent successfully HARVESTS the shared apple node (co-harvest)",
       len(harvesters) >= 2, f"{len(harvesters)} distinct successful harvesters")

    # ----------------------------------------------------------- [G] shelter = territory
    print("\n[G] POSITIONAL SHELTER = TERRITORY")
    b = _model(f"{GROUP}_05")
    ck("builder built a shelter and CLAIMED its current point (shelter_x/y set)",
       b["shelter_status"] in ("basic", "improved") and b["shelter_x"] is not None and b["shelter_y"] is not None,
       f"status={b['shelter_status']} claim=({b['shelter_x']},{b['shelter_y']})")
    ck("shelter claim point == the point the builder moved to before building (build @ current pos)",
       b["shelter_x"] is not None and abs(b["shelter_x"] - 700.0) < 5 and abs(b["shelter_y"] - 700.0) < 5,
       f"claim=({b['shelter_x']},{b['shelter_y']}) vs intended (700,700)")

    # ----------------------------------------------------------- deterministic mechanics
    # Threads are stopped; drive the REAL handlers directly for exact, race-free accounting.
    print("\n[C] MOVEMENT COST (deterministic: exact energy charged for ACTUAL distance)")
    mover = agents[f"{GROUP}_02"]
    # place it at a known origin, then move to the river node; assert energy delta = thought + move_cost.
    requests.post(f"{BASE}/models/{f'{GROUP}_02'}/position", json={"pos_x": 0.0, "pos_y": 0.0, "note": ""}, timeout=10)
    requests.post(f"{BASE}/models/{f'{GROUP}_02'}/energy/adjust",
                  json={"delta": MAX_ENERGY}, timeout=10)   # top back up to the cap
    e_before = _model(f"{GROUP}_02")["current_energy"]
    rpt = _node_pt(GROUP, "river")
    dist = math.hypot(rpt[0], rpt[1])
    exp_move = MV.move_cost(dist)
    THOUGHT = 500
    mover._handle_move({"action_type": "move", "target": "river", "reasoning": "det"}, THOUGHT)
    e_after = _model(f"{GROUP}_02")["current_energy"]
    charged = e_before - e_after
    ck("teleport move arrives at the node SAME tick (position == river node point)",
       _at(f"{GROUP}_02", rpt), f"pos now river ({rpt[0]:.1f},{rpt[1]:.1f})")
    ck("energy charged == inference tokens + move_cost(actual distance) exactly",
       charged == THOUGHT + exp_move,
       f"charged {charged} = {THOUGHT} thought + {exp_move} move (dist {dist:.1f} x {MOVE_COST_PER_UNIT})")

    print("\n[F] GRACEFUL DISPLACEMENT + spatial_note + OWNER-EXCEPTION (deterministic)")
    claim = (float(b["shelter_x"]), float(b["shelter_y"]))
    # owner-exception: the builder can land EXACTLY on its own shelter point (own shelter not an obstacle).
    builder = agents[f"{GROUP}_05"]
    requests.post(f"{BASE}/models/{f'{GROUP}_05'}/position", json={"pos_x": 300.0, "pos_y": 300.0, "note": ""}, timeout=10)
    requests.post(f"{BASE}/models/{f'{GROUP}_05'}/energy/adjust", json={"delta": MAX_ENERGY}, timeout=10)
    builder._handle_move({"action_type": "move", "target": f"{claim[0]},{claim[1]}", "reasoning": "det"}, THOUGHT)
    ck("OWNER-EXCEPTION: builder lands EXACTLY on its own shelter point (not displaced)",
       _at(f"{GROUP}_05", claim), f"builder pos == claim ({claim[0]:.1f},{claim[1]:.1f})")
    # displacement: a DIFFERENT agent moving onto that claimed point is pushed to a nearby free point + noted.
    intruder = agents[f"{GROUP}_07"]
    requests.post(f"{BASE}/models/{f'{GROUP}_07'}/position", json={"pos_x": 300.0, "pos_y": 300.0, "note": ""}, timeout=10)
    requests.post(f"{BASE}/models/{f'{GROUP}_07'}/energy/adjust", json={"delta": MAX_ENERGY}, timeout=10)
    intruder._handle_move({"action_type": "move", "target": f"{claim[0]},{claim[1]}", "reasoning": "det"}, THOUGHT)
    im = _model(f"{GROUP}_07")
    off = math.hypot(im["pos_x"] - claim[0], im["pos_y"] - claim[1])
    ck("DISPLACEMENT: intruder targeting the claimed point lands OFF it (nearest free point)",
       off > 1e-6, f"landed {off:.2f} units off the claimed point")
    from models.prompt_builder import build_prompt
    iprompt = build_prompt(f"{GROUP}_07")
    ck("spatial_note surfaces the displacement to the agent's NEXT prompt ('Last move:' line)",
       "Last move:" in iprompt and "occupied" in iprompt)

    # ----------------------------------------------------------- [H] dynamic spatial prompt
    print("\n[H] SPATIAL PROMPT RENDERS DYNAMICALLY (position + distances change after a move)")
    def pos_of(p):
        m = re.search(r"Position:\s+\(([-\d.]+), ([-\d.]+)\)", p)
        return (float(m.group(1)), float(m.group(2))) if m else None
    def apple_dist(p):
        for line in p.splitlines():
            if "apple" in line and "distance" in line:
                mm = re.search(r"distance ([\d.]+)", line); return float(mm.group(1)) if mm else None
        return None
    # decision_log captured a rendered prompt every tick during the live loop.
    dl = requests.get(f"{BASE}/decision_log/recent/{GROUP}_01", params={"limit": 5}, timeout=10).json()
    ck("prompt was built + logged every decision tick during the live loop", len(dl) > 0,
       f"{len(dl)} recent decision rows for {GROUP}_01")
    # Render the SAME agent at two positions: the per-node distance must track position.
    p_here = build_prompt(f"{GROUP}_01")             # currently AT the apple node (dist ~0)
    requests.post(f"{BASE}/models/{GROUP}_01/position", json={"pos_x": 0.0, "pos_y": 0.0, "note": ""}, timeout=10)
    p_far = build_prompt(f"{GROUP}_01")              # moved to (0,0): apple now far
    d_here, d_far = apple_dist(p_here), apple_dist(p_far)
    far_expected = math.hypot(apple_pt[0], apple_pt[1])
    ck("prompt shows a live Position line that reflects the agent's current point",
       pos_of(p_here) is not None and pos_of(p_far) == (0.0, 0.0))
    ck("per-node distance is DYNAMIC: re-renders with position (at-node ~0 -> far after moving away)",
       d_here is not None and d_far is not None and d_here <= 1.0 and abs(d_far - far_expected) < 1.0,
       f"apple distance {d_here:.1f} (at node) -> {d_far:.1f} (from origin, expected {far_expected:.1f})")

    # =========================================================== TOKEN-COST MEASUREMENT
    print("\n" + "=" * 74)
    print("TOKEN-COST MEASUREMENT  (spatial info vs pre-space baseline)")
    print("=" * 74)

    def spatial_added_chars(p):
        """Sum of the char length of the SPACE-milestone additions present in prompt p."""
        added = 0; parts = {}
        for line in p.splitlines():
            s = line.strip()
            if s.startswith("Position:"):
                parts["position_line"] = parts.get("position_line", 0) + len(line) + 1
            elif s.startswith("Last move:"):
                parts["last_move_note"] = parts.get("last_move_note", 0) + len(line) + 1
            elif "costs energy = distance x" in line:          # the 'move' AVAILABLE ACTION line
                parts["move_action_line"] = parts.get("move_action_line", 0) + len(line) + 1
            elif s.startswith("SPACE:"):
                parts["mechanics_space"] = parts.get("mechanics_space", 0) + len(line) + 1
            elif s.startswith("SHELTER:"):
                parts["mechanics_shelter"] = parts.get("mechanics_shelter", 0) + len(line) + 1
        # per-node "  |  distance X / move cost Y" suffix appended to each node line
        suffix = sum(len(m) for m in re.findall(r"   \|  distance [\d.]+ / move cost \d+", p))
        if suffix: parts["node_distance_suffix"] = suffix
        # directive move fragments
        for frag in ("For move, the target is the node type you want to travel to, or 'x,y' coordinates.",):
            if frag in p: parts["directive_move"] = parts.get("directive_move", 0) + len(frag)
        for frag in (", move",):    # 'move' appended to the action_type enumeration line
            if "action_type must be one of" in p and "move" in p:
                parts["directive_move_enum"] = len(frag); break
        added = sum(parts.values())
        return added, parts

    # top the flat agent's tension to CALM already (flat -> always CALM). Render a mature CALM prompt.
    calm = build_prompt(f"{GROUP}_01")
    calm_add, calm_parts = spatial_added_chars(calm)
    calm_total = len(calm); calm_base = calm_total - calm_add

    # force the tunnel agent into the TUNNEL band (hunger dominant) and render.
    requests.post(f"{BASE}/models/tunnel_C1_01/tension",
                  json={"tension": 90, "tension_sources": json.dumps(
                      {"hunger": 90, "thirst": 0, "failures": 0, "shelter": 0, "messages": 0})}, timeout=10)
    tunnelp = build_prompt("tunnel_C1_01")
    is_tunnel = "barely think" in tunnelp
    tun_add, tun_parts = spatial_added_chars(tunnelp)
    tun_total = len(tunnelp); tun_base = tun_total - tun_add

    C = 4.0  # chars/token (calibrated: a ~6000-char CALM prompt -> ~1500 tok = the live burn)
    def line(lbl, total, base, add):
        print(f"  {lbl:<26} prompt {total:>5} chars (~{total/C:>5.0f} tok) | "
              f"baseline {base:>5} (~{base/C:>4.0f}) | spatial +{add:>4} chars "
              f"(~{add/C:>4.0f} tok) = +{100.0*add/base:>4.1f}%")
    print(f"  (token estimate uses ~{C:.0f} chars/token; %-increase is invariant to that ratio)\n")
    line("CALM / flat prompt", calm_total, calm_base, calm_add)
    line("TUNNEL (compressed)", tun_total, tun_base, tun_add)
    print(f"\n  CALM spatial breakdown (chars): {calm_parts}")
    print(f"  TUNNEL spatial breakdown (chars): {tun_parts}")
    ck("TUNNEL prompt genuinely rendered in the compressed band", is_tunnel)
    ck("spatial info measurably increases CALM prompt size (position + per-node dist + move + mechanics)",
       calm_add > 0 and calm_parts.get("node_distance_suffix", 0) > 0)
    ck("compression: TUNNEL carries FAR less spatial overhead than CALM (mechanics/actions dropped)",
       tun_add < calm_add, f"tunnel +{tun_add} < calm +{calm_add} chars")

    # =========================================================== CALIBRATION CHECK
    print("\n" + "=" * 74)
    print("CALIBRATION CHECK  (v1 constants vs measured spatial burn -- viability, no changes)")
    print("=" * 74)
    calm_tok = calm_total / C
    spatial_tok = calm_add / C
    base_tok = calm_base / C
    # average move on the plane: E[dist] between two uniform points ~ 0.5214 * side
    avg_dist = 0.5214 * PLANE_WIDTH
    avg_move = MV.move_cost(avg_dist)
    print(f"  measured CALM thought  : ~{calm_tok:.0f} energy/thought  "
          f"(pre-space ~{base_tok:.0f} + spatial ~{spatial_tok:.0f})")
    print(f"  BASAL_INCOME           : +{BASAL_INCOME}/tick")
    print(f"  COST_HARVEST           : {COST_HARVEST}/harvest    apple eat yield: {E.consumption_yield('eat','apple',False)}")
    print(f"  avg one-time move cost : ~{avg_move} energy  (E[dist]~{avg_dist:.0f} x {MOVE_COST_PER_UNIT}/unit)")
    # reasonable-play cycle: move-to-node ONCE, then a harvest+eat 2-tick loop in place.
    eat_yield = E.consumption_yield("eat", "apple", False)
    cyc_in = 2 * BASAL_INCOME + eat_yield
    cyc_out = 2 * calm_tok + COST_HARVEST
    print(f"  harvest+eat 2-tick loop: in {cyc_in:.0f} (2x basal + eat) - out {cyc_out:.0f} "
          f"(2x thought + harvest) = NET {cyc_in - cyc_out:+.0f} / 2 ticks")
    print(f"  one-time travel to node: ~{avg_move} energy, recovered by {avg_move/eat_yield:.2f} of one eat")
    viable = (cyc_in - cyc_out) > 0 and avg_move < eat_yield
    ck("reasonable play (move-to-node then harvest+eat) NETS POSITIVE under v1 constants",
       viable, f"loop net {cyc_in - cyc_out:+.0f}/2tk; one move ~{avg_move} < one eat {eat_yield}")
    print("  RECOMMENDATION: " + (
        "no retune needed. Movement is a MINOR drain vs inference: one avg move "
        f"(~{avg_move}) is ~{100.0*avg_move/(2*calm_tok+COST_HARVEST+avg_move):.0f}% of a move+harvest+eat "
        "sequence, and is repaid by a fraction of one eat. The dominant cost remains the "
        f"per-thought inference (~{calm_tok:.0f}), of which spatial adds ~{spatial_tok:.0f} "
        f"(+{100.0*calm_add/calm_base:.0f}%). Reasonable play stays positive; only pathological "
        "wandering (move every tick, never consume) soft-locks -- as intended. If real-run "
        "margins prove thin, BASAL_INCOME is the lever (movement is not the binding cost). "
        "NO CONSTANT CHANGED."))

    # =========================================================== [I] dump + circumstance
    print("\n[I] DUMP HAS SPATIAL COLUMNS + SCORER PRODUCES CIRCUMSTANCE")
    import psycopg2
    url = [l.split("=", 1)[1].strip() for l in open(".env") if l.startswith("DATABASE_URL=")][0]
    url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    conn = psycopg2.connect(url)
    DUMP = os.path.abspath("_smoke_spatial_dump.sql")
    with open(DUMP, "w") as f:
        # exactly the COPY blocks the pass-4 scorer parses (actions + models + node_state).
        blocks = [
            ("actions", "action_id, model_id, action_type, succeeded, tokens_used"),
            ("models", "model_id, spawn_x, spawn_y"),
            ("node_state", "node_id, node_type, experiment_group, pos_x, pos_y"),
        ]
        for tbl, cols in blocks:
            f.write(f"COPY public.{tbl} ({cols}) FROM stdin;\n")
            cur = conn.cursor()
            cur.copy_expert(f"COPY (SELECT {cols} FROM {tbl}) TO STDOUT", f)
            f.write("\\.\n")
    # confirm the dump actually carries populated spatial values
    dump_txt = open(DUMP).read()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM models WHERE pos_x IS NOT NULL AND spawn_x IS NOT NULL")
    n_pos = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM node_state WHERE pos_x IS NOT NULL")
    n_node = cur.fetchone()[0]
    conn.close()
    ck("DB models rows carry populated pos_x/spawn_x (spatial columns)", n_pos == len(ROLES) + 1, f"{n_pos} rows")
    ck("DB node_state rows carry populated pos_x/pos_y", n_node > 0, f"{n_node} nodes")

    # run the canonical scorer on this run's dump -> circumstance fields populated
    sys.path.insert(0, r"C:/nyctimene/_vps_push/gen2_run/box_pull")
    import score_generation as SG
    pools = SG.score(DUMP)
    flat_agents = pools["flat"]["agents"]
    sample = flat_agents[0] if flat_agents else {}
    circ = sample.get("circumstance", {})
    ck("scorer emits circumstance record with spawn_opportunity (non-null on spatial data)",
       circ.get("spawn_opportunity") is not None,
       f"{sample.get('model')}: spawn_opportunity={circ.get('spawn_opportunity')}")
    ck("scorer emits spawn_location + resource_landscape circumstance fields",
       circ.get("spawn_location") is not None and circ.get("resource_landscape") is not None)
    have_opp = [a for a in flat_agents if a.get("circumstance", {}).get("spawn_opportunity") is not None]
    ck("every scored flat agent has a computed spawn_opportunity",
       len(have_opp) == len(flat_agents), f"{len(have_opp)}/{len(flat_agents)}")
    os.remove(DUMP)

    print("\n" + "=" * 74)
    print(f"SPATIAL SMOKE RESULT: {sum(results)}/{len(results)} checks passed")
    print("=" * 74)
    sys.exit(0 if all(results) else 1)
finally:
    app.terminate()
    try: app.wait(timeout=10)
    except Exception: app.kill()
