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


def compute_vertex_normals(points):
    m = len(points)
    n = len(points[0]) if m > 0 else 0
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
        im1 = max(0, i - 1)
        ip1 = min(m - 1, i + 1)
        for j in range(n):
            jm1 = max(0, j - 1)
            jp1 = min(n - 1, j + 1)
            tv = points[ip1][j] - points[im1][j]
            tu = points[i][jp1] - points[i][jm1]
            nrm = tv.cross(tu)
            if nrm.length <= 1e-10:
                nrm = points[i][j] - centroid
            if nrm.length <= 1e-10:
                nrm = Vector((0.0, 0.0, 1.0))
            else:
                nrm.normalize()
            normals[i][j] = nrm
    return normals


def apply_inflation_from_ctrl(base_points, muscle):
    out = [[p.copy() for p in row] for row in base_points]

    if not muscle.inflation_enabled:
        return out

    amount = float(muscle.inflation_max_value)
    radius = max(1e-8, float(muscle.inflation_falloff_radius))
    b_strength = max(0.0, min(1.0, float(getattr(muscle, "inflation_boundary_strength", 0.7))))
    b_band = max(0.1, float(getattr(muscle, "inflation_boundary_band", 2.0)))
    b_power = max(0.1, float(getattr(muscle, "inflation_boundary_power", 1.5)))
    depth = max(1e-8, float(getattr(muscle, "inflation_direction_depth", 0.05)))

    if amount <= 0.0:
        return out

    m = len(base_points)
    n = len(base_points[0]) if m > 0 else 0
    if m == 0 or n == 0:
        return out

    ctrl = Vector(muscle.inflation_ctrl_world)
    falloff_type = muscle.inflation_falloff_type
    normals = compute_vertex_normals(base_points)

    flip = bool(getattr(muscle, "flip_normals", False))
    sign = -1.0 if flip else 1.0

    min_d2 = None
    ci = 0
    cj = 0
    for i in range(m):
        for j in range(n):
            d2 = (base_points[i][j] - ctrl).length_squared
            if min_d2 is None or d2 < min_d2:
                min_d2 = d2
                ci, cj = i, j

    n0 = normals[ci][cj].copy()
    if n0.length <= 1e-10:
        n0 = Vector((0.0, 0.0, 1.0))
    else:
        n0.normalize()

    g = ctrl - (n0 * depth * sign)

    def is_boundary(i, j):
        on_u = (j == 0 or j == n - 1)
        on_v = (not bool(muscle.closed_v)) and (i == 0 or i == m - 1)
        return on_u or on_v

    def boundary_distance(i, j):
        du = min(j, n - 1 - j) if n > 1 else 0
        dv = 10**9 if bool(muscle.closed_v) else (min(i, m - 1 - i) if m > 1 else 0)
        return min(du, dv)

    for i in range(m):
        for j in range(n):
            p = base_points[i][j]
            if is_boundary(i, j):
                out[i][j] = p
                continue

            d = (p - ctrl).length
            t = d / radius
            if falloff_type != "GAUSSIAN" and t > 1.0:
                continue

            w = falloff_weight(t, falloff_type)
            if w <= 1e-8:
                continue

            bd = boundary_distance(i, j)
            t_edge = max(0.0, min(1.0, bd / b_band))
            r = t_edge * t_edge * (3.0 - 2.0 * t_edge)
            r = r ** b_power
            edge_alpha = (1.0 - b_strength) + b_strength * r

            dir_vec = p - g
            if dir_vec.length <= 1e-10:
                dir_vec = n0.copy()
            else:
                dir_vec.normalize()

            out[i][j] = p + dir_vec * (amount * w * edge_alpha)

    return out
