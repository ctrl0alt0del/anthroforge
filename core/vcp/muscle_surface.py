from mathutils import Vector


def build_surface_topology(m, n, closed_v=False):
    """
    Build quad topology for a grid of M fibers x N nodes.
    vertex_index = i * n + j
    """
    if m < 2 or n < 2:
        return []

    faces = []

    v_pairs = [(i, i + 1) for i in range(m - 1)]
    if closed_v and m > 2:
        v_pairs.append((m - 1, 0))

    for i0, i1 in v_pairs:
        for j in range(n - 1):
            v0 = i0 * n + j
            v1 = i1 * n + j
            v2 = i1 * n + (j + 1)
            v3 = i0 * n + (j + 1)
            faces.append((v0, v1, v2, v3))

    return faces


def flatten_fiber_points(ordered_fiber_points):
    """
    Convert [[Vector,...],[Vector,...],...] -> [(x,y,z),...]
    """
    verts = []
    for pts in ordered_fiber_points:
        for p in pts:
            if isinstance(p, Vector):
                verts.append((p.x, p.y, p.z))
            else:
                verts.append((float(p[0]), float(p[1]), float(p[2])))
    return verts


def validate_fiber_point_grid(ordered_fiber_points):
    """
    v1 validation:
    - at least 2 fibers
    - each fiber has at least 2 points
    - all fibers same point count
    Returns (ok, reason, n)
    """
    m = len(ordered_fiber_points)
    if m < 2:
        return False, "Need at least 2 fibers.", 0

    n = len(ordered_fiber_points[0])
    if n < 2:
        return False, "Each fiber needs at least 2 nodes.", 0

    for i, pts in enumerate(ordered_fiber_points):
        if len(pts) != n:
            return False, f"Fiber[{i}] node count mismatch.", 0

    return True, "", n


def build_surface_data(ordered_fiber_points, closed_v=False):
    """
    Convenience builder:
    returns (verts, faces, n)
    """
    ok, reason, n = validate_fiber_point_grid(ordered_fiber_points)
    if not ok:
        raise ValueError(reason)

    m = len(ordered_fiber_points)
    verts = flatten_fiber_points(ordered_fiber_points)
    faces = build_surface_topology(m=m, n=n, closed_v=closed_v)
    return verts, faces, n


def build_anchor_loops(ordered_fiber_points, anchor_indices):
    """
    For each anchor node index A, return the vertex indices across fibers.
    Useful for deformation rings / debugging.

    returns dict[int, list[int]]
    """
    loops = {}
    if not ordered_fiber_points:
        return loops

    m = len(ordered_fiber_points)
    n = len(ordered_fiber_points[0])

    for a in anchor_indices:
        if a < 0 or a >= n:
            continue
        loops[a] = [i * n + a for i in range(m)]

    return loops


def anchor_indices_from_fiber(fiber_prop, node_count):
    """
    Derive stable anchor indices for one fiber:
    start(0), mid touch mapped, end(node_count-1)
    """
    if node_count < 2:
        return [0]

    k = len(getattr(fiber_prop, "mid_touches", []))
    indices = [0]

    if k > 0:
        for i in range(k):
            idx = int(round((i + 1) * (node_count - 1) / float(k + 1)))
            idx = max(1, min(node_count - 2, idx))
            if idx not in indices:
                indices.append(idx)

    indices.append(node_count - 1)
    return sorted(indices)


def validate_anchor_structure(fibers):
    """
    v1 anchor-structure validation:
    all fibers must have identical node_count and identical derived anchor indices.
    Returns (ok, reason, node_count, anchor_indices)
    """
    if len(fibers) < 2:
        return False, "Need at least 2 fibers.", 0, []

    node_count = int(fibers[0].node_count)
    ref_indices = anchor_indices_from_fiber(fibers[0], node_count)

    for i, f in enumerate(fibers[1:], start=1):
        if int(f.node_count) != node_count:
            return False, f"Fiber[{i}] node_count mismatch.", 0, []
        idxs = anchor_indices_from_fiber(f, node_count)
        if idxs != ref_indices:
            return False, f"Fiber[{i}] anchor structure mismatch.", 0, []

    return True, "", node_count, ref_indices
