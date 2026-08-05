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
    preview_points: tuple = ()
    preview_edges: tuple = ()
    preview_faces: tuple = ()
    preview_distances: tuple = ()


def supported_edit_object(obj):
    return bool(obj and getattr(obj, "type", "") in SUPPORTED_TYPES)


def selected_edit_points(obj):
    return selected_edit_preview(obj)[0]


def selected_edit_preview(obj):
    kind = "" if obj is None else str(getattr(obj, "type", ""))
    if kind == "MESH":
        return _selected_mesh_preview(obj)
    if kind in {"CURVE", "SURFACE"}:
        points, edges = _selected_curve_preview(obj)
        return points, edges, ()
    if kind == "LATTICE":
        points, edges = _selected_lattice_preview(obj)
        return points, edges, ()
    return (), (), ()


def _selected_mesh_preview(obj):
    mesh = bmesh.from_edit_mesh(obj.data)
    vertices = tuple(vert for vert in mesh.verts if vert.select)
    indices = {vert: index for index, vert in enumerate(vertices)}
    edges = tuple((indices[edge.verts[0]], indices[edge.verts[1]]) for edge in mesh.edges if all(vert in indices for vert in edge.verts))
    faces = _selected_face_triangles(mesh, indices)
    return tuple(vert.co.copy() for vert in vertices), edges, faces


def _selected_face_triangles(mesh, indices):
    mapped = [tuple(indices[vert] for vert in face.verts) for face in mesh.faces if all(vert in indices for vert in face.verts)]
    return tuple((face[0], face[index], face[index + 1]) for face in mapped for index in range(1, len(face) - 1))


def _selected_curve_preview(obj):
    points = []
    edges = []
    for spline in obj.data.splines:
        selected, links = _selected_spline_preview(spline)
        edges.extend((len(points) + start, len(points) + end) for start, end in links)
        points.extend(selected)
    return tuple(points), tuple(edges)


def _selected_spline_preview(spline):
    if spline.type == "BEZIER":
        return _selected_bezier_preview(spline)
    rows = [(index, Vector(point.co[:3])) for index, point in enumerate(spline.points) if point.select]
    lookup = {source: index for index, (source, _point) in enumerate(rows)}
    edges = tuple((lookup[start], lookup[end]) for start, end in _grid_pairs(spline) if start in lookup and end in lookup)
    return tuple(point for _source, point in rows), edges


def _selected_bezier_preview(spline):
    rows = [row for index, point in enumerate(spline.bezier_points) for row in _selected_bezier_rows(index, point)]
    lookup = {source: index for index, (source, _point) in enumerate(rows)}
    pairs = [(index, index + 1) for index in range(max(0, len(spline.bezier_points) * 3 - 1))]
    pairs += [(len(spline.bezier_points) * 3 - 1, 0)] if spline.use_cyclic_u and rows else []
    edges = tuple((lookup[start], lookup[end]) for start, end in pairs if start in lookup and end in lookup)
    return tuple(point for _source, point in rows), edges


def _selected_bezier_rows(index, point):
    rows = []
    rows += [(index * 3, point.handle_left.copy())] if point.select_left_handle else []
    rows += [(index * 3 + 1, point.co.copy())] if point.select_control_point else []
    rows += [(index * 3 + 2, point.handle_right.copy())] if point.select_right_handle else []
    return rows


def _grid_pairs(spline):
    count_u = max(1, int(getattr(spline, "point_count_u", len(spline.points))))
    count_v = max(1, int(getattr(spline, "point_count_v", 1)))
    pairs = [(v * count_u + u, v * count_u + u + 1) for v in range(count_v) for u in range(count_u - 1)]
    pairs += [(v * count_u + u, (v + 1) * count_u + u) for v in range(count_v - 1) for u in range(count_u)]
    pairs += [(v * count_u + count_u - 1, v * count_u) for v in range(count_v)] if spline.use_cyclic_u else []
    pairs += [((count_v - 1) * count_u + u, u) for u in range(count_u)] if getattr(spline, "use_cyclic_v", False) else []
    return pairs


def _selected_lattice_preview(obj):
    rows = [(index, point.co_deform.copy()) for index, point in enumerate(obj.data.points) if point.select]
    lookup = {source: index for index, (source, _point) in enumerate(rows)}
    edges = tuple((lookup[start], lookup[end]) for start, end in _lattice_pairs(obj.data) if start in lookup and end in lookup)
    return tuple(point for _source, point in rows), edges


def _lattice_pairs(data):
    size_u, size_v, size_w = int(data.points_u), int(data.points_v), int(data.points_w)
    index = lambda u, v, w: w * size_u * size_v + v * size_u + u
    pairs = [(index(u, v, w), index(u + 1, v, w)) for w in range(size_w) for v in range(size_v) for u in range(size_u - 1)]
    pairs += [(index(u, v, w), index(u, v + 1, w)) for w in range(size_w) for v in range(size_v - 1) for u in range(size_u)]
    pairs += [(index(u, v, w), index(u, v, w + 1)) for w in range(size_w - 1) for v in range(size_v) for u in range(size_u)]
    return pairs


def build_quick_hook_draft(obj, scp_id, reuse=None):
    points, edges, faces = selected_edit_preview(obj)
    if not points:
        return None
    center = _draft_center(points, reuse)
    radius, strength, falloff = _draft_settings(points, center, reuse)
    scale = max(_local_span(obj), radius * 2.0, 1.0e-4) / 400.0
    distances = tuple((Vector(point) - center).length for point in points)
    return QuickHookDraft(obj, str(scp_id), center, radius, strength, falloff, scale, len(points), reuse, points, edges, faces, distances)


def quick_hook_influence(distance, radius, falloff, strength=1.0):
    strength = min(1.0, max(0.0, float(strength)))
    if strength == 0.0:
        return 0.0
    if str(falloff) == "NONE" or float(radius) <= 0.0:
        return strength
    if float(distance) >= float(radius):
        return 0.0
    remaining = 1.0 - max(0.0, float(distance)) / float(radius)
    return strength * _falloff_profile(remaining, str(falloff))


def _falloff_profile(value, falloff):
    if falloff == "CONSTANT":
        return 1.0
    if falloff == "SHARP":
        return value * value
    if falloff == "ROOT":
        return value ** 0.5
    if falloff == "SPHERE":
        return max(0.0, 2.0 * value - value * value) ** 0.5
    if falloff == "INVERSE_SQUARE":
        return value * (2.0 - value)
    if falloff == "SMOOTH":
        return value * value * (3.0 - 2.0 * value)
    return value


def quick_hook_preview_weights(draft):
    distances = tuple(getattr(draft, "preview_distances", ()))
    if len(distances) != len(draft.preview_points):
        distances = tuple((Vector(point) - Vector(draft.center)).length for point in draft.preview_points)
    return tuple(quick_hook_influence(distance, draft.radius, draft.falloff, draft.strength) for distance in distances)


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
