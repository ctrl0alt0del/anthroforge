import colorsys
import zlib

from .common import set_prop_raw


def _slot_color(slot):
    hue = (float(slot) * 0.61803398875) % 1.0
    sat, val = 0.72, 0.92
    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
    return (r, g, b, 1.0)


def _color_key(color):
    return tuple(round(float(v), 4) for v in tuple(color or ())[:3])


def _scp_color(scp):
    color = tuple(getattr(scp, "color", (0.0, 0.0, 0.0, 1.0)) or ())
    return tuple(float(v) for v in color[:4]) if len(color) >= 4 else (0.0, 0.0, 0.0, 1.0)


def _used_color_keys(root, exclude_scp=None):
    keys = set()
    for scp in getattr(root.af_scp_system, "scps", ()):
        if scp != exclude_scp and getattr(scp, "color_initialized", False):
            keys.add(_color_key(_scp_color(scp)))
    return keys


def _seed_slot(scp_id):
    return zlib.crc32(str(scp_id or "").encode("utf-8")) % 4096


def next_scp_color(root, scp_id, exclude_scp=None):
    used = _used_color_keys(root, exclude_scp=exclude_scp)
    start = _seed_slot(scp_id)
    for offset in range(4096):
        color = _slot_color(start + offset)
        if _color_key(color) not in used:
            return color
    return _slot_color(start)


def ensure_scp_color(root, scp):
    if getattr(scp, "color_initialized", False):
        return _scp_color(scp)
    color = next_scp_color(root, getattr(scp, "id", ""), exclude_scp=scp)
    set_prop_raw(scp, "color", color)
    set_prop_raw(scp, "color_initialized", True)
    return color


def apply_object_color(obj, color):
    if obj is not None:
        obj.color = tuple(color or (0.0, 0.0, 0.0, 1.0))


def enable_object_color_view(context):
    screen = None if context is None else getattr(context, "screen", None)
    for area in getattr(screen, "areas", ()):
        _set_area_object_color(area)


def _set_area_object_color(area):
    if getattr(area, "type", "") != "VIEW_3D":
        return
    for space in getattr(area, "spaces", ()):
        _set_space_object_color(space)


def _set_space_object_color(space):
    shading = None if getattr(space, "type", "") != "VIEW_3D" else getattr(space, "shading", None)
    if shading is not None and getattr(shading, "type", "") == "SOLID":
        shading.color_type = "OBJECT"
