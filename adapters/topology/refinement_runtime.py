import numpy as np
from scipy.spatial import cKDTree

try:
    from ...core.topology.constants import REFINEMENT_MUSCLE_PROXIMITY
    from ...core.topology.refinement import muscle_proximity_weights, muscle_target_lengths
except ImportError:
    from core.topology.constants import REFINEMENT_MUSCLE_PROXIMITY
    from core.topology.refinement import muscle_proximity_weights, muscle_target_lengths


def apply_refinement_strategy(capture, lengths):
    if capture.settings.refinement_strategy != REFINEMENT_MUSCLE_PROXIMITY:
        return np.asarray(lengths), (), {}
    points = muscle_points(capture)
    if not len(points):
        warning = "Muscle-proximity refinement found no muscle surfaces; using uniform density."
        return np.asarray(lengths), (warning,), {"muscle_vertices": 0}
    distances = cKDTree(points).query(capture.vertices, workers=-1)[0]
    diagonal = max(float(np.linalg.norm(capture.upper - capture.lower)), 1.0e-12)
    weights = muscle_proximity_weights(distances, diagonal)
    stats = _statistics(points, weights, diagonal)
    return muscle_target_lengths(lengths, weights), (), stats


def muscle_points(capture):
    values = [np.asarray(item.vertices) for item in capture.ownership_sources
              if item.entity_type == "MUSCLE" and len(item.vertices)]
    return np.concatenate(values) if values else np.empty((0, 3), dtype=np.float64)


def has_muscle_refinement(capture):
    return capture.settings.refinement_strategy == REFINEMENT_MUSCLE_PROXIMITY and bool(len(muscle_points(capture)))


def _statistics(points, weights, diagonal):
    active = int(np.count_nonzero(np.asarray(weights) > 0.01))
    return {"muscle_vertices": int(len(points)), "influenced_skin_vertices": active,
            "influence_inner": 0.01 * diagonal, "influence_outer": 0.05 * diagonal,
            "maximum_density_multiplier": 1.5}
