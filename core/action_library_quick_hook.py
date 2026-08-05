from dataclasses import dataclass

import bmesh
import bpy
from mathutils import Vector


SUPPORTED_TYPES = {"MESH", "CURVE", "SURFACE", "LATTICE"}
FALLOFF_TYPES = ("SMOOTH", "LINEAR", "SHARP", "ROOT", "SPHERE", "CONSTANT", "NONE", "INVERSE_SQUARE")
_LAST_HOOKS = {}


@dataclass(frozen=True)
class QuickHookReuse:
    control: object
    modifier: object
    scp_id: str


@dataclass
class QuickHookDraft:
    geometry: object
    scp_id: str
    center: Vector
    radius: float
    strength: float
    falloff: str
    pixel_scale: float
    selected_count: int
    reuse: object = None


def supported_edit_object(obj):
    return bool(obj and getattr(obj, "type", "") in SUPPORTED_TYPES)


def selected_edit_points(obj):
    kind = "" if obj is None else str(getattr(obj, "type", ""))
    if kind == "MESH":
        return _selected_mesh_points(obj)
    if kind in {"CURVE", "SURFACE"}:
        return _selected_curve_points(obj)
    return _selected_lattice_points(obj) if kind == "LATTICE" else ()


def _selected_mesh_points(obj):
    mesh = bmesh.from_edit_mesh(obj.data)
    return tuple(vert.co.copy() for vert in mesh.verts if vert.select)


def _selected_curve_points(obj):
    points = []
    for spline in obj.data.splines:
        points.extend(_selected_spline_points(spline))
    return tuple(points)


def _selected_spline_points(spline):
    if spline.type == "BEZIER":
        return [co for point in spline.bezier_points for co in _selected_bezier_coords(point)]
    return [Vector(point.co[:3]) for point in spline.points if point.select]


def _selected_bezier_coords(point):
    points = []
    points += [point.handle_left.copy()] if point.select_left_handle else []
    points += [point.co.copy()] if point.select_control_point else []
    points += [point.handle_right.copy()] if point.select_right_handle else []
    return points


def _selected_lattice_points(obj):
    return tuple(point.co_deform.copy() for point in obj.data.points if point.select)


def build_quick_hook_draft(obj, scp_id, reuse=None):
    points = selected_edit_points(obj)
    if not points:
        return None
    center = _draft_center(points, reuse)
    radius, strength, falloff = _draft_settings(points, center, reuse)
    scale = max(_local_span(obj), radius * 2.0, 1.0e-4) / 400.0
    return QuickHookDraft(obj, str(scp_id), center, radius, strength, falloff, scale, len(points), reuse)


def _draft_center(points, reuse):
    if reuse is not None:
        return Vector(reuse.modifier.center)
    return sum((Vector(point) for point in points), Vector()) / len(points)


def _draft_settings(points, center, reuse):
    if reuse is not None:
        mod = reuse.modifier
        return float(mod.falloff_radius), float(mod.strength), str(mod.falloff_type)
    radius = max(((Vector(point) - center).length for point in points), default=0.0)
    return radius * 1.25, 1.0, "SMOOTH"


def _local_span(obj):
    corners = [Vector(point) for point in tuple(getattr(obj, "bound_box", ()) or ())]
    if not corners:
        return 1.0
    low = Vector(tuple(min(point[i] for point in corners) for i in range(3)))
    high = Vector(tuple(max(point[i] for point in corners) for i in range(3)))
    return (high - low).length


def deselect_edit_points(obj):
    kind = str(getattr(obj, "type", "") or "")
    if kind == "MESH":
        _deselect_mesh(obj)
    elif kind in {"CURVE", "SURFACE"}:
        _deselect_curves(obj)
    elif kind == "LATTICE":
        _deselect_lattice(obj)


def _deselect_mesh(obj):
    mesh = bmesh.from_edit_mesh(obj.data)
    for vert in mesh.verts:
        vert.select = False
    bmesh.update_edit_mesh(obj.data)


def _deselect_curves(obj):
    for spline in obj.data.splines:
        _deselect_spline(spline)


def _deselect_spline(spline):
    for point in spline.bezier_points:
        point.select_left_handle = point.select_control_point = point.select_right_handle = False
    for point in spline.points:
        point.select = False


def _deselect_lattice(obj):
    for point in obj.data.points:
        point.select = False


def reusable_quick_hook(scene, obj, scp_id):
    row = _LAST_HOOKS.get(_session_key(scene, obj))
    if row is None or str(row.scp_id) != str(scp_id):
        return None
    if not _reuse_is_live(scene, obj, row):
        _LAST_HOOKS.pop(_session_key(scene, obj), None)
        return None
    return row


def _reuse_is_live(scene, obj, row):
    try:
        control, modifier = row.control, row.modifier
        live = scene.objects.get(control.name) == control and obj.modifiers.get(modifier.name) == modifier
        root_name = str(obj.get("af_root_name", ""))
        owned = control.get("af_scp_bound") and control.get("af_root_name") == root_name
        owned = owned and str(control.get("af_scp_id", "")) == str(row.scp_id)
        geometry = supported_edit_object(obj) and obj.get("af_scp_bound") and root_name
        geometry = geometry and str(obj.get("af_scp_id", "")) == str(row.scp_id)
        linked = modifier.type == "HOOK" and modifier.object == control
        return bool(live and owned and geometry and linked)
    except (ReferenceError, RuntimeError):
        return False


def remember_quick_hook(scene, obj, scp_id, control, modifier):
    row = QuickHookReuse(control, modifier, str(scp_id))
    _LAST_HOOKS[_session_key(scene, obj)] = row
    return row


def clear_quick_hook_sessions():
    _LAST_HOOKS.clear()


def _session_key(scene, obj):
    return _pointer(scene), _pointer(obj)


def _pointer(value):
    try:
        return int(value.as_pointer())
    except Exception:
        return id(value)


def next_hook_name(scp_name):
    base = f"{_name_token(scp_name)[:54]}_Hook"
    index = 1
    while bpy.data.objects.get(f"{base}_{index:02d}") is not None:
        index += 1
    return f"{base}_{index:02d}"


def _name_token(value):
    token = "_".join(str(value or "SCP").strip().split())
    return token or "SCP"


def apply_quick_hook_settings(modifier, draft):
    modifier.falloff_radius = max(0.0, float(draft.radius))
    modifier.strength = min(1.0, max(0.0, float(draft.strength)))
    modifier.falloff_type = str(draft.falloff)


def apply_reuse_target(modifier, reuse):
    modifier.object = reuse.control
    modifier.center = reuse.modifier.center
    modifier.matrix_inverse = reuse.modifier.matrix_inverse.copy()
