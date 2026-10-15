from collections import Counter

import numpy as np

from .model import TopologyValidationReport


def face_edges(faces):
    values = np.asarray(faces, dtype=np.int64)
    edges = np.vstack([values[:, (i, (i + 1) % 4)] for i in range(4)])
    return np.sort(edges, axis=1)


def edge_counts(faces):
    edges, counts = np.unique(face_edges(faces), axis=0, return_counts=True)
    return edges, counts


def component_count(vertex_count, faces):
    adjacency = [set() for _ in range(int(vertex_count))]
    for first, second in np.unique(face_edges(faces), axis=0):
        adjacency[int(first)].add(int(second)); adjacency[int(second)].add(int(first))
    return _walk_components(adjacency)


def _walk_components(adjacency):
    pending, count = {i for i, links in enumerate(adjacency) if links}, 0
    while pending:
        stack, count = [pending.pop()], count + 1
        while stack:
            linked = adjacency[stack.pop()].intersection(pending)
            pending.difference_update(linked); stack.extend(linked)
    return count


def degenerate_count(vertices, faces):
    points = np.asarray(vertices)[np.asarray(faces)]
    first = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    second = np.cross(points[:, 2] - points[:, 0], points[:, 3] - points[:, 0])
    scale = max(float(np.max(np.ptp(vertices, axis=0))), 1.0)
    return int(np.count_nonzero((np.linalg.norm(first, axis=1) + np.linalg.norm(second, axis=1)) < scale * scale * 1e-12))


def max_valence(vertex_count, faces):
    values = np.zeros(int(vertex_count), dtype=np.int32)
    for first, second in np.unique(face_edges(faces), axis=0):
        values[int(first)] += 1; values[int(second)] += 1
    return int(values.max(initial=0))


def orientable(faces):
    directed = np.vstack([faces[:, (i, (i + 1) % 4)] for i in range(4)])
    signs = np.where(directed[:, 0] < directed[:, 1], 1, -1)
    edges = np.sort(directed, axis=1)
    groups = {}
    for edge, sign in zip(map(tuple, edges), signs):
        groups.setdefault(edge, []).append(int(sign))
    return all(len(items) == 1 or (len(items) == 2 and sum(items) == 0) for items in groups.values())


def _has_quads(faces):
    return bool(faces.ndim == 2 and faces.shape[1] == 4 and len(faces))


def _quad_metrics(vertices, faces):
    if not _has_quads(faces):
        return (), (), False, False, False, False
    edges, counts = edge_counts(faces)
    connected = component_count(len(vertices), faces) == 1
    clean = degenerate_count(vertices, faces) == 0
    return edges, counts, connected, orientable(faces), clean, max_valence(len(vertices), faces) <= 8


def validate_topology(vertices, faces, metrics=None):
    metrics = dict(metrics or {})
    checks = _checks(np.asarray(vertices), np.asarray(faces), metrics)
    failed = [name for name, passed in checks.items() if not passed]
    return TopologyValidationReport(
        valid=not failed, finite=checks["finite"], all_quads=checks["all_quads"],
        connected=checks["connected"], orientable=checks["orientable"],
        manifold=checks["manifold"], no_degenerates=checks["no_degenerates"],
        boundary_match=checks["boundary_match"], guide_preserved=checks["guide_preserved"],
        symmetry_ok=checks["symmetry_ok"], fidelity_ok=checks["fidelity_ok"],
        valence_ok=checks["valence_ok"], self_intersections=None if metrics.get("self_intersections", 0) is None else int(metrics.get("self_intersections", 0)),
        message="" if not failed else f"Validation failed: {', '.join(failed)}")


def _checks(vertices, faces, metrics):
    edges, counts, connected, oriented, clean, valence = _quad_metrics(vertices, faces)
    return {
        "finite": bool(len(vertices) and np.isfinite(vertices).all()),
        "all_quads": _has_quads(faces),
        "connected": connected,
        "orientable": oriented,
        "manifold": bool(len(counts) and np.all(np.asarray(counts) <= 2)),
        "no_degenerates": clean,
        "boundary_match": bool(metrics.get("boundary_match", True)),
        "guide_preserved": bool(metrics.get("guide_preserved", True)),
        "symmetry_ok": bool(metrics.get("symmetry_ok", True)),
        "fidelity_ok": bool(metrics.get("fidelity_ok", True)),
        "valence_ok": valence,
    }
