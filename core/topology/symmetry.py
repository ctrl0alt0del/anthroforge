import numpy as np

from .model import SymmetryPlane


def normalized_plane(origin, normal):
    origin = np.asarray(origin, dtype=np.float64)
    normal = np.asarray(normal, dtype=np.float64)
    length = float(np.linalg.norm(normal))
    if not np.isfinite(origin).all() or not np.isfinite(normal).all() or length < 1e-12:
        raise ValueError("Symmetry plane requires a finite origin and non-zero normal.")
    return SymmetryPlane(origin, normal / length)


def signed_distances(points, plane):
    return (np.asarray(points) - plane.origin) @ plane.normal


def reflect_points(points, plane):
    values = np.asarray(points)
    distances = signed_distances(values, plane)
    return values - (2.0 * distances[:, None] * plane.normal)


def reflect_vectors(vectors, plane):
    values = np.asarray(vectors)
    return values - (2.0 * (values @ plane.normal)[:, None] * plane.normal)


def project_to_plane(points, plane):
    values = np.asarray(points)
    return values - (signed_distances(values, plane)[:, None] * plane.normal)
