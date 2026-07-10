"""
Pure teleport-per-tick movement resolver (space milestone pass 1) - NO DB/HTTP.

nyctimene_space_milestone_design.md section 2, PHASE ONE (teleport-per-tick):
a move pays ENERGY proportional to the straight-line distance from the agent's
CURRENT position to the destination, and (if affordable) the agent ARRIVES the
SAME tick -- an energy cost, no time cost. Move is a COSTED action: it is DENIED
if the balance cannot cover the distance cost, exactly like harvest/build/cook.

Kept pure (like mechanics/energy.py) so the geometry + cost + gating are testable
without a GPU/DB. The agent loop wires a successful move to models.pos_x/pos_y and
the energy ledger; a denied move changes neither.
"""
from constants import (MOVE_COST_PER_UNIT, AT_NODE_EPSILON,
                       DISPLACEMENT_STEP, DISPLACEMENT_DENY_THRESHOLD)
from mechanics.geometry import distance


def at_node(ax, ay, nx, ny):
    """SPACE pass 3: is an agent at (ax, ay) AT the node (nx, ny)? True within
    AT_NODE_EPSILON. Teleport-per-tick lands the mover exactly on the node point, so
    this is effectively exact-coordinate presence (the epsilon only absorbs float
    drift). Used to gate node-located actions (harvest, build-well) on presence."""
    return distance(ax, ay, nx, ny) <= AT_NODE_EPSILON


def on_any_node(x, y, node_points):
    """True if (x,y) coincides (within AT_NODE_EPSILON) with any node point. Builds are
    barred from node points; harvest/movement presence is unaffected (agents may still
    stand on a node to harvest and co-harvest)."""
    return any(at_node(x, y, nx, ny) for (nx, ny) in node_points)


def destination_occupied(dest_x, dest_y, others, dest_is_node):
    """SPACE pass-3 (CORRECTED collision model): exact-point occupancy check for a MOVE.

    Movement is NEVER blocked by another agent's PROXIMITY, and never by "passing
    near/through" one (teleport-per-tick has no mid-transit occupancy -- pass-through is a
    non-concept). A move is DENIED only when the DESTINATION POINT is already occupied by
    another agent in the same sealed group AND the destination is NOT a node.

    NODE destinations are NEVER blocked: multiple agents may stack on a node's single
    point to co-harvest it (the load-bearing cooperation rule). Since pass-1 move only
    ever targets nodes, no move is occupancy-blocked in practice today; the non-node
    branch is the general invariant for any future non-node destination.

    `others` = (x, y) of the OTHER agents in the SAME group. Returns the occupying (x, y)
    if the move is blocked, else None. "Same point" = within AT_NODE_EPSILON (exact match;
    reuses at_node). Proximity/radius plays NO role -- there is no PERSONAL_RADIUS anymore.

    Same-tick, same NON-node destination: the tick resolves agents sequentially and each
    move reads the CURRENT occupancy at resolve time, so the first-resolved agent occupies
    the point and any later agent aiming at the same point is denied -- deterministic and
    consistent with how the tick resolves every other action."""
    if dest_is_node:
        return None
    for (qx, qy) in others:
        if at_node(dest_x, dest_y, qx, qy):   # exact-point occupancy
            return (qx, qy)
    return None


def _occupied(x, y, obstacles):
    """True if (x,y) coincides (within AT_NODE_EPSILON) with any obstacle point."""
    return any(at_node(x, y, ox, oy) for (ox, oy) in obstacles)


def resolve_landing(cx, cy, tx, ty, obstacles, target_is_node,
                    step=DISPLACEMENT_STEP, deny_threshold=DISPLACEMENT_DENY_THRESHOLD):
    """SPATIAL CLEANUP -- GRACEFUL DISPLACEMENT. Resolve a TARGET point (tx,ty), reached
    from the actor's current position (cx,cy), to the ACTUAL landing point, given the
    occupied `obstacles` (other agents + other-owned shelter points, same sealed group).

    - NODE target -> exempt: land EXACTLY on it (co-harvest stacking; no displacement).
    - FREE non-node target -> land exactly on it.
    - OCCUPIED non-node target -> the action still HAPPENS but lands at the nearest free
      point IN THE DIRECTION OF INTENT: step back from the target toward (cx,cy), past the
      occupied point(s), to the first free point (granularity DISPLACEMENT_STEP).
    - DEFERRED DENY HOOK (dormant): if the displacement (intended target -> landing) exceeds
      `deny_threshold`, the action is DENIED for the tick instead (default threshold = inf,
      so this never fires on today's empty plane).

    Returns {land_x, land_y, displaced, displacement, denied}. Cost is charged by the caller
    on distance(cx,cy -> land), i.e. the ACTUAL distance traveled."""
    if target_is_node or not _occupied(tx, ty, obstacles):
        return {"land_x": tx, "land_y": ty, "displaced": False,
                "displacement": 0.0, "denied": False}
    d = distance(cx, cy, tx, ty)
    lx, ly = cx, cy   # fallback: no free point on the segment -> stay put (empty plane won't hit)
    if d > 0:
        ux, uy = (tx - cx) / d, (ty - cy) / d      # unit direction current -> target
        back = step
        while back < d:
            px, py = tx - ux * back, ty - uy * back   # step back from the target
            if not _occupied(px, py, obstacles):
                lx, ly = px, py
                break
            back += step
    disp = distance(lx, ly, tx, ty)
    if disp > deny_threshold:
        # dormant deny hook: refuse rather than displace this far
        return {"land_x": cx, "land_y": cy, "displaced": False,
                "displacement": disp, "denied": True}
    return {"land_x": lx, "land_y": ly, "displaced": True,
            "displacement": disp, "denied": False}


def move_cost(dist):
    """Energy cost of moving `dist` units: round(dist * MOVE_COST_PER_UNIT).
    Rounded to an integer because the energy ledger is integer-valued."""
    return round(dist * MOVE_COST_PER_UNIT)


def resolve_move(cur_x, cur_y, dest_x, dest_y, energy):
    """Resolve one teleport move against `energy` -- the balance AFTER basal +
    inference, i.e. the same point in the tick where costed actions gate. Pure.

    Returns:
      distance - euclidean distance current -> destination
      cost     - move_cost(distance)
      applied  - True iff affordable (energy >= cost)
      new_x/y  - the DESTINATION if applied (teleport, same tick),
                 else the UNCHANGED current position (denied)
      energy   - energy - cost if applied, else unchanged
    Position updates ONLY on a successful (affordable) move.
    """
    dist = distance(cur_x, cur_y, dest_x, dest_y)
    cost = move_cost(dist)
    if energy >= cost:
        return {"distance": dist, "cost": cost, "applied": True,
                "new_x": dest_x, "new_y": dest_y, "energy": energy - cost}
    return {"distance": dist, "cost": cost, "applied": False,
            "new_x": cur_x, "new_y": cur_y, "energy": energy}
