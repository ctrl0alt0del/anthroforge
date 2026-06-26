from math import atan2

from mathutils import Quaternion, Vector


def close_loop(points, eps=1.0e-9):
    pts = [point.copy() for point in tuple(points or ())]
    if not pts or (pts[0] - pts[-1]).length <= eps:
        return pts
    return pts + [pts[0].copy()]


def closed_spans(points):
    pts = close_loop(points)
    spans = [0.0]
    for i in range(len(pts) - 1):
        spans.append(spans[-1] + (pts[i + 1] - pts[i]).length)
    return pts, spans, spans[-1] if spans else 0.0


def resample_closed(points, count):
    pts, spans, total = closed_spans(points)
    if not pts or count <= 0:
        return []
    if total <= 1.0e-9:
        return [pts[0].copy() for _ in range(count)]
    return [_closed_point(pts, spans, total * i / float(count)) for i in range(count)]


def _closed_point(points, spans, target):
    for i in range(len(spans) - 1):
        if spans[i + 1] >= target:
            return _segment_point(points[i], points[i + 1], spans[i], spans[i + 1], target)
    return points[0].copy()


def _segment_point(a, b, start, end, target):
    span = max(1.0e-9, end - start)
    return a.lerp(b, (target - start) / span)


def loop_pin_targets(route, anchors, count):
    marks, total = _anchor_marks(route, anchors)
    used, out = set(), {}
    for mark, anchor in zip(marks, anchors):
        index = _free_index(int(round((mark / max(total, 1.0e-9)) * count)) % max(1, count), used, count)
        used.add(index)
        out[index] = anchor.copy()
    return out


def _anchor_marks(route, anchors):
    pts, spans, total = closed_spans(route)
    cursor = 0
    marks = []
    for anchor in anchors:
        cursor = _anchor_index(pts, anchor, cursor)
        marks.append(spans[cursor])
    return marks, total


def _anchor_index(points, anchor, start, eps=1.0e-6):
    for index in range(start, len(points)):
        if (points[index] - anchor).length <= eps:
            return index
    return start


def _free_index(index, used, count):
    for step in range(max(1, count)):
        trial = (index + step) % max(1, count)
        if trial not in used:
            return trial
    return 0


def loop_tangents(points):
    count = len(points)
    return [_safe_dir(points[(i + 1) % count] - points[i - 1]) for i in range(count)]


def loop_frames(points):
    tangents = loop_tangents(points)
    normal = _best_fit_normal(points)
    normals, binormals = [_seed_normal(points, tangents, normal)], []
    binormals.append(_safe_dir(tangents[0].cross(normals[0])))
    for i in range(1, len(points)):
        normals.append(_transport_normal(tangents[i - 1], tangents[i], normals[-1]))
        binormals.append(_safe_dir(tangents[i].cross(normals[-1])))
    return tangents, *_twist_closed_frames(tangents, normals, binormals)


def _best_fit_normal(points):
    center = loop_center(points)
    normal = sum(((points[i] - center).cross(points[(i + 1) % len(points)] - center) for i in range(len(points))), Vector())
    return _safe_dir(normal, Vector((0.0, 0.0, 1.0)))


def loop_center(points):
    return sum((point for point in points), Vector()) / float(max(1, len(points)))


def _seed_normal(points, tangents, plane_normal):
    inside = loop_center(points) - points[0]
    seed = inside - tangents[0] * inside.dot(tangents[0])
    if seed.length <= 1.0e-8:
        seed = plane_normal.cross(tangents[0])
    return _safe_dir(seed, _fallback_axis(tangents[0]))


def _fallback_axis(tangent):
    axis = Vector((1.0, 0.0, 0.0)) if abs(tangent.x) < 0.9 else Vector((0.0, 1.0, 0.0))
    return _safe_dir(axis - tangent * axis.dot(tangent), Vector((0.0, 0.0, 1.0)))


def _transport_normal(prev_tangent, tangent, normal):
    return _safe_dir(prev_tangent.rotation_difference(tangent) @ normal, _fallback_axis(tangent))


def _twist_closed_frames(tangents, normals, binormals):
    end = _transport_normal(tangents[-1], tangents[0], normals[-1])
    twist = _signed_angle(end, normals[0], tangents[0])
    return _apply_twist(tangents, normals, binormals, twist)


def _apply_twist(tangents, normals, binormals, twist):
    out_n, out_b = [], []
    count = float(max(1, len(normals)))
    for i, tangent in enumerate(tangents):
        q = Quaternion(tangent, -twist * (i / count))
        out_n.append(_safe_dir(q @ normals[i], normals[i]))
        out_b.append(_safe_dir(q @ binormals[i], binormals[i]))
    return out_n, out_b


def _signed_angle(a, b, axis):
    cross = a.cross(b)
    return atan2(cross.dot(axis), max(-1.0, min(1.0, a.dot(b))))


def _safe_dir(vector, fallback=None):
    base = Vector((1.0, 0.0, 0.0)) if fallback is None else Vector(fallback)
    return Vector(base).normalized() if Vector(vector).length <= 1.0e-8 else Vector(vector).normalized()


def profile_offsets(fiber, t):
    du, dv = _profile_delta(profile_keys(fiber), t % 1.0)
    return float(getattr(fiber, "loop_base_offset_u", 0.0)) + du, float(getattr(fiber, "loop_base_offset_v", 0.0)) + dv


def profile_keys(fiber):
    keys = [(float(item.t), float(item.delta_u), float(item.delta_v)) for item in getattr(fiber, "loop_profile_keys", ())]
    return sorted(keys, key=lambda item: item[0])


def _profile_delta(keys, t):
    if not keys:
        return 0.0, 0.0
    if len(keys) == 1:
        return keys[0][1], keys[0][2]
    return _wrapped_profile(keys, t)


def _wrapped_profile(keys, t):
    extended = list(keys) + [(keys[0][0] + 1.0, keys[0][1], keys[0][2])]
    for i in range(len(keys)):
        if extended[i + 1][0] >= (t if t >= keys[0][0] else t + 1.0):
            return _profile_lerp(extended[i], extended[i + 1], t if t >= keys[0][0] else t + 1.0)
    return keys[-1][1], keys[-1][2]


def _profile_lerp(a, b, t):
    span = max(1.0e-9, b[0] - a[0])
    alpha = (t - a[0]) / span
    du = a[1] + (b[1] - a[1]) * alpha
    dv = a[2] + (b[2] - a[2]) * alpha
    return du, dv
