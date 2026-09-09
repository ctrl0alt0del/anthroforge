"""One scale policy shared by interactive and declarative native requests."""
import numpy as np
from .contracts import V2ResolvedTolerances, V2Quality


def resolve_tolerances(colliders, radius, quality):
    low, high, coordinate = bounds(colliders)
    diagonal = float(np.linalg.norm(high-low)) if low is not None else float(radius)
    length = max(diagonal, float(radius), 1e-6)
    coordinate = max(1., coordinate, length)
    floor = max(1e-9*length, 8*np.finfo(np.float32).eps*coordinate)
    slack = max(floor, .01*float(radius)) if radius > 0 else floor
    fixed = 1e-6 if quality is V2Quality.FINAL else 1e-4
    return V2ResolvedTolerances(length, coordinate, floor, slack, max(1e-7, 1e-6*length),
                                fixed, fixed, 1e-7 if quality is V2Quality.FINAL else 1e-5)


def bounds(colliders):
    if not colliders:
        return None, None, 1.
    lows = np.asarray([row.vertices.min(axis=0) for row in colliders])
    highs = np.asarray([row.vertices.max(axis=0) for row in colliders])
    coordinate = max(float(np.max(np.abs(lows))), float(np.max(np.abs(highs))))
    return lows.min(axis=0), highs.max(axis=0), coordinate
