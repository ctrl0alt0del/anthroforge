"""Coherent chart frames without a world-axis fallback or SciPy dependency."""
import numpy as np


def gaussian(values, sigma, axis):
    radius = int(4 * sigma + .5)
    offsets = np.arange(-radius, radius + 1)
    weights = np.exp(-.5 * (offsets / sigma) ** 2)
    pads = [(0, 0)] * values.ndim
    pads[axis] = (radius, radius)
    padded = np.pad(values, pads, mode="edge")
    return np.apply_along_axis(lambda row: np.convolve(row, weights / weights.sum(), mode="valid"), axis, padded)


def normalized(values):
    lengths = np.linalg.norm(values, axis=-1, keepdims=True)
    return np.divide(values, lengths, out=np.zeros_like(values), where=lengths > 0)


def coherent(values):
    result = values.copy().reshape(-1, 3)
    previous = None
    for normal in result:
        if np.linalg.norm(normal) == 0:
            continue
        if previous is not None and np.dot(normal, previous) < 0:
            normal *= -1
        previous = normal
    return result.reshape(values.shape)


def direction_field(base, direction):
    cross = np.cross(np.gradient(base, axis=0), np.gradient(base, axis=1))
    areas = np.linalg.norm(cross, axis=2)
    normals = coherent(normalized(cross))
    if direction == "SMOOTH":
        normals = gaussian(gaussian(normals, max(1, len(base)*.12), 0), max(1, base.shape[1]*.065), 1)
    elif direction == "SECTION":
        column = normalized(np.sum(normals * areas[..., None], axis=0))
        normals = np.broadcast_to(gaussian(column, max(1, base.shape[1]*.08), 0), base.shape).copy()
    elif direction != "LOCAL":
        raise ValueError("PROFILE_DIRECTION_UNSUPPORTED")
    lengths = np.linalg.norm(normals, axis=2)
    return normalized(normals), areas, lengths


def validate_frames(base, frames, affected):
    diagonal = np.linalg.norm(np.ptp(base.reshape(-1, 3), axis=0))
    if np.any(frames[1][affected] <= 1e-12 * diagonal**2):
        raise ValueError("PROFILE_FRAME_DEGENERATE: moving samples require nondegenerate chart frames.")
    if not np.isfinite(frames[0]).all() or np.any(frames[2][affected] <= 1e-12):
        raise ValueError("PROFILE_DIRECTION_DEGENERATE: moving samples require a coherent direction.")
