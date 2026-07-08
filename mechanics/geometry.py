"""
Pure 2D geometry for the space milestone (pass 1) - NO DB/HTTP/threads.

The world is a continuous plane (constants.PLANE_WIDTH x PLANE_HEIGHT). Positions
are floats. This module is the single source of truth for distance so the movement
cost and the (future) spatial prompt agree on the same geometry.
"""
import math


def distance(x0, y0, x1, y1):
    """Euclidean (straight-line) distance between two points on the plane."""
    return math.hypot(x1 - x0, y1 - y0)
