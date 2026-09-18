"""Versioned world-distance section profiles; Blender-independent mathematics."""
from dataclasses import dataclass, replace
import numpy as np

PROFILE_VERSION = "section-profile-1"
PROFILE_FIELDS = ("section_profile_version", "section_depths", "section_peaks", "section_roundness", "section_direction")


@dataclass(frozen=True)
class SectionProfileSpec:
    version: int = 1
    depths: tuple = (0.025, 0.05, 0.05, 0.025)
    peaks: tuple = (0.5, 0.5, 0.5, 0.5)
    roundness: float = 1.0
    direction: str = "SMOOTH"


def checked_values(values, size, low, high, name):
    if np.asarray(values).dtype.kind not in "iuf":
        raise ValueError(f"PROFILE_PARAMETER_RANGE: {name} requires real numbers.")
    array = np.asarray(values, dtype=np.float64)
    if array.shape != (size,) or not np.isfinite(array).all() or np.any((array < low) | (array > high)):
        raise ValueError(f"PROFILE_PARAMETER_RANGE: {name} requires {size} finite values in [{low}, {high}].")
    return tuple(float(value) for value in array.astype(np.float32))


def canonical_profile(spec):
    if type(spec.version) is not int or spec.version != 1:
        raise ValueError(f"PROFILE_VERSION_UNSUPPORTED: {spec.version}; explicitly initialize or reset the profile.")
    if spec.direction not in ("LOCAL", "SMOOTH", "SECTION"):
        raise ValueError(f"PROFILE_DIRECTION_UNSUPPORTED: {spec.direction}")
    return SectionProfileSpec(1, checked_values(spec.depths, 4, 0, 10, "depths"),
        checked_values(spec.peaks, 4, 0.1, 0.9, "peaks"),
        checked_values((spec.roundness,), 1, 0.25, 4, "roundness")[0], spec.direction)


def profile_from_muscle(muscle):
    return canonical_profile(SectionProfileSpec(int(getattr(muscle, "section_profile_version", 0)),
        tuple(getattr(muscle, "section_depths", ())), tuple(getattr(muscle, "section_peaks", ())),
        float(getattr(muscle, "section_roundness", 1)), str(getattr(muscle, "section_direction", "SMOOTH"))))


def reset_profile(depth):
    value = checked_values((depth,), 1, 0, 10, "peak depth")[0]
    return canonical_profile(SectionProfileSpec(depths=(value * .5, value, value, value * .5)))


def scale_profile(spec, factor):
    if not np.isfinite(factor) or factor < 0:
        raise ValueError("PROFILE_SCALE_RANGE: scale must be finite and nonnegative.")
    return canonical_profile(replace(canonical_profile(spec), depths=tuple(value * factor for value in spec.depths)))


def profile_properties(spec):
    spec = canonical_profile(spec)
    return dict(zip(PROFILE_FIELDS, (spec.version, spec.depths, spec.peaks, spec.roundness, spec.direction)))


def _endpoint(first, second):
    slope = (3 * first - second) * .5
    if np.sign(slope) != np.sign(first):
        return 0.0
    return 3 * first if np.sign(first) != np.sign(second) and abs(slope) > abs(3 * first) else slope


def pchip(values, samples):
    """Shape-preserving Hermite interpolation on the six fixed, equal stations."""
    y = np.asarray(values, dtype=np.float64)
    slopes = np.diff(y) * 5
    tangents = np.zeros(6)
    same = (slopes[:-1] * slopes[1:]) > 0
    tangents[1:-1][same] = 2 / (1 / slopes[:-1][same] + 1 / slopes[1:][same])
    tangents[0], tangents[-1] = _endpoint(*slopes[:2]), _endpoint(*slopes[-2:][::-1])
    position = np.clip(np.asarray(samples) * 5, 0, 5)
    index = np.minimum(position.astype(int), 4)
    t = position - index
    return ((2*t**3-3*t**2+1)*y[index] + (t**3-2*t**2+t)*.2*tangents[index]
            + (-2*t**3+3*t**2)*y[index+1] + (t**3-t**2)*.2*tangents[index+1])


def height_field(shape, spec):
    across, along = np.linspace(0, 1, shape[0])[:, None], np.linspace(0, 1, shape[1])
    depth = pchip((0, *spec.depths, 0), along)
    peak = pchip((spec.peaks[0], *spec.peaks, spec.peaks[-1]), along)
    x = np.where(across <= peak, across / peak, (1-across) / (1-peak))
    height = np.maximum(depth, 0) * np.maximum(0, x*(2-x)) ** spec.roundness
    height[[0, -1], :], height[:, [0, -1]] = 0, 0
    return height


def checked_grid(grid):
    base = np.asarray(grid, dtype=np.float64)
    if base.ndim != 3 or min(base.shape[:2]) < 3 or base.shape[2] != 3 or not np.isfinite(base).all():
        raise ValueError("PROFILE_GRID_INVALID: a finite grid with at least three samples on each axis is required.")
    return base


def apply_profile(grid, spec, enabled=True, flip=False, parity=1, frames=None):
    from .muscle_profile_frames import direction_field, validate_frames
    spec, base = canonical_profile(spec), checked_grid(grid)
    if type(parity) is not int or parity not in (-1, 1):
        raise ValueError("PROFILE_PARITY_INVALID: orientation parity must be +1 or -1.")
    height = height_field(base.shape, spec)
    if not enabled or not np.any(height):
        return base.copy()
    frames = frames if frames is not None else direction_field(base, spec.direction)
    validate_frames(base, frames, height > 0)
    result = base + (height * parity * (-1 if flip else 1))[..., None] * frames[0]
    result[[0, -1], :], result[:, [0, -1]] = base[[0, -1], :], base[:, [0, -1]]
    return result
