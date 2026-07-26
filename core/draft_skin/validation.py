import numpy as np
from scipy.sparse.csgraph import connected_components

from .mesh import adjacency_matrix, face_edges, signed_volume
from .model import SkinValidationReport
from .status import check_cancelled


def validate_mesh(vertices, faces, source_inside=True, cancelled=None):
    checks = _mesh_checks(vertices, faces, source_inside, cancelled)
    valid = all(checks.values())
    failed = [name for name, passed in checks.items() if not passed]
    return SkinValidationReport(
        valid=valid,
        finite=checks["finite"],
        connected=checks["connected"],
        watertight=checks["watertight"],
        orientable=checks["orientable"],
        positive_volume=checks["positive_volume"],
        no_degenerates=checks["no_degenerates"],
        source_inside=checks["source_inside"],
        message="" if valid else f"Validation failed: {', '.join(failed)}",
    )


def _mesh_checks(vertices, faces, source_inside, cancelled):
    stages = (
        ("finite", lambda: bool(np.isfinite(vertices).all())),
        ("connected", lambda: _connected(vertices, faces)),
        ("watertight", lambda: _watertight(faces)),
        ("orientable", lambda: _orientable(faces)),
        ("positive_volume", lambda: signed_volume(vertices, faces) > 0.0),
        ("no_degenerates", lambda: _no_degenerates(vertices, faces)),
        ("source_inside", lambda: bool(source_inside)),
    )
    return {name: _checked(function, cancelled) for name, function in stages}


def _checked(function, cancelled):
    check_cancelled(cancelled)
    return function()


def _connected(vertices, faces):
    if not len(vertices) or not len(faces):
        return False
    count, _labels = connected_components(adjacency_matrix(len(vertices), faces), directed=False)
    return int(count) == 1


def _watertight(faces):
    if not len(faces):
        return False
    _edges, counts = np.unique(face_edges(faces), axis=0, return_counts=True)
    return bool(np.all(counts == 2))


def _orientable(faces):
    if not _watertight(faces):
        return False
    directed = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    signs = np.where(directed[:, 0] < directed[:, 1], 1, -1)
    edges = np.sort(directed, axis=1)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    return bool(np.all((signs[order][0::2] + signs[order][1::2]) == 0))


def _no_degenerates(vertices, faces):
    if not len(faces) or np.any(faces[:, 0] == faces[:, 1]):
        return False
    triangles = vertices[faces].astype(np.float64)
    area2 = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1)
    scale = max(float(np.max(np.ptp(vertices, axis=0))), 1.0)
    return bool(np.all(area2 > ((scale * scale) * 1.0e-12)))
