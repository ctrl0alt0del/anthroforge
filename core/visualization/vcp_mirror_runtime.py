import bpy

from ..scp_runtime.runtime_state import mirror_effective_axis, mirror_source_id, mirror_status
from ..utils import get_af_root, scene_for_id
from ..vcp.fiber_modes import fiber_parent_ids, fiber_root
from .mirror_objects import create_mirror_from_source, ensure_obj_type, remove_obj, copy_data
from .mirror_rules import mirror_world_matrix


def _as_id(value):
    return str(value or "")


def _as_axis(value):
    axis = _as_id(value).upper()
    return axis if axis in {"X", "Y", "Z"} else "X"


def _as_origin(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return (0.0, 0.0, 0.0)
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except Exception:
        return (0.0, 0.0, 0.0)


def _resolve_inputs(root, scene):
    scene = scene or scene_for_id(root)
    root = root or get_af_root(scene)
    if root is None or scene is None or not hasattr(root, "af_vcp_system"):
        return None, None
    return root, scene


def _scp_map(root):
    return {_as_id(s.id): s for s in root.af_scp_system.scps}


def _fiber_map(root):
    return {_as_id(f.id): f for f in root.af_vcp_system.fibers}


def _muscle_map(root):
    return {_as_id(m.id): m for m in root.af_vcp_system.muscles}


def _blob_map(root):
    return {_as_id(b.id): b for b in root.af_vcp_system.blobs}


def _source_id_for_scp(scp_id, scp_by_id):
    sid = _as_id(scp_id)
    if not sid:
        return ""
    scp = scp_by_id.get(sid)
    if scp is None:
        return ""
    status = mirror_status(scp)
    if status == "SOURCE":
        return sid
    if status == "TARGET":
        return mirror_source_id(scp)
    return ""


def _source_rule(source_id, scp_by_id):
    sid = _as_id(source_id)
    if not sid:
        return None
    scp = scp_by_id.get(sid)
    if scp is None:
        return None
    status = mirror_status(scp)
    if status != "SOURCE":
        return None
    axis = _as_axis(mirror_effective_axis(scp) or getattr(scp, "mirror_axis", "X"))
    origin = _as_origin(getattr(scp, "mirror_origin", (0.0, 0.0, 0.0)))
    return axis, origin


def _rule_for_scp(scp_id, scp_by_id):
    source_id = _source_id_for_scp(scp_id, scp_by_id)
    if not source_id:
        return None
    return _source_rule(source_id, scp_by_id)


def _rule_for_fiber(fiber, fibers_by_id, scp_by_id):
    parent_ids = [_as_id(pid) for pid in fiber_parent_ids(fiber) if _as_id(pid)]
    if not parent_ids:
        parent_ids = _fiber_root_parents(fiber, fibers_by_id)
    for pid in parent_ids:
        rule = _rule_for_scp(pid, scp_by_id)
        if rule is not None:
            return rule
    return None


def _fiber_root_parents(fiber, fibers_by_id):
    root = fiber_root(fiber, fibers_by_id)
    return [] if root is None or root == fiber else [_as_id(pid) for pid in fiber_parent_ids(root) if _as_id(pid)]


def _rule_for_muscle(muscle, fibers_by_id, scp_by_id):
    for ref in getattr(muscle, "fiber_refs", []):
        fid = _as_id(getattr(ref, "fiber_id", ""))
        if not fid:
            continue
        fiber = fibers_by_id.get(fid)
        if fiber is None:
            continue
        rule = _rule_for_fiber(fiber, fibers_by_id, scp_by_id)
        if rule is not None:
            return rule
    return None


def _rule_for_blob(blob, muscles_by_id, fibers_by_id, scp_by_id):
    target_type = _as_id(getattr(blob, "attach_target_type", "NONE")).upper()
    target_id = _as_id(getattr(blob, "attach_target_id", ""))

    if target_type == "SCP" and target_id:
        return _rule_for_scp(target_id, scp_by_id)

    if target_type == "MUSCLE" and target_id:
        muscle = muscles_by_id.get(target_id)
        if muscle is None:
            return None
        return _rule_for_muscle(muscle, fibers_by_id, scp_by_id)

    return None


def _ensure_vcp_collection(scene, name="AF_VCP_VIS"):
    col = scene.collection.children.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        scene.collection.children.link(col)
    return col


def _ensure_mirror_from_source(collection, src_obj, existing):
    mir = existing or create_mirror_from_source(collection, src_obj, f"{src_obj.name}_MIR")
    if mir is None:
        return None
    if ensure_obj_type(mir, src_obj) is not None:
        return mir
    remove_obj(mir)
    return create_mirror_from_source(collection, src_obj, f"{src_obj.name}_MIR")


def _copy_mirror_transform(src_obj, mirror_obj, axis, origin):
    copy_data(src_obj, mirror_obj)
    mirror_obj.matrix_world = mirror_world_matrix(src_obj.matrix_world, axis=axis, origin=origin)
    mirror_obj.hide_select = True


def _find_source_fiber_obj(vis_col, root_name, fiber_id):
    fid = _as_id(fiber_id)
    for obj in vis_col.objects:
        if (
            obj.get("af_fiber_proxy")
            and not obj.get("af_fiber_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and _as_id(obj.get("af_fiber_id")) == fid
        ):
            return obj
    return None


def _find_mirror_fiber_obj(vis_col, root_name, source_fiber_id):
    fid = _as_id(source_fiber_id)
    for obj in vis_col.objects:
        if (
            obj.get("af_fiber_proxy")
            and obj.get("af_fiber_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and _as_id(obj.get("af_source_fiber_id")) == fid
        ):
            return obj
    return None


def _find_source_muscle_obj(vis_col, root_name, muscle_id, surface):
    mid = _as_id(muscle_id)
    surf = _as_id(surface)
    for obj in vis_col.objects:
        if (
            obj.get("af_muscle_proxy")
            and not obj.get("af_muscle_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and _as_id(obj.get("af_muscle_id")) == mid
            and _as_id(obj.get("af_muscle_surface")) == surf
        ):
            return obj
    return None


def _find_mirror_muscle_obj(vis_col, root_name, source_muscle_id, surface):
    mid = _as_id(source_muscle_id)
    surf = _as_id(surface)
    for obj in vis_col.objects:
        if (
            obj.get("af_muscle_proxy")
            and obj.get("af_muscle_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and _as_id(obj.get("af_source_muscle_id")) == mid
            and _as_id(obj.get("af_muscle_surface")) == surf
        ):
            return obj
    return None


def _find_source_blob_obj(vis_col, root_name, blob_id):
    bid = _as_id(blob_id)
    for obj in vis_col.objects:
        if (
            obj.get("af_blob_proxy")
            and not obj.get("af_blob_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and _as_id(obj.get("af_blob_id")) == bid
        ):
            return obj
    return None


def _find_mirror_blob_obj(vis_col, root_name, source_blob_id):
    bid = _as_id(source_blob_id)
    for obj in vis_col.objects:
        if (
            obj.get("af_blob_proxy")
            and obj.get("af_blob_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and _as_id(obj.get("af_source_blob_id")) == bid
        ):
            return obj
    return None


def _sync_fiber_mirrors(root, vis_col, fibers_by_id, scp_by_id, target_fiber_ids=None):
    target_ids = None if target_fiber_ids is None else {_as_id(v) for v in set(target_fiber_ids)}
    desired = set()
    affected = set(target_ids) if target_ids is not None else set()

    for fid, fiber in fibers_by_id.items():
        if target_ids is not None and fid not in target_ids:
            continue
        affected.add(fid)
        rule = _rule_for_fiber(fiber, fibers_by_id, scp_by_id)
        src = _find_source_fiber_obj(vis_col, root.name, fid)
        mir = _find_mirror_fiber_obj(vis_col, root.name, fid)
        if rule is None or src is None:
            if target_ids is None and mir is not None:
                remove_obj(mir)
            continue

        axis, origin = rule
        mir = _ensure_mirror_from_source(vis_col, src, mir)
        if mir is None:
            continue
        _copy_mirror_transform(src, mir, axis, origin)
        mir["af_fiber_proxy"] = True
        mir["af_fiber_mirror_proxy"] = True
        mir["af_root_name"] = root.name
        mir["af_source_fiber_id"] = fid
        mir["af_fiber_id"] = fid
        desired.add(fid)

    for obj in list(vis_col.objects):
        if not obj.get("af_fiber_proxy") or not obj.get("af_fiber_mirror_proxy"):
            continue
        if obj.get("af_root_name") != root.name:
            continue
        fid = _as_id(obj.get("af_source_fiber_id") or obj.get("af_fiber_id"))
        if fid in desired:
            continue
        if target_ids is not None and fid not in affected:
            continue
        remove_obj(obj)


def _sync_muscle_mirrors(root, vis_col, muscles_by_id, fibers_by_id, scp_by_id, target_muscle_ids=None):
    target_ids = None if target_muscle_ids is None else {_as_id(v) for v in set(target_muscle_ids)}
    desired = set()
    affected = set()
    if target_ids is not None:
        for mid in target_ids:
            affected.add((mid, "BASE"))
            affected.add((mid, "INFL"))

    for mid, muscle in muscles_by_id.items():
        if target_ids is not None and mid not in target_ids:
            continue
        rule = _rule_for_muscle(muscle, fibers_by_id, scp_by_id)
        for surf in ("BASE", "INFL"):
            key = (mid, surf)
            affected.add(key)
            src = _find_source_muscle_obj(vis_col, root.name, mid, surf)
            mir = _find_mirror_muscle_obj(vis_col, root.name, mid, surf)
            if rule is None or src is None:
                if target_ids is None and mir is not None:
                    remove_obj(mir)
                continue

            axis, origin = rule
            mir = _ensure_mirror_from_source(vis_col, src, mir)
            if mir is None:
                continue
            _copy_mirror_transform(src, mir, axis, origin)
            mir["af_muscle_proxy"] = True
            mir["af_muscle_mirror_proxy"] = True
            mir["af_root_name"] = root.name
            mir["af_source_muscle_id"] = mid
            mir["af_muscle_id"] = mid
            mir["af_muscle_surface"] = surf
            desired.add(key)

    for obj in list(vis_col.objects):
        if not obj.get("af_muscle_proxy") or not obj.get("af_muscle_mirror_proxy"):
            continue
        if obj.get("af_root_name") != root.name:
            continue
        key = (
            _as_id(obj.get("af_source_muscle_id") or obj.get("af_muscle_id")),
            _as_id(obj.get("af_muscle_surface")),
        )
        if key in desired:
            continue
        if target_ids is not None and key not in affected:
            continue
        remove_obj(obj)


def _sync_blob_mirrors(root, vis_col, blobs_by_id, muscles_by_id, fibers_by_id, scp_by_id, target_blob_ids=None):
    target_ids = None if target_blob_ids is None else {_as_id(v) for v in set(target_blob_ids)}
    desired = set()
    affected = set(target_ids) if target_ids is not None else set()

    for bid, blob in blobs_by_id.items():
        if target_ids is not None and bid not in target_ids:
            continue
        affected.add(bid)
        rule = _rule_for_blob(blob, muscles_by_id, fibers_by_id, scp_by_id)
        src = _find_source_blob_obj(vis_col, root.name, bid)
        mir = _find_mirror_blob_obj(vis_col, root.name, bid)
        if rule is None or src is None:
            if target_ids is None and mir is not None:
                remove_obj(mir)
            continue

        axis, origin = rule
        mir = _ensure_mirror_from_source(vis_col, src, mir)
        if mir is None:
            continue
        _copy_mirror_transform(src, mir, axis, origin)
        mir["af_blob_proxy"] = True
        mir["af_blob_mirror_proxy"] = True
        mir["af_root_name"] = root.name
        mir["af_source_blob_id"] = bid
        mir["af_blob_id"] = bid
        desired.add(bid)

    for obj in list(vis_col.objects):
        if not obj.get("af_blob_proxy") or not obj.get("af_blob_mirror_proxy"):
            continue
        if obj.get("af_root_name") != root.name:
            continue
        bid = _as_id(obj.get("af_source_blob_id") or obj.get("af_blob_id"))
        if bid in desired:
            continue
        if target_ids is not None and bid not in affected:
            continue
        remove_obj(obj)


def sync_vcp_mirrors(root=None, scene=None, target_fiber_ids=None, target_muscle_ids=None, target_blob_ids=None):
    root, scene = _resolve_inputs(root, scene)
    if root is None:
        return

    vis_col = _ensure_vcp_collection(scene, name="AF_VCP_VIS")

    scp_by_id = _scp_map(root)
    fibers_by_id = _fiber_map(root)
    muscles_by_id = _muscle_map(root)
    blobs_by_id = _blob_map(root)

    _sync_fiber_mirrors(root, vis_col, fibers_by_id, scp_by_id, target_fiber_ids=target_fiber_ids)
    _sync_muscle_mirrors(
        root,
        vis_col,
        muscles_by_id,
        fibers_by_id,
        scp_by_id,
        target_muscle_ids=target_muscle_ids,
    )
    _sync_blob_mirrors(
        root,
        vis_col,
        blobs_by_id,
        muscles_by_id,
        fibers_by_id,
        scp_by_id,
        target_blob_ids=target_blob_ids,
    )
