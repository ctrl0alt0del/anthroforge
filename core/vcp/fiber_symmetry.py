from mathutils import Vector


SYMMETRY_NONE = "NONE"
MIRROR_SEAM_LOOP = "MIRROR_SEAM_LOOP"


def fiber_symmetry_mode(fiber):
    return str(getattr(fiber, "symmetry_mode", SYMMETRY_NONE) or SYMMETRY_NONE)


def is_mirror_seam_loop(fiber):
    return fiber_symmetry_mode(fiber) == MIRROR_SEAM_LOOP


def mirror_axis(fiber):
    axis = str(getattr(fiber, "symmetry_axis", "X") or "X").upper()
    return axis if axis in {"X", "Y", "Z"} else "X"


def mirror_origin(fiber):
    value = getattr(fiber, "symmetry_origin", (0.0, 0.0, 0.0))
    return tuple(float(value[i]) for i in range(3)) if hasattr(value, "__len__") else (0.0, 0.0, 0.0)


def axis_index(axis):
    axis = str(axis or "X").upper()
    return 1 if axis == "Y" else 2 if axis == "Z" else 0


def axis_origin(origin, axis):
    return float(origin[axis_index(axis)]) if hasattr(origin, "__len__") else 0.0


def signed_distance(point, axis, origin):
    return float(point[axis_index(axis)]) - axis_origin(origin, axis)


def mirror_point(point, axis, origin):
    values = [float(point[i]) for i in range(3)]
    index = axis_index(axis)
    values[index] = (2.0 * axis_origin(origin, axis)) - values[index]
    return Vector(values)


def expand_mirror_seam_points(points, axis, origin):
    authored = [Vector(point).copy() for point in tuple(points or ())]
    mirror_source = authored[1:-1] if _has_seam_endpoints(authored, axis, origin) else authored
    mirrored = [mirror_point(point, axis, origin) for point in reversed(mirror_source)]
    return authored + mirrored


def _has_seam_endpoints(points, axis, origin, eps=1.0e-5):
    items = tuple(points or ())
    if len(items) < 2:
        return False
    first = abs(signed_distance(items[0], axis, origin)) <= eps
    return first and abs(signed_distance(items[-1], axis, origin)) <= eps


def expand_fiber_loop_points(fiber, points):
    if not is_mirror_seam_loop(fiber):
        return [Vector(point).copy() for point in tuple(points or ())]
    return expand_mirror_seam_points(points, mirror_axis(fiber), mirror_origin(fiber))
