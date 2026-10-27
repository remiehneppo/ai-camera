"""Shared 2D geometry algorithms for edge perception modules."""

from __future__ import annotations

from typing import Sequence

__all__ = ["point_in_polygon"]


def point_in_polygon(
    x: float,
    y: float,
    polygon: Sequence[Sequence[float]] | None,
) -> bool:
    """Ray casting algorithm for testing if a 2D point is inside a polygon."""
    if not polygon or len(polygon) < 3:
        return True
    n = len(polygon)
    inside = False
    p1x, p1y = polygon[0][0], polygon[0][1]
    for i in range(1, n + 1):
        p2 = polygon[i % n]
        p2x, p2y = p2[0], p2[1]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside
