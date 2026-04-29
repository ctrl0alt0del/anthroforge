import re

from ..id_utils import next_prefixed_id
from .bound_objects import clear_scp_tags, iter_bound_objects
from .common import as_id, find_scp_by_id, scp_prop_map, set_prop_raw
from .lookup import clear_native_parent_keep_world
from .object_roles import add_bound_object_to_scp, create_scp, set_scp_geometry_object, set_scp_transform_object
from .tree import children_map

_FULL_OBJECT_RE = re.compile(r"^bpy\.data\.objects\[[\"'](.+?)[\"']\](.+)$")
_SCP_SKIP = {"id", "name", "parent_id", "color", "color_initialized", "bound_objects", "transform_object_ref", "geometry_object_ref", "mirror_status", "mirror_source_id", "mirror_effective_axis"}
_FIBER_SKIP = {"id", "name", "mid_touches", "a_parent_id", "b_parent_id", "muscle_id", "not_converged", "last_recompute_ms", "last_recompute_status", "last_eps_disp", "last_eps_pen"}
_MUSCLE_SKIP = {"id", "name", "fiber_refs", "active_fiber_ref_index"}
_BLOB_SKIP = {"id", "name", "attach_target_id", "attach_target_object_name", "last_solve_converged", "last_solve_max_disp", "last_solve_iterations"}


def _copyable_prop(prop, key, skip):
    return key != "rna_type" and key not in skip and not prop.is_readonly and prop.type not in {"COLLECTION", "POINTER"}


def _copy_scalars(src, dst, skip=()):
    for prop in src.bl_rna.properties:
        key = prop.identifier
        if _copyable_prop(prop, key, set(skip or ())):
            setattr(dst, key, getattr(src, key))


def _copied_name(src_name, src_id, dst_id):
    name = str(src_name or "")
    return str(dst_id or "") if name == str(src_id or "") else (name or str(dst_id or ""))


def _copy_name(src, dst, dst_id):
    dst.name = _copied_name(getattr(src, "name", ""), getattr(src, "id", ""), dst_id)


def _new_maps():
    return {"scps": {}, "objects": {}, "names": {}, "fibers": {}, "muscles": {}}


def _subtree_ids(root, scp_id):
    scp_by_id, kids = scp_prop_map(root), children_map(scp_prop_map(root))
    stack, seen, out = [as_id(scp_id)], set(), []
    while stack:
        sid = stack.pop()
        if sid in scp_by_id and sid not in seen:
            seen.add(sid), out.append(sid), stack.extend(reversed(kids.get(sid, [])))
    return out


def _source_scps(root, scp_ids):
    return [find_scp_by_id(root, sid) for sid in scp_ids if find_scp_by_id(root, sid) is not None]


def _clone_object(scene, obj):
    clone = obj.copy()
    clone.data = None if getattr(obj, "data", None) is None else obj.data.copy()
    _link_clone(scene, obj, clone)
    clear_scp_tags(clone), clear_native_parent_keep_world(clone)
    return clone


def _link_clone(scene, obj, clone):
    cols = tuple(getattr(obj, "users_collection", ()) or ())
    cols = cols if cols else (scene.collection,)
    for col in cols:
        col.objects.link(clone)


def _copy_scp_props(src, dst):
    _copy_scalars(src, dst, skip=_SCP_SKIP)


def _copy_scp_objects(root, scene, src, dst, maps):
    local = {}
    for _entry, obj in iter_bound_objects(src):
        local[obj.name] = _clone_object(scene, obj)
        maps["objects"][obj.name] = local[obj.name]
        maps["names"][obj.name] = local[obj.name].name
        add_bound_object_to_scp(root, dst, local[obj.name])
    _set_copied_roles(root, src, dst, local)


def _set_copied_roles(root, src, dst, local):
    xform = getattr(getattr(src, "transform_object_ref", None), "name", "")
    geo = getattr(getattr(src, "geometry_object_ref", None), "name", "")
    set_scp_transform_object(root, dst, local.get(xform))
    set_scp_geometry_object(root, dst, local.get(geo))


def _copy_scps(root, scene, scps, maps):
    pairs = []
    for src in scps:
        dst = create_scp(root, getattr(src, "name", ""))
        maps["scps"][as_id(src.id)] = as_id(dst.id)
        _copy_scp_props(src, dst), _copy_scp_objects(root, scene, src, dst, maps)
        pairs.append((src, dst))
    return pairs


def _apply_scp_links(pairs, scp_map):
    for src, dst in pairs:
        set_prop_raw(dst, "parent_id", scp_map.get(as_id(getattr(src, "parent_id", "")), as_id(getattr(src, "parent_id", ""))))


def _fiber_parent_ids(fiber):
    mids = [as_id(tp.parent_id) for tp in fiber.mid_touches if as_id(tp.parent_id)]
    return [sid for sid in [as_id(fiber.a_parent_id), as_id(fiber.b_parent_id), *mids] if sid]


def _copyable_fiber(fiber, scp_ids):
    parent_ids = set(_fiber_parent_ids(fiber))
    return bool(parent_ids) and parent_ids <= set(scp_ids or set())


def _new_item(collection, prefix):
    item = collection.add()
    item.id = next_prefixed_id(collection, prefix)
    return item


