from math import exp
from mathutils import Vector


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

    centroid = Vector((0.0, 0.0, 0.0))
    cnt = 0
    for i in range(m):
        for j in range(n):
            centroid += points[i][j]
            cnt += 1
    centroid /= max(1, cnt)

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


def apply_inflation_from_ctrl(base_points, muscle):
    out = [[p.copy() for p in row] for row in base_points]
    if not muscle.inflation_enabled:
        return out
    params = _inflation_params(muscle)
    if params["amount"] <= 0.0:
        return out
    setup = _inflation_setup(base_points, muscle, params)
    if setup is None:
        return out
    m, n, ctrl, n0, g = setup
    for i in range(m):
        for j in range(n):
            p = base_points[i][j]
            edge_alpha = _edge_alpha(i, j, m, n, muscle, params["b_strength"], params["b_band"], params["b_power"])
            if edge_alpha == 0.0:
                out[i][j] = p
                continue
            d = (p - ctrl).length
            t = d / params["radius"]
            if params["falloff_type"] != "GAUSSIAN" and t > 1.0:
                continue
            w = falloff_weight(t, params["falloff_type"])
            if w <= 1e-8:
                continue
            dir_vec = _safe_normal(p - g) if (p - g).length > 1e-10 else n0.copy()
            out[i][j] = p + dir_vec * (params["amount"] * w * edge_alpha)
    return out


def _inflation_setup(base_points, muscle, params):
    m, n = _grid_shape(base_points)
    if m == 0 or n == 0:
        return None
    ctrl = Vector(muscle.inflation_ctrl_world)
    normals = compute_vertex_normals(base_points)
    ci, cj = _closest_ctrl_index(base_points, ctrl)
    n0 = _safe_normal(normals[ci][cj])
    g = ctrl - (n0 * params["depth"] * params["sign"])
    return m, n, ctrl, n0, g


def _inflation_params(muscle):
    amount = float(muscle.inflation_max_value)
    return {
        "amount": amount,
        "radius": max(1e-8, float(muscle.inflation_falloff_radius)),
        "b_strength": max(0.0, min(1.0, float(getattr(muscle, "inflation_boundary_strength", 0.7)))),
        "b_band": max(0.1, float(getattr(muscle, "inflation_boundary_band", 2.0))),
        "b_power": max(0.1, float(getattr(muscle, "inflation_boundary_power", 1.5))),
        "depth": max(1e-8, float(getattr(muscle, "inflation_direction_depth", 0.05))),
        "falloff_type": muscle.inflation_falloff_type,
        "sign": -1.0 if bool(getattr(muscle, "flip_normals", False)) else 1.0,
    }
