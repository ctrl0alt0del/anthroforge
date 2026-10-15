"""Hard structural guards, distinct from publishable geometry quality warnings."""
import math
import numpy as np


def validate_settings(settings):
    if settings.method not in {"LE", "FAST"}:
        raise ValueError("Unknown deformation method; no fallback is permitted.")
    if type(settings.fast_handles) is not int or not 5 <= settings.fast_handles <= 1024:
        raise ValueError("FAST handle count must be between 5 and 1024.")
    if type(settings.proxy_resolution) is not int or not 8 <= settings.proxy_resolution <= 256:
        raise ValueError("Proxy resolution must be between 8 and 256.")
    if not math.isfinite(settings.constraint_strength) or settings.constraint_strength <= 0:
        raise ValueError("Constraint strength must be finite and positive.")


def validate_mesh_identity(reference, vertices, faces, vertex_ids):
    a = reference.arrays
    if np.asarray(vertices).shape != a["vertices"].shape or not np.isfinite(vertices).all():
        raise ValueError("Final mesh vertex count changed or positions are nonfinite.")
    if not np.array_equal(faces, a["quads"]) or not np.array_equal(vertex_ids, a["vertex_ids"]):
        raise ValueError("Final mesh connectivity or vertex identities changed; reinitialize explicitly.")


def validate_anatomy(reference, contributors, arrays):
    from .reference import canonical
    expected = reference.metadata["contributors"]
    if canonical(contributors) != canonical(expected):
        raise ValueError("Contributor identities or material addresses changed; reinitialize explicitly.")
    a = reference.arrays; output = np.empty_like(a["samples"], dtype=np.float64)
    for index, row in enumerate(expected):
        selected = a["sample_owners"] == index
        points = np.asarray(arrays[row["key"]]); addresses = a["sample_addresses"][selected]
        if points.shape != (row["vertex_count"], 3) or np.any(addresses >= len(points)):
            raise ValueError("Unavailable anatomical sample address: " + row["key"])
        output[selected] = points[addresses]
    if not np.isfinite(output).all(): raise ValueError("Nonfinite current anatomy.")
    return output
