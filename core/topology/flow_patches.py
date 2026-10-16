"""Recover evaluated patch grids using explicit assembly vertex identities."""
import numpy as np


def branch_grids(assembly, result):
    from ..vcp.branched_surface import assemble, _branch_map
    base, faces = assemble(assembly)
    vertices = validate_result(result, base, faces)
    count = assembly.main.size // 3
    patches = [("main", vertices[:count].reshape(assembly.main.shape), assembly.flip, None)]
    for branch in assembly.branches:
        mapping, extra = _branch_map(assembly.main, branch.grid, branch, count)
        patches.append((branch.connection.id, vertices[mapping].reshape(branch.grid.shape),
                        (branch.connection.boundary == -1) != assembly.flip, seam_metadata(branch)))
        count += len(extra)
    return tuple(patches)


def seam_metadata(branch):
    return dict(parent="main", boundary=branch.connection.boundary,
                parent_samples=branch.seam.tolist(), child_column=0,
                connector_width=branch.connection.width)


def grid_samples(grid, owner, flip=False):
    along, across = np.gradient(grid, axis=1), np.gradient(grid, axis=0)
    normal = np.cross(across, along) * (-1 if flip else 1)
    select = (slice(1, -1, 2), slice(1, -1, 3))
    p, d, n = (a[select].reshape(-1, 3) for a in (grid, along, normal))
    lengths, areas = np.linalg.norm(d, axis=1), np.linalg.norm(n, axis=1)
    valid = (lengths > 1e-12) & (areas > 1e-12)
    return np.column_stack((p[valid], d[valid]/lengths[valid, None],
                            n[valid]/areas[valid, None], np.full(valid.sum(), owner)))


def validate_result(result, base, faces):
    vertices = np.asarray(result.inflated_vertices)
    if result.error or not np.array_equal(result.faces, faces):
        raise ValueError("Branched FLOW requires unchanged material connectivity.")
    if vertices.shape != base.shape or not np.isfinite(vertices).all():
        raise ValueError("Invalid evaluated branched FLOW positions.")
    return vertices
