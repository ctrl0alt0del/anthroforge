import colorsys
import zlib


def _slot_color(slot):
    hue = (float(slot) * 0.61803398875) % 1.0
    sat, val = 0.72, 0.92
    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
    return (r, g, b, 1.0)


def _color_key(color):
    return tuple(round(float(v), 4) for v in tuple(color or ())[:3])


def _used_color_keys(scene, root_name, exclude_obj=None):
    keys = set()
    for obj in getattr(scene, "objects", ()):
        valid = obj is not exclude_obj and obj.get("af_scp_geometry") and not obj.get("af_scp_mirror")
        valid = valid and obj.get("af_root_name") == root_name and obj.get("af_scp_id")
        if valid:
            keys.add(_color_key(getattr(obj, "color", (0.0, 0.0, 0.0, 1.0))))
    return keys


def _seed_slot(scp_id):
    return zlib.crc32(str(scp_id or "").encode("utf-8")) % 4096


def scp_object_color(scene, root_name, scp_id, exclude_obj=None):
    used = _used_color_keys(scene, root_name, exclude_obj=exclude_obj)
    start = _seed_slot(scp_id)
    for offset in range(4096):
        color = _slot_color(start + offset)
        if _color_key(color) not in used:
            return color
    return _slot_color(start)


def apply_scp_object_color(obj, scene, root_name, scp_id):
    if obj is not None:
        obj.color = scp_object_color(scene, root_name, scp_id, exclude_obj=obj)


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
