from mathutils import Vector

from .fiber_loop import resample_closed


def build_surface_topology(m, n, closed_v=False, closed_u=False):
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
        for j in _u_columns(n, closed_u):
            faces.append(_quad(i0, i1, j, n))

    return faces


def _u_columns(n, closed_u):
    return range(n) if closed_u and n > 2 else range(n - 1)


def _quad(i0, i1, j, n):
    j1 = (j + 1) % n
    return i0 * n + j, i1 * n + j, i1 * n + j1, i0 * n + j1


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


def build_surface_data(ordered_fiber_points, closed_v=False, closed_u=False):
    """
    Convenience builder:
    returns (verts, faces, n)
    """
    ok, reason, n = validate_fiber_point_grid(ordered_fiber_points)
    if not ok:
        raise ValueError(reason)

    m = len(ordered_fiber_points)
    verts = flatten_fiber_points(ordered_fiber_points)
    faces = build_surface_topology(m=m, n=n, closed_v=closed_v, closed_u=closed_u)
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
    Current muscle surface build only requires aligned node_count.
    Mid-touch layout may differ because rows are resampled uniformly later.
    Returns (ok, reason, node_count, anchor_indices)
    """
    if len(fibers) < 2:
        return False, "Need at least 2 fibers.", 0, []

    node_count = int(fibers[0].node_count)
    ref_indices = anchor_indices_from_fiber(fibers[0], node_count)

    for i, f in enumerate(fibers[1:], start=1):
        if int(f.node_count) != node_count:
            return False, f"Fiber[{i}] node_count mismatch.", 0, []

    return True, "", node_count, ref_indices


# ------------------------------
# Surface quality helpers
# ------------------------------

def _cumlen(points):
    out = [0.0]
    for i in range(1, len(points)):
        out.append(out[-1] + (points[i] - points[i - 1]).length)
    return out


def _sample_polyline(points, s):
    if s <= 0.0:
        return points[0].copy()

    cum = _cumlen(points)
    total = cum[-1]
    if total <= 1e-9:
        return points[0].copy()

    s = max(0.0, min(total, s))
    for i in range(1, len(points)):
        if cum[i] >= s:
            a = points[i - 1]
            b = points[i]
            span = max(1e-9, cum[i] - cum[i - 1])
            t = (s - cum[i - 1]) / span
            return a.lerp(b, t)

    return points[-1].copy()


def resample_uniform(points, n, closed=False):
    """
    Arc-length uniform resample for one fiber polyline.
    """
    if closed:
        return resample_closed(points, n)
    if not points:
        return []
    if n <= 1:
        return [points[0].copy()]
    return _resample_open(points, n)


def _resample_open(points, n):
    cum = _cumlen(points)
    total = cum[-1]
    if total <= 1e-9:
        return [points[0].copy() for _ in range(n)]
    out = []
    for k in range(n):
        s = (k / float(n - 1)) * total
        out.append(_sample_polyline(points, s))
    return out


def normalize_fibers_uniform(ordered_fiber_points, n, closed_u=False):
    """
    Resample all fibers to same N points.
    """
    return [resample_uniform(pts, n, closed=closed_u) for pts in ordered_fiber_points]


def densify_between_fibers(ordered_fiber_points):
    """
    Insert intermediate fiber rows so V spacing approaches U spacing.
    This reduces elongated quads and improves isotropic inflation behavior.
    """
    m = len(ordered_fiber_points)
    if m < 2:
        return ordered_fiber_points

    n = len(ordered_fiber_points[0])
    if n < 2:
        return ordered_fiber_points

    u_step = _avg_u_step(ordered_fiber_points, n)

    out = [ordered_fiber_points[0]]
    for i in range(m - 1):
        a = ordered_fiber_points[i]
        b = ordered_fiber_points[i + 1]
        inserts = _inserts_for_row_pair(a, b, n, u_step)
        for k in range(1, inserts + 1):
            t = k / float(inserts + 1)
            row = [a[j].lerp(b[j], t) for j in range(n)]
            out.append(row)
        out.append(b)
    return out


def _avg_u_step(rows, n):
    u_sum = 0.0
    u_cnt = 0
    for row in rows:
        for j in range(n - 1):
            u_sum += (row[j + 1] - row[j]).length
            u_cnt += 1
    return max(1e-6, u_sum / max(1, u_cnt))


def _inserts_for_row_pair(a, b, n, u_step):
    v_avg = 0.0
    for j in range(n):
        v_avg += (b[j] - a[j]).length
    v_avg /= float(n)
    return max(0, int(round(v_avg / u_step)) - 1)


def prepare_surface_rows(ordered_fiber_points, target_n=None, densify_v=True, closed_u=False):
    """
    Full preprocessing pipeline:
    1) uniform U resample
    2) optional V densification
    """
    if not ordered_fiber_points:
        return ordered_fiber_points

    if target_n is None:
        target_n = len(ordered_fiber_points[0])

    rows = normalize_fibers_uniform(ordered_fiber_points, target_n, closed_u=closed_u)
    if densify_v:
        rows = densify_between_fibers(rows)
    return rows
