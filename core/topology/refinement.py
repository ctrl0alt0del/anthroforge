import numpy as np

from .constants import REFINEMENT_MUSCLE_PROXIMITY, REFINEMENT_NONE


def normalized_strategy(value):
    mode = str(value or REFINEMENT_NONE).upper()
    if mode not in {REFINEMENT_NONE, REFINEMENT_MUSCLE_PROXIMITY}:
        raise ValueError(f"Unsupported topology refinement strategy: {mode}")
    return mode


def muscle_proximity_weights(distances, diagonal, inner=0.01, outer=0.05):
    start, end = float(inner) * diagonal, float(outer) * diagonal
    values = np.clip((np.asarray(distances) - start) / max(end - start, 1.0e-12), 0.0, 1.0)
    smooth = values * values * (3.0 - 2.0 * values)
    return 1.0 - smooth


def muscle_target_lengths(lengths, weights, quad_boost=1.5):
    density = 1.0 + (float(quad_boost) - 1.0) * np.asarray(weights)
    return np.asarray(lengths, dtype=np.float64) / np.sqrt(density)
