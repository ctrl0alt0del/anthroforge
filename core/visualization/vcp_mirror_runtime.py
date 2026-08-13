import bpy

from ..scp_runtime.runtime_state import mirror_effective_axis, mirror_source_id, mirror_status
from ..utils import get_af_root, scene_for_id
from ..vcp.fiber_modes import fiber_parent_ids
from ..vcp.surface_target import SurfaceTargetKind, effective_tissue_target
from .mirror_objects import create_mirror_from_source, ensure_obj_type, remove_obj, copy_data
from .muscle_sync_helpers import resolve_muscle_surface
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


def _soft_tissue_map(root):
    return {_as_id(item.id): item for item in root.af_vcp_system.soft_tissues}


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
    _ = fibers_by_id
    parent_ids = [_as_id(pid) for pid in fiber_parent_ids(fiber) if _as_id(pid)]
    for pid in parent_ids:
        rule = _rule_for_scp(pid, scp_by_id)
        if rule is not None:
            return rule
    return None


def _rule_for_muscle(muscle, fibers_by_id, scp_by_id):
    source = _muscle_surface_source(muscle)
    if bool(getattr(source, "use_mirrored_rows", False)):
        return None
    for ref in getattr(source, "fiber_refs", []):
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


def _muscle_surface_source(muscle):
    if str(getattr(muscle, "surface_source_mode", "LEGACY_FIBERS")) != "FIBER_SURFACE":
        return muscle
    root = getattr(muscle, "id_data", None)
    surfaces = getattr(getattr(root, "af_vcp_system", None), "fiber_surfaces", ())
    target = str(getattr(muscle, "fiber_surface_id", "") or "")
    return next((surface for surface in surfaces if str(surface.id) == target), muscle)


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


def _rule_for_soft_tissue(tissue, muscles_by_id, fibers_by_id, scp_by_id):
    target = effective_tissue_target(tissue)
    if target.kind == SurfaceTargetKind.SCP:
        return _rule_for_scp(target.entity_id, scp_by_id)
    if target.kind == SurfaceTargetKind.MUSCLE:
        muscle = muscles_by_id.get(target.entity_id)
        return None if muscle is None else _rule_for_muscle(muscle, fibers_by_id, scp_by_id)
    for fiber in _soft_source_fibers(tissue, fibers_by_id):
        rule = _rule_for_fiber(fiber, fibers_by_id, scp_by_id)
        if rule is not None:
            return rule
    return None


def surface_target_mirror_rule(root, target):
    scps, muscles, fibers = _scp_map(root), _muscle_map(root), _fiber_map(root)
    if target.kind == SurfaceTargetKind.SCP:
        return _rule_for_scp(target.entity_id, scps)
    if target.kind == SurfaceTargetKind.MUSCLE:
        muscle = muscles.get(target.entity_id)
        return None if muscle is None else _rule_for_muscle(muscle, fibers, scps)
    return None


def tissue_source_mirror_rule(root, tissue):
    fibers, scps = _fiber_map(root), _scp_map(root)
    for fiber in _soft_source_fibers(tissue, fibers):
        rule = _rule_for_fiber(fiber, fibers, scps)
        if rule is not None:
            return rule
    return None


def _soft_source_fibers(tissue, fibers_by_id):
    source_type = str(getattr(tissue, "base_source_type", "OBJECT") or "OBJECT")
    source_id = _as_id(getattr(tissue, "base_source_id", ""))
    if source_type == "FIBER":
        return [fibers_by_id[source_id]] if source_id in fibers_by_id else []
    surface = _soft_source_surface(tissue, source_id) if source_type == "FIBER_SURFACE" else None
    return [] if surface is None or bool(surface.use_mirrored_rows) else [fibers_by_id[ref.fiber_id] for ref in surface.fiber_refs if ref.fiber_id in fibers_by_id]


def _soft_source_surface(tissue, source_id):
    root = getattr(tissue, "id_data", None)
    surfaces = getattr(getattr(root, "af_vcp_system", None), "fiber_surfaces", ())
    return next((surface for surface in surfaces if _as_id(surface.id) == source_id), None)


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


def _find_source_soft_obj(vis_col, root_name, tissue_id):
    return next((obj for obj in vis_col.objects if obj.get("af_soft_tissue_proxy")
                 and not obj.get("af_soft_tissue_mirror_proxy") and obj.get("af_root_name") == root_name
                 and _as_id(obj.get("af_soft_tissue_id")) == _as_id(tissue_id)), None)


def _find_mirror_soft_obj(vis_col, root_name, tissue_id):
    return next((obj for obj in vis_col.objects if obj.get("af_soft_tissue_proxy")
                 and obj.get("af_soft_tissue_mirror_proxy") and obj.get("af_root_name") == root_name
                 and _as_id(obj.get("af_source_soft_tissue_id")) == _as_id(tissue_id)), None)


def _sync_fiber_mirrors(root, vis_col, fibers_by_id, scp_by_id, target_fiber_ids=None):
    target_ids = None if target_fiber_ids is None else {_as_id(v) for v in set(target_fiber_ids)}
    affected = set(target_ids) if target_ids is not None else set()
    desired = set()
    for fid, fiber in fibers_by_id.items():
        if target_ids is not None and fid not in target_ids:
            continue
        affected.add(fid)
        if _sync_one_fiber_mirror(root, vis_col, fiber, fid, fibers_by_id, scp_by_id):
            desired.add(fid)
    _remove_stale_fiber_mirrors(vis_col, root.name, desired, affected, target_ids)


def _sync_one_fiber_mirror(root, vis_col, fiber, fid, fibers_by_id, scp_by_id):
    rule = _rule_for_fiber(fiber, fibers_by_id, scp_by_id)
    src = _find_source_fiber_obj(vis_col, root.name, fid)
    mir = _find_mirror_fiber_obj(vis_col, root.name, fid)
    if rule is None or src is None:
        return False
    if src.get("af_fiber_output_state") != "CURRENT":
        return mir is not None
    mir = _ensure_mirror_from_source(vis_col, src, mir)
    if mir is None:
        return False
    _copy_mirror_transform(src, mir, *rule)
    _tag_fiber_mirror(mir, root.name, fid)
    return True


def _tag_fiber_mirror(mirror, root_name, fid):
    mirror["af_fiber_proxy"] = True
    mirror["af_fiber_mirror_proxy"] = True
    mirror["af_root_name"] = root_name
    mirror["af_source_fiber_id"] = fid
    mirror["af_fiber_id"] = fid


def _remove_stale_fiber_mirrors(vis_col, root_name, desired, affected, target_ids):
    for obj in list(vis_col.objects):
        if not _owned_fiber_mirror(obj, root_name):
            continue
        fid = _as_id(obj.get("af_source_fiber_id") or obj.get("af_fiber_id"))
        if fid in desired:
            continue
        if target_ids is not None and fid not in affected:
            continue
        remove_obj(obj)


def _owned_fiber_mirror(obj, root_name):
    return bool(obj.get("af_fiber_proxy") and obj.get("af_fiber_mirror_proxy")
                and obj.get("af_root_name") == root_name)


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
            src = resolve_muscle_surface(root, mid, surf)
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


def _sync_soft_tissue_mirrors(root, vis_col, tissues, muscles, fibers, scps, target_ids=None):
    targets = None if target_ids is None else {_as_id(value) for value in set(target_ids)}
    desired = set()
    for tissue_id, tissue in tissues.items():
        if targets is None or tissue_id in targets:
            _sync_one_soft_mirror(root, vis_col, tissue_id, tissue, muscles, fibers, scps, desired)
    _remove_stale_soft_mirrors(root, vis_col, desired, targets)


def _sync_one_soft_mirror(root, vis_col, tissue_id, tissue, muscles, fibers, scps, desired):
    source = _find_source_soft_obj(vis_col, root.name, tissue_id)
    mirror = _find_mirror_soft_obj(vis_col, root.name, tissue_id)
    rule = _rule_for_soft_tissue(tissue, muscles, fibers, scps)
    if rule is None or source is None:
        if mirror is not None:
            remove_obj(mirror)
        return
    mirror = _ensure_vcp_mirror(vis_col, source, mirror, rule)
    if mirror is not None:
        _tag_soft_mirror(mirror, root.name, tissue_id)
        desired.add(tissue_id)


def _ensure_vcp_mirror(vis_col, source, mirror, rule):
    mirror = _ensure_mirror_from_source(vis_col, source, mirror)
    if mirror is not None:
        _copy_mirror_transform(source, mirror, *rule)
    return mirror


def _tag_soft_mirror(obj, root_name, tissue_id):
    obj["af_soft_tissue_proxy"] = True
    obj["af_soft_tissue_mirror_proxy"] = True
    obj["af_root_name"] = str(root_name)
    obj["af_source_soft_tissue_id"] = str(tissue_id)
    obj["af_soft_tissue_id"] = str(tissue_id)


def _remove_stale_soft_mirrors(root, vis_col, desired, targets):
    for obj in tuple(vis_col.objects):
        if not obj.get("af_soft_tissue_mirror_proxy") or obj.get("af_root_name") != root.name:
            continue
        tissue_id = _as_id(obj.get("af_source_soft_tissue_id"))
        if tissue_id not in desired and (targets is None or tissue_id in targets):
            remove_obj(obj)


def sync_vcp_mirrors(root=None, scene=None, target_fiber_ids=None, target_muscle_ids=None, target_blob_ids=None, target_soft_tissue_ids=None):
    root, scene = _resolve_inputs(root, scene)
    if root is None:
        return
    targets = target_fiber_ids, target_muscle_ids, target_blob_ids, target_soft_tissue_ids
    _sync_all_mirror_types(root, scene, targets)


def _sync_all_mirror_types(root, scene, targets):
    vis_col = _ensure_vcp_collection(scene, name="AF_VCP_VIS")
    scp_by_id = _scp_map(root)
    fibers_by_id = _fiber_map(root)
    muscles_by_id = _muscle_map(root)
    blobs_by_id = _blob_map(root)
    tissues_by_id = _soft_tissue_map(root)
    _sync_fiber_mirrors(root, vis_col, fibers_by_id, scp_by_id, target_fiber_ids=targets[0])
    _sync_muscle_mirrors(root, vis_col, muscles_by_id, fibers_by_id, scp_by_id, target_muscle_ids=targets[1])
    _sync_blob_mirrors(root, vis_col, blobs_by_id, muscles_by_id, fibers_by_id, scp_by_id, target_blob_ids=targets[2])
    _sync_soft_tissue_mirrors(root, vis_col, tissues_by_id, muscles_by_id, fibers_by_id, scp_by_id, targets[3])
