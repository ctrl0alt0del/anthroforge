import numpy as np
from scipy.spatial import cKDTree

try:
    from ...core.topology.constants import REGION_AUTO
    from ...core.topology.ownership import vertex_areas
    from ...core.topology.refine import refine_quads
except ImportError:
    from core.topology.constants import REGION_AUTO
    from core.topology.ownership import vertex_areas
    from core.topology.refine import refine_quads

from .density_runtime import sample_density


def base_quad_target(capture, density, reserved):
    if not density or not len(density[1]):
        return capture.settings.target_quad_count
    area = float(np.sum(vertex_areas(capture.vertices, capture.triangles)))
    edge = float(np.max(density[1]))
    predicted = round(area / max(edge * edge, 1.0e-20)) + int(reserved)
    return min(capture.settings.target_quad_count, max(1000, predicted))


def refine_to_density(capture, result, density, passes=2):
    current = result
    for _unused in range(int(passes)):
        refined = _refine_pass(capture, current, density)
        if len(refined[1]) == len(current[1]):
            break
        current = refined
    return current


def _refine_pass(capture, result, density):
    vertices, faces, regions, guides = result
    _owners, lengths = sample_density(capture, density[0], density[1], vertices)
    scores = _face_scores(vertices, faces, lengths)
    candidates = np.flatnonzero((scores > 1.35) & (regions == REGION_AUTO))
    if not len(candidates) or len(faces) >= capture.settings.target_quad_count:
        return result
    ordered = _candidate_groups(capture, vertices, faces, candidates, scores)
    target = capture.settings.target_quad_count
    return _best_refinement(vertices, faces, regions, guides, ordered, target)


def _face_scores(vertices, faces, lengths):
    points = np.asarray(vertices)[np.asarray(faces, dtype=np.int64)]
    first = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    second = np.cross(points[:, 2] - points[:, 0], points[:, 3] - points[:, 0])
    areas = 0.5 * (np.linalg.norm(first, axis=1) + np.linalg.norm(second, axis=1))
    desired = np.mean(np.asarray(lengths)[np.asarray(faces, dtype=np.int64)], axis=1)
    return areas / np.maximum(desired * desired, 1.0e-20)


def _best_refinement(vertices, faces, regions, guides, ordered, target):
    low, high, best = 1, len(ordered), (vertices, faces, regions, guides)
    for _unused in range(8):
        if low > high:
            break
        count = (low + high) // 2
        trial = _refined_result(vertices, faces, regions, guides, _flatten(ordered[:count]))
        if _even_boundaries(trial[1]):
            best = min((best, trial), key=lambda item: abs(len(item[1]) - target))
        low, high = (count + 1, high) if len(trial[1]) < target else (low, count - 1)
    return best


def _refined_result(vertices, faces, regions, guides, selected):
    mask = np.zeros(len(faces), dtype=bool); mask[np.asarray(selected, dtype=np.int64)] = True
    points, quads, parents = refine_quads(vertices, faces, mask)
    return points, quads, np.asarray(regions)[parents], np.asarray(guides)[parents]


def _candidate_groups(capture, vertices, faces, candidates, scores):
    if capture.plane is None:
        return tuple((int(index),) for index in candidates[np.argsort(-scores[candidates])])
    centers = np.mean(np.asarray(vertices)[np.asarray(faces)], axis=1)
    reflected = _reflect(centers, capture.plane)
    partners = cKDTree(centers).query(reflected, workers=-1)[1]
    allowed, groups = set(map(int, candidates)), {}
    for index in candidates:
        pair = tuple(sorted((int(index), int(partners[index]))))
        if pair[1] in allowed:
            groups[pair] = max(scores[list(pair)])
    return tuple(pair for pair, _score in sorted(groups.items(), key=lambda item: -item[1]))


def _reflect(points, plane):
    values = np.asarray(points); normal = np.asarray(plane.normal)
    distances = (values - np.asarray(plane.origin)) @ normal
    return values - 2.0 * distances[:, None] * normal


def _flatten(groups):
    return np.asarray([index for group in groups for index in group], dtype=np.int64)


def _boundary_edges(faces):
    counts = {}
    for face in np.asarray(faces, dtype=np.int64):
        for index in range(4):
            edge = tuple(sorted((int(face[index]), int(face[(index + 1) % 4]))))
            counts[edge] = counts.get(edge, 0) + 1
    return tuple(edge for edge, count in counts.items() if count == 1)


def _even_boundaries(faces):
    pending, adjacency = set(_boundary_edges(faces)), {}
    for first, second in pending:
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)
    lengths = []
    while pending:
        lengths.append(_consume_boundary(pending, adjacency))
    return all(length % 2 == 0 for length in lengths)


def _consume_boundary(pending, adjacency):
    edge = pending.pop(); start, current = edge
    previous, length = start, 1
    while current != start:
        following = next(item for item in adjacency[current] if item != previous)
        pending.discard(tuple(sorted((current, following))))
        previous, current, length = current, following, length + 1
    return length