def _copy_touches(src, dst, scp_map):
    for touch in src.mid_touches:
        new_touch = dst.mid_touches.add()
        _copy_scalars(touch, new_touch, skip={"parent_id"})
        new_touch.parent_id = scp_map.get(as_id(touch.parent_id), "")


def _copy_fiber_item(root, src, maps):
    dst = _new_item(root.af_vcp_system.fibers, "FIBER")
    maps["fibers"][as_id(src.id)] = as_id(dst.id)
    _copy_scalars(src, dst, skip=_FIBER_SKIP), _copy_name(src, dst, dst.id)
    dst.a_parent_id = maps["scps"].get(as_id(src.a_parent_id), "")
    dst.b_parent_id = maps["scps"].get(as_id(src.b_parent_id), "")
    _copy_touches(src, dst, maps["scps"])


def _copy_fibers(root, scp_ids, maps):
    for fiber in tuple(root.af_vcp_system.fibers):
        _copy_fiber_item(root, fiber, maps) if _copyable_fiber(fiber, scp_ids) else None


def _copyable_muscle(muscle, fiber_map):
    ids = [as_id(ref.fiber_id) for ref in muscle.fiber_refs if as_id(ref.fiber_id)]
    return bool(ids) and all(fid in fiber_map for fid in ids)


def _copy_fiber_refs(src, dst, fiber_map):
    ids = [fiber_map[as_id(ref.fiber_id)] for ref in src.fiber_refs if as_id(ref.fiber_id) in fiber_map]
    for fid in ids:
        ref = dst.fiber_refs.add()
        ref.fiber_id = fid
    dst.active_fiber_ref_index = min(int(getattr(src, "active_fiber_ref_index", -1)), len(dst.fiber_refs) - 1)


def _fiber_by_id(root, fiber_id):
    return next((fiber for fiber in root.af_vcp_system.fibers if as_id(fiber.id) == as_id(fiber_id)), None)


def _copy_muscle_item(root, src, maps):
    dst = _new_item(root.af_vcp_system.muscles, "MUSCLE")
    maps["muscles"][as_id(src.id)] = as_id(dst.id)
    _copy_scalars(src, dst, skip=_MUSCLE_SKIP), _copy_name(src, dst, dst.id)
    _copy_fiber_refs(src, dst, maps["fibers"]), _assign_muscle(dst.id, dst.fiber_refs, root)


def _assign_muscle(muscle_id, refs, root):
    for ref in refs:
        fiber = _fiber_by_id(root, ref.fiber_id)
        setattr(fiber, "muscle_id", muscle_id) if fiber is not None else None


def _copy_muscles(root, maps):
    for muscle in tuple(root.af_vcp_system.muscles):
        _copy_muscle_item(root, muscle, maps) if _copyable_muscle(muscle, maps["fibers"]) else None


def _remapped_blob_target(blob, maps):
    target_type = str(getattr(blob, "attach_target_type", "NONE") or "NONE")
    if target_type == "SCP" and as_id(blob.attach_target_id) in maps["scps"]:
        return "SCP", maps["scps"][as_id(blob.attach_target_id)], ""
    if target_type == "MUSCLE" and as_id(blob.attach_target_id) in maps["muscles"]:
        return "MUSCLE", maps["muscles"][as_id(blob.attach_target_id)], ""
    if target_type == "OBJECT" and str(blob.attach_target_object_name or "") in maps["names"]:
        return "OBJECT", "", maps["names"][str(blob.attach_target_object_name or "")]
    return None


def _copy_blob_item(root, src, maps):
    remap = _remapped_blob_target(src, maps)
    if remap is None:
        return
    dst = _new_item(root.af_vcp_system.blobs, "BLOB")
    _copy_scalars(src, dst, skip=_BLOB_SKIP), _copy_name(src, dst, dst.id)
    dst.attach_target_type, dst.attach_target_id, dst.attach_target_object_name = remap


def _copy_blobs(root, maps):
    for blob in tuple(root.af_vcp_system.blobs):
        _copy_blob_item(root, blob, maps)


def _rewritten_path(raw, name_map):
    match = _FULL_OBJECT_RE.match(str(raw or "").strip())
    if match is None or match.group(1) not in name_map:
        return ""
    return f"bpy.data.objects[{repr(name_map[match.group(1)])}]{match.group(2)}"


def _add_shortcut(root, shortcut, data_path):
    item = root.af_shortcut_system.shortcuts.add()
    item.id = next_prefixed_id(root.af_shortcut_system.shortcuts, "SHORTCUT")
    item.name, item.data_path = str(shortcut.name or item.id), data_path


def _copy_shortcuts(root, maps):
    for shortcut in tuple(root.af_shortcut_system.shortcuts):
        path = _rewritten_path(getattr(shortcut, "data_path", ""), maps["names"])
        _add_shortcut(root, shortcut, path) if path else None


def copy_scp_subtree(root, scene, scp_id):
    maps = _new_maps()
    source_ids = _subtree_ids(root, scp_id)
    if not source_ids:
        return ""
    pairs = _copy_scps(root, scene, _source_scps(root, source_ids), maps)
    _apply_scp_links(pairs, maps["scps"])
    _copy_fibers(root, set(source_ids), maps), _copy_muscles(root, maps)
    _copy_blobs(root, maps), _copy_shortcuts(root, maps)
    return maps["scps"].get(as_id(scp_id), "")
