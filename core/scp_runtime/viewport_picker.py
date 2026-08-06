from bpy_extras import view3d_utils

from ..scp_proxy.consts import ATTR_SLOT, FLAG as PROXY_FLAG, SIDE_KEY, SIDE_MIRRORED
from ..scp_proxy.session import proxy_sources
from .common import scp_prop_map
from .runtime_state import mirror_effective_axis, mirror_source_id
from ..visualization.mirror_rules import mirror_matrix


def raycast_scp(context, event, candidates=()):
    ray = _ray_from_event(context, event)
    return None if ray is None else _closest_hit(ray, candidates)


def pick_candidates(context, root):
    if root is None:
        return ()
    return tuple(_candidate_row(root, obj) for obj in context.scene.objects if _is_candidate(context, root, obj))


def has_pick_candidates(context, root):
    return bool(pick_candidates(context, root))


def candidate_for_object(root, obj):
    return None if not _candidate_kind(root, obj) else _candidate_row(root, obj)


def raycast_world(origin, direction, candidates=()):
    return _closest_hit((origin, direction), candidates)


def _ray_from_event(context, event):
    region, rv3d = _view_window(context)
    if region is None or rv3d is None:
        return None
    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    return origin, direction


def _view_window(context):
    area = getattr(context, "area", None)
    if area is None or area.type != "VIEW_3D":
        return None, None
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    space = next((s for s in area.spaces if s.type == "VIEW_3D"), None)
    return region, getattr(space, "region_3d", None)


def _is_candidate(context, root, obj):
    kind = _candidate_kind(root, obj)
    return bool(kind and _visible_for_pick(context, obj))


def _candidate_kind(root, obj):
    if getattr(obj, "type", "") != "MESH":
        return ""
    if _is_proxy(root, obj):
        return "PROXY"
    if _is_mirror(root, obj):
        return "MIRROR"
    return "SCP" if _scp_id(root, obj) else ""


def _is_proxy(root, obj):
    return bool(obj.get(PROXY_FLAG) and obj.get("af_root_name") == root.name)


def _is_mirror(root, obj):
    valid = obj.get("af_scp_mirror") and obj.get("af_root_name") == root.name
    return bool(valid and obj.get("af_source_scp_id"))


def _scp_id(root, obj):
    valid = obj.get("af_root_name") == root.name and obj.get("af_scp_bound")
    valid = valid and obj.get("af_scp_geometry") and not obj.get("af_scp_mirror")
    return str(obj.get("af_scp_id", "") or "") if valid else ""


def _visible_for_pick(context, obj):
    try:
        return bool(obj.visible_get(view_layer=context.view_layer))
    except Exception:
        return not bool(obj.hide_get())


def _candidate_row(root, obj):
    kind = _candidate_kind(root, obj)
    payload = _candidate_payload(root, obj, kind)
    return kind, obj, obj.matrix_world.copy(), obj.matrix_world.inverted().copy(), payload


def _candidate_payload(root, obj, kind):
    if kind == "PROXY":
        return _proxy_slot_payload(root, obj)
    if kind == "MIRROR":
        sid = str(obj.get("af_source_scp_id", "") or "")
        return sid, _unmirror_matrix(root, sid)
    return _scp_id(root, obj)


def _closest_hit(ray, candidates):
    hits = tuple(hit for hit in (_object_hit(row, *ray) for row in tuple(candidates or ())) if hit)
    return None if not hits else _pick_payload(min(hits, key=lambda item: item[2]))


def _object_hit(row, origin, direction):
    kind, obj, matrix_world, world_inv, payload = row
    local_ray = _local_ray(world_inv, origin, direction)
    if local_ray is None:
        return None
    hit, loc, _normal, face = obj.ray_cast(*local_ray)
    return None if not hit else _world_hit(kind, obj, payload, face, matrix_world @ loc, origin)


def _world_hit(kind, obj, payload, face, world, origin):
    scp_id, attach_world = _row_pick(kind, obj, payload, face, world)
    return None if not scp_id else (scp_id, attach_world, (world - origin).length, world)


def _local_ray(world_inv, origin, direction):
    local_origin = world_inv @ origin
    local_direction = world_inv.to_3x3() @ direction
    if local_direction.length <= 1.0e-9:
        return None
    return local_origin, local_direction.normalized()


def _row_pick(kind, obj, payload, face, world):
    if kind == "SCP":
        return payload, world
    if kind == "MIRROR":
        return payload[0], _mapped_world(payload[1], world)
    source = _proxy_source_for_face(obj, payload, face)
    return ("", world) if source is None else (source[0], _mapped_world(source[1], world))


def _pick_payload(hit):
    return hit[0], hit[1].copy(), hit[3].copy()


def _proxy_slot_payload(root, obj):
    rows = (_proxy_slot_row(root, obj, row) for row in proxy_sources(obj))
    return {slot: data for slot, data in rows if slot >= 0 and data[0]}


def _proxy_slot_row(root, obj, row):
    try:
        slot = int(row.get("slot", -1))
    except Exception:
        slot = -1
    sid = str(row.get("scp_id", "") or "")
    matrix = _unmirror_matrix(root, sid) if obj.get(SIDE_KEY) == SIDE_MIRRORED else None
    return slot, (sid, matrix)


def _unmirror_matrix(root, scp_id):
    scps = scp_prop_map(root)
    target = scps.get(str(scp_id or ""))
    source = None if target is None else scps.get(mirror_source_id(target))
    origin = (0.0, 0.0, 0.0) if source is None else tuple(source.mirror_origin)
    return None if source is None else mirror_matrix(mirror_effective_axis(target), origin)


def _proxy_source_for_face(obj, payload, face_index):
    slot = _proxy_face_slot(obj, face_index)
    return None if slot is None else payload.get(int(slot))


def _proxy_face_slot(obj, face_index):
    poly = _face_poly(obj, face_index)
    attr = None if poly is None else obj.data.attributes.get(ATTR_SLOT)
    if attr is None:
        return None
    slots = [int(attr.data[int(v)].value) for v in poly.vertices]
    return None if not slots else max(set(slots), key=slots.count)


def _face_poly(obj, face_index):
    index = int(face_index)
    polys = getattr(getattr(obj, "data", None), "polygons", ())
    return polys[index] if 0 <= index < len(polys) else None


def _mapped_world(matrix, world):
    return world if matrix is None else matrix @ world
