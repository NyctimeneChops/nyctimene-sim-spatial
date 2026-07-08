"""
Pure world placement for the space milestone (pass 1) - NO DB/HTTP.

Placement scheme (documented decision): UNIFORM-RANDOM spread. Every node and every
agent is dropped at a uniform-random (x, y) on the [0, PLANE_WIDTH] x [0, PLANE_HEIGHT]
plane. Random (not a grid) is deliberate: spawn location is meant to be a genuine
source of circumstance variance (near-vs-far from the resources an agent needs), which
is exactly the spawn-advantage signal the space milestone + circumstance-aware fitness
(spec section 7) are built to reason about. Each experiment group is a sealed sub-world
laid out on its own copy of the plane, so positions are only ever compared within a
group.

Determinism: the caller passes a seeded RNG (main.py seeds Python's global `random`
from EXPERIMENT_SEED before world init), so the spatial layout is pinned to the world
seed like every other world roll -- each generation gets a different, reproducible map.
"""
from constants import PLANE_WIDTH, PLANE_HEIGHT


def place_point(rng):
    """One uniform-random position (x, y) on the plane."""
    return (rng.uniform(0.0, PLANE_WIDTH), rng.uniform(0.0, PLANE_HEIGHT))


def place_points(rng, n):
    """n uniform-random positions on the plane (list of (x, y) tuples)."""
    return [place_point(rng) for _ in range(n)]
