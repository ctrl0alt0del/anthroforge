from .constants import QUAD_EXPANSION


def internal_target(target_quads, reserved_quads=0):
    available = max(512, int(target_quads) - int(reserved_quads))
    return max(128, round(available / QUAD_EXPANSION))


def needs_correction(actual, target, tolerance=0.15):
    return abs(int(actual) - int(target)) > (float(tolerance) * max(1, int(target)))


def corrected_target(previous, actual, wanted):
    ratio = float(wanted) / max(1, int(actual))
    return max(128, round(int(previous) * ratio))


def proxy_face_count(source_faces, target_quads):
    desired = min(300000, max(64000, int(target_quads) * 2))
    return min(int(source_faces), desired)
