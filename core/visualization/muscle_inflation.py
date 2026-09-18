from math import exp
from mathutils import Vector

from ..vcp.runtime_state import muscle_inflation_ctrl_world


def falloff_weight(t, falloff_type):
    x = max(0.0, min(1.0, t))
    if falloff_type == "LINEAR":
        return 1.0 - x
    if falloff_type == "SMOOTHSTEP":
        s = x * x * (3.0 - 2.0 * x)
        return 1.0 - s
    return exp(-4.0 * x * x)


def _grid_shape(points):
    m = len(points)
    n = len(points[0]) if m > 0 else 0
    return m, n


def _safe_normal(v):
    if v.length <= 1e-10:
        return Vector((0.0, 0.0, 1.0))
    out = v.copy()
    out.normalize()
    return out


def _normal_at(points, i, j, m, n, centroid):
    im1, ip1 = max(0, i - 1), min(m - 1, i + 1)
    jm1, jp1 = max(0, j - 1), min(n - 1, j + 1)
    tv = points[ip1][j] - points[im1][j]
    tu = points[i][jp1] - points[i][jm1]
    nrm = tv.cross(tu)
    if nrm.length <= 1e-10:
        nrm = points[i][j] - centroid
    return _safe_normal(nrm)


def compute_vertex_normals(points):
    m, n = _grid_shape(points)
    if m == 0 or n == 0:
        return []
    return _vertex_normals(points, m, n, _grid_centroid(points, m, n))


def _grid_centroid(points, m, n):
    centroid = Vector((0.0, 0.0, 0.0))
    for i in range(m):
        for j in range(n):
            centroid += points[i][j]
    return centroid / max(1, m * n)


def _vertex_normals(points, m, n, centroid):
    normals = [[Vector((0.0, 0.0, 1.0)) for _ in range(n)] for _ in range(m)]
    for i in range(m):
        for j in range(n):
            normals[i][j] = _normal_at(points, i, j, m, n, centroid)
    return normals


def _closest_ctrl_index(points, ctrl):
    m, n = _grid_shape(points)
    min_d2, ci, cj = None, 0, 0
    for i in range(m):
        for j in range(n):
            d2 = (points[i][j] - ctrl).length_squared
            if min_d2 is None or d2 < min_d2:
                min_d2, ci, cj = d2, i, j
    return ci, cj


def _edge_alpha(i, j, m, n, muscle, b_strength, b_band, b_power):
    prepared = getattr(muscle, "boundary_weights", None)
    if prepared is not None:
        return float(prepared[i, j])
    on_u = (j == 0 or j == n - 1)
    on_v = (not bool(muscle.closed_v)) and (i == 0 or i == m - 1)
    if on_u or on_v:
        return 0.0
    du = min(j, n - 1 - j) if n > 1 else 0
    dv = 10**9 if bool(muscle.closed_v) else (min(i, m - 1 - i) if m > 1 else 0)
    bd = min(du, dv)
    t_edge = max(0.0, min(1.0, bd / b_band))
    r = (t_edge * t_edge * (3.0 - 2.0 * t_edge)) ** b_power
    return (1.0 - b_strength) + b_strength * r


def _copy_grid(points):
    return [[p.copy() for p in row] for row in points]


def apply_inflation_from_ctrl(base_points, muscle):
    out = _copy_grid(base_points)
    if not muscle.inflation_enabled:
        return out
    params = _inflation_params(muscle)
    if params["amount"] <= 0.0:
        return out
    setup = _inflation_setup(base_points, muscle, params)
    if setup is None:
        return out
    return _ctrl_rows(base_points, out, muscle, params, setup)


def _ctrl_rows(base_points, out, muscle, params, setup):
    m, n, ctrl, n0, g = setup
    for i in range(m):
        for j in range(n):
            out[i][j] = _ctrl_point(base_points, ctrl, n0, g, i, j, m, n, muscle, params)
    return out


def _ctrl_point(base_points, ctrl, n0, g, i, j, m, n, muscle, params):
    p = base_points[i][j]
    edge = _edge_alpha(i, j, m, n, muscle, params["b_strength"], params["b_band"], params["b_power"])
    t = (p - ctrl).length / params["radius"] if edge > 0.0 else 2.0
    if edge <= 0.0 or (params["falloff_type"] != "GAUSSIAN" and t > 1.0):
        return p
    weight = falloff_weight(t, params["falloff_type"])
    if weight <= 1e-8:
        return p
    direction = _safe_normal(p - g) if (p - g).length > 1e-10 else n0.copy()
    return p + direction * (params["amount"] * weight * edge)


def apply_inflation_distributed(base_points, muscle):
    out = _copy_grid(base_points)
    setup = _distributed_setup(base_points, muscle)
    if setup is None:
        return out
    normals, params = setup
    return _distributed_rows(base_points, out, normals, muscle, params)


def _inflation_setup(base_points, muscle, params):
    m, n = _grid_shape(base_points)
    if m == 0 or n == 0:
        return None
    ctrl = Vector(muscle_inflation_ctrl_world(muscle))
    normals = compute_vertex_normals(base_points)
    ci, cj = _closest_ctrl_index(base_points, ctrl)
    n0 = _safe_normal(normals[ci][cj])
    g = ctrl - (n0 * params["depth"] * params["sign"])
    return m, n, ctrl, n0, g


def _distributed_setup(base_points, muscle):
    params = _enabled_params(muscle)
    m, n = _grid_shape(base_points)
    if params is None or m == 0 or n == 0:
        return None
    normals = _coherent_normals(compute_vertex_normals(base_points))
    return normals, params


def _enabled_params(muscle):
    if not bool(getattr(muscle, "inflation_enabled", True)):
        return None
    params = _inflation_params(muscle)
    return params if params["amount"] > 0.0 else None


def _coherent_normals(normals):
    out = [[_safe_normal(item) for item in row] for row in normals]
    for i, row in enumerate(out):
        for j, item in enumerate(row):
            ref = _coherent_ref(out, i, j)
            out[i][j] = item if ref is None or item.dot(ref) >= 0.0 else -item
    return out


def _coherent_ref(normals, i, j):
    if j > 0:
        return normals[i][j - 1]
    return normals[i - 1][j] if i > 0 else None


def _distributed_rows(base_points, out, normals, muscle, params):
    m, n = _grid_shape(base_points)
    for i in range(m):
        for j in range(n):
            out[i][j] = _distributed_point(base_points, normals, i, j, m, n, muscle, params)
    return out


def _distributed_point(base_points, normals, i, j, m, n, muscle, params):
    p = base_points[i][j]
    amount = _distributed_amount(base_points, normals, i, j, m, n, muscle, params)
    if amount <= 0.0:
        return p
    direction = _distributed_direction(normals[i][j], params["sign"])
    return p + direction * amount


def _distributed_amount(base_points, normals, i, j, m, n, muscle, params):
    edge = _edge_alpha(i, j, m, n, muscle, params["b_strength"], params["b_band"], params["b_power"])
    weights = getattr(muscle, "length_weights", None)
    fade = _length_fade(j, n, params["length_taper_band"]) if weights is None else float(weights[i, j])
    raw = params["amount"] * edge * fade
    if raw <= 0.0 or _normal_stability(normals, i, j, m, n) >= 0.85:
        return max(0.0, raw)
    return _stabilized_amount(base_points, normals, i, j, m, n, raw)


def _distributed_direction(normal, sign):
    direction = _safe_normal(normal)
    return direction if sign >= 0.0 else -direction


def _distributed_limit(base_points, i, j, m, n):
    radius = _support_radius(base_points, i, j, m, n)
    return radius * 2.5 if radius > 1e-8 else 0.0


def _stabilized_amount(base_points, normals, i, j, m, n, raw):
    clamped = min(raw, _distributed_limit(base_points, i, j, m, n))
    weight = _normal_stability(normals, i, j, m, n) / 0.85
    return _lerp(clamped, raw, max(0.0, min(1.0, weight)))


def _support_radius(base_points, i, j, m, n):
    lengths = []
    for ii, jj in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)):
        if 0 <= ii < m and 0 <= jj < n:
            lengths.append((base_points[ii][jj] - base_points[i][j]).length)
    return min(lengths) if lengths else 0.0


def _normal_stability(normals, i, j, m, n):
    dots = []
    for ii, jj in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)):
        if 0 <= ii < m and 0 <= jj < n:
            dots.append(max(0.0, normals[i][j].dot(normals[ii][jj])))
    return min(dots) if dots else 1.0


def _lerp(a, b, t):
    return a + (b - a) * t


def _length_fade(j, n, taper_band):
    band = max(1.0, float(taper_band) * max(0.0, n - 1.0))
    u = max(0.0, min(1.0, min(j, max(0, n - 1 - j)) / float(band)))
    return u * u * (3.0 - 2.0 * u)


def _inflation_params(muscle):
    amount = float(muscle.inflation_max_value)
    return {
        "amount": amount,
        "radius": max(1e-8, float(muscle.inflation_falloff_radius)),
        "b_strength": max(0.0, min(1.0, float(getattr(muscle, "inflation_boundary_strength", 0.7)))),
        "b_band": max(0.1, float(getattr(muscle, "inflation_boundary_band", 2.0))),
        "b_power": max(0.1, float(getattr(muscle, "inflation_boundary_power", 1.5))),
        "length_taper_band": max(0.01, min(0.49, float(getattr(muscle, "inflation_length_taper_band", 0.2)))),
        "depth": max(1e-8, float(getattr(muscle, "inflation_direction_depth", 0.05))),
        "falloff_type": muscle.inflation_falloff_type,
        "sign": -1.0 if bool(getattr(muscle, "flip_normals", False)) else 1.0,
    }
