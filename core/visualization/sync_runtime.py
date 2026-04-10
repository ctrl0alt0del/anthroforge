import bpy
import json

from ..deps.dirty_hints import dirty_hints_for
from ..deps.controls import classify_control_object, enqueue_control_intent
from ..deps.transform_intents import enqueue_scp_transform_intent
from ..registry import SCPRegistry
from ..utils import get_af_root


def _stable_text(data):
    try:
        return json.dumps(data, sort_keys=True, separators=(",", ":"))
    except Exception:
        return repr(data)


def _vec3_tuple(v):
    try:
        return (float(v[0]), float(v[1]), float(v[2]))
    except Exception:
        return ()


def _vec4_tuple(v):
    try:
        return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
    except Exception:
        return ()


def _curve_points_sig(scp_prop):
    out = []
    for p in getattr(scp_prop, "curve_points", []):
        out.append(_vec3_tuple(getattr(p, "co", (0.0, 0.0, 0.0))))
    return out


def _parallelepiped_points_sig(scp_prop):
    out = []
    for p in getattr(scp_prop, "parallelepiped_points", []):
        out.append(_vec3_tuple(getattr(p, "co", (0.0, 0.0, 0.0))))
    return out


def _shape_topology_payload(scp, scp_prop):
    shape = getattr(scp, "shape", None)
    st = str(getattr(shape, "type_id", "") or getattr(scp_prop, "shape_type", ""))
    payload = {"shape_type": st}

    if st == "CURVE":
        payload.update(
            {
                "segments": int(getattr(scp_prop, "curve_segments", getattr(shape, "segments", 0))),
                "point_count": len(getattr(scp_prop, "curve_points", getattr(shape, "points", []))),
            }
        )
    elif st == "PARALLELEPIPED":
        payload.update(
            {
                "resolution": int(getattr(scp_prop, "parallelepiped_resolution", getattr(shape, "resolution", 0))),
                "point_count": len(getattr(scp_prop, "parallelepiped_points", getattr(shape, "points", []))),
            }
        )
    elif st == "ELLIPSOID":
        payload.update(
            {
                "resolution": int(getattr(scp_prop, "ellipsoid_resolution", getattr(shape, "resolution", 0))),
                "clip_enabled": bool(getattr(scp_prop, "ellipsoid_clip_enabled", getattr(shape, "clip_enabled", False))),
                "clip1_enabled": bool(getattr(scp_prop, "ellipsoid_clip1_enabled", getattr(shape, "clip1_enabled", False))),
                "clip2_enabled": bool(getattr(scp_prop, "ellipsoid_clip2_enabled", getattr(shape, "clip2_enabled", False))),
            }
        )
    elif st == "MESH_ASSET":
        payload.update(
            {
                "asset_id": str(getattr(scp_prop, "mesh_asset_id", getattr(shape, "asset_id", "")) or ""),
            }
        )
    return payload


def _shape_deformer_payload(scp, scp_prop):
    shape = getattr(scp, "shape", None)
    st = str(getattr(shape, "type_id", "") or getattr(scp_prop, "shape_type", ""))
    payload = {"shape_type": st}

    if scp_prop is not None:
        payload["deformer_state_json"] = str(getattr(scp_prop, "af_deformer_state_json", "") or "")
    if shape is not None:
        try:
            payload["mirror_enabled"] = bool(shape.is_mirror_source())
            payload["mirror_axis"] = str(shape.mirror_axis())
        except Exception:
            payload["mirror_enabled"] = False
            payload["mirror_axis"] = "X"
    elif scp_prop is not None:
        payload["mirror_enabled"] = bool(getattr(scp_prop, "mirror_enabled", False))
        payload["mirror_axis"] = str(getattr(scp_prop, "mirror_axis", "X"))

    if st == "CURVE":
        payload.update(
            {
                "length": float(getattr(scp_prop, "curve_length", getattr(shape, "length", 0.0))),
                "thickness": float(getattr(scp_prop, "curve_thickness", getattr(shape, "thickness", 0.0))),
                "points": _curve_points_sig(scp_prop) if scp_prop is not None else [],
            }
        )
    elif st == "PARALLELEPIPED":
        payload.update(
            {
                "size": _vec3_tuple(getattr(scp_prop, "parallelepiped_size", getattr(shape, "size", ()))),
                "bend_enabled": bool(getattr(scp_prop, "parallelepiped_bend_enabled", getattr(shape, "bend_enabled", False))),
                "bend_axis": str(getattr(scp_prop, "parallelepiped_bend_axis", getattr(shape, "bend_axis", "X"))),
                "bend_angle_deg": float(getattr(scp_prop, "parallelepiped_bend_angle_deg", getattr(shape, "bend_angle_deg", 0.0))),
                "bend_radius": float(getattr(scp_prop, "parallelepiped_bend_radius", getattr(shape, "bend_radius", 1.0))),
                "points": _parallelepiped_points_sig(scp_prop) if scp_prop is not None else [],
            }
        )
    elif st == "ELLIPSOID":
        payload.update(
            {
                "radii": _vec3_tuple(getattr(scp_prop, "ellipsoid_radii", getattr(shape, "radii", ()))),
                "clip1_normal": _vec3_tuple(getattr(scp_prop, "ellipsoid_clip1_normal", getattr(shape, "clip1_normal", ()))),
                "clip1_offset": float(getattr(scp_prop, "ellipsoid_clip1_offset", getattr(shape, "clip1_offset", 0.0))),
                "clip1_keep_side": str(getattr(scp_prop, "ellipsoid_clip1_keep_side", getattr(shape, "clip1_keep_side", "POS"))),
                "clip2_normal": _vec3_tuple(getattr(scp_prop, "ellipsoid_clip2_normal", getattr(shape, "clip2_normal", ()))),
                "clip2_offset": float(getattr(scp_prop, "ellipsoid_clip2_offset", getattr(shape, "clip2_offset", 0.0))),
                "clip2_keep_side": str(getattr(scp_prop, "ellipsoid_clip2_keep_side", getattr(shape, "clip2_keep_side", "POS"))),
            }
        )
    return payload


def _transform_payload(scp, scp_prop):
    if scp_prop is not None:
        return {
            "local_origin": _vec3_tuple(getattr(scp_prop, "local_origin", ())),
            "local_rotation": _vec4_tuple(getattr(scp_prop, "local_rotation", ())),
            "local_scale": _vec3_tuple(getattr(scp_prop, "local_scale", ())),
            "parent_id": str(getattr(scp_prop, "parent_id", "") or ""),
            "attach_param": str(getattr(scp_prop, "attach_param", "") or ""),
            "attach_follow_parent_rotation": bool(getattr(scp_prop, "attach_follow_parent_rotation", True)),
        }
    att = getattr(scp, "attachment", None)
    return {
        "local_origin": _vec3_tuple(getattr(scp, "local_origin", ())),
        "local_scale": _vec3_tuple(getattr(scp, "local_scale", ())),
        "parent_id": str(getattr(att, "parent_id", "") or ""),
    }


def _scp_fingerprints(sync, root, scp):
    scp_prop = sync._get_scp_prop_by_id(root, scp.id)
    fp_transform = _stable_text(_transform_payload(scp, scp_prop))
    fp_topology = _stable_text(_shape_topology_payload(scp, scp_prop))
    fp_deformer = _stable_text(_shape_deformer_payload(scp, scp_prop))
    return fp_transform, fp_topology, fp_deformer


def _resolve_sync_inputs(root, scene):
    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if root is None or scene is None:
        return None, None
    return root, scene


def _ids_to_sync(runtime_registry, target_scp_ids):
    all_live_ids = set(runtime_registry.keys())
    if target_scp_ids is None:
        return all_live_ids, all_live_ids
    return all_live_ids, set(target_scp_ids) & all_live_ids


def _sync_single_proxy(sync, vis_col, root, scene, runtime, scp):
    obj = sync._find_proxy(vis_col, root.name, scp.id)
    created = False
    shape_swapped = False
    if obj is None:
        obj = sync._create_proxy(vis_col, root, scp)
        created = True
    elif not sync._object_matches_shape(obj, scp):
        sync._replace_proxy_data(obj, scp)
        shape_swapped = True
    obj["af_proxy"] = True
    obj["af_root_name"] = root.name
    obj["af_scp_id"] = scp.id
    if obj.parent != root:
        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()

    fp_transform, fp_topology, fp_deformer = _scp_fingerprints(sync, root, scp)
    old_transform = str(obj.get("af_fp_transform", "") or "")
    old_topology = str(obj.get("af_fp_topology", "") or "")
    old_deformer = str(obj.get("af_fp_deformer", "") or "")

    topology_changed = old_topology != fp_topology
    deformer_changed = old_deformer != fp_deformer
    force_geometry = bool(created or shape_swapped)
    shape_type = str(getattr(getattr(scp, "shape", None), "type_id", "") or "")

    # Safety: Parallelepiped deformation (bend angle/radius) drives both proxy
    # geometry and downstream attachment frames. Keep this path eager/correct.
    always_rebuild = (shape_type == "PARALLELEPIPED")
    if always_rebuild or force_geometry or topology_changed or deformer_changed:
        scp.shape.ensure_proxy_object(obj)

    obj.matrix_world = sync._compute_visual_world_matrix(scp, runtime.registry, root, scene)
    _sync_source_mirror_modifier(obj, getattr(scp, "shape", None), sync._get_scp_prop_by_id(root, scp.id))
    obj["af_fp_transform"] = fp_transform
    obj["af_fp_topology"] = fp_topology
    obj["af_fp_deformer"] = fp_deformer
    sync._mark_synced_matrix(obj)


def _sync_source_mirror_modifier(obj, shape, scp_prop):
    if obj is None or not hasattr(obj, "modifiers"):
        return

    mod_name = "AF_MIRROR_SOURCE"
    enabled = False
    axis = "X"
    if shape is not None:
        try:
            enabled = bool(shape.is_mirror_source())
            axis = str(shape.mirror_axis() or "X")
        except Exception:
            enabled = False
            axis = "X"
    elif scp_prop is not None:
        enabled = bool(getattr(scp_prop, "mirror_enabled", False))
        axis = str(getattr(scp_prop, "mirror_axis", "X") or "X")
    existing = obj.modifiers.get(mod_name)

    if not enabled:
        if existing is not None:
            try:
                obj.modifiers.remove(existing)
            except Exception:
                pass
        return

    mod = existing
    if mod is None:
        try:
            mod = obj.modifiers.new(name=mod_name, type="MIRROR")
        except Exception:
            return
    elif str(getattr(mod, "type", "")) != "MIRROR":
        try:
            obj.modifiers.remove(mod)
            mod = obj.modifiers.new(name=mod_name, type="MIRROR")
        except Exception:
            return

    axis = str(axis or "X").upper()
    use_x = axis == "X"
    use_y = axis == "Y"
    use_z = axis == "Z"
    axis_vec = (use_x, use_y, use_z)
    if hasattr(mod, "use_axis"):
        mod.use_axis = axis_vec
    if hasattr(mod, "use_bisect_axis"):
        mod.use_bisect_axis = axis_vec
    if hasattr(mod, "use_bisect_flip_axis"):
        mod.use_bisect_flip_axis = (False, False, False)
    if hasattr(mod, "use_clip"):
        mod.use_clip = True
    if hasattr(mod, "use_mirror_merge"):
        mod.use_mirror_merge = True
    if hasattr(mod, "merge_threshold"):
        mod.merge_threshold = 1e-4


def _cleanup_stale_root_proxies(sync, vis_col, root_name, live_ids):
    for obj in list(sync._iter_root_proxies(vis_col, root_name)):
        if obj.get("af_scp_id") not in live_ids:
            sync._remove_proxy(obj)


def sync_root_to_scene(sync, root=None, scene=None, target_scp_ids=None):
    if sync._syncing:
        return

    root, scene = _resolve_sync_inputs(root, scene)
    if root is None:
        return

    sync._syncing = True
    try:
        vis_col = sync._get_vis_collection(scene)

        runtime = SCPRegistry(root)
        runtime.build()

        all_live_ids, ids_to_sync = _ids_to_sync(runtime.registry, target_scp_ids)

        for scp_id in ids_to_sync:
            scp = runtime.registry.get(scp_id)
            if scp is None:
                continue
            _sync_single_proxy(sync, vis_col, root, scene, runtime, scp)

        for ext in sync._shape_sync_extensions:
            ext.sync_post(sync, root, scene, vis_col)

        _cleanup_stale_root_proxies(sync, vis_col, root.name, all_live_ids)
    finally:
        sync._syncing = False


def _is_relevant_proxy_update(root, vis_col, obj):
    if not isinstance(obj, bpy.types.Object):
        return False
    if obj.get("af_root_name") != root.name:
        return False
    return vis_col.objects.get(obj.name) is not None


def _handle_extension_updates(sync, root, scene, vis_col, obj, depsgraph, changed_ids):
    classified = classify_control_object(obj)
    if not classified:
        return False, False
    ctype = str(classified["control_type"])
    if ctype not in ("SCP_CURVE_POINT", "SCP_PARALLELEPIPED_VERTEX", "SCP_ELLIPSOID_CLIP"):
        return False, False
    payload = dict(classified["payload"])
    payload["binding"] = classified.get("binding")
    if enqueue_control_intent(root, classified["control_type"], payload):
        changed_ids |= set(classified["dirty_hints"].get("SCP", set()) or set())
        return True, True
    return False, False


def _handle_proxy_transform_update(sync, root, scene, obj, depsgraph, changed_ids, non_source_scp_ids):
    if not obj.get("af_proxy") or obj.get("af_mirror_proxy"):
        return False
    scp_id = str(obj.get("af_scp_id") or "")
    if not scp_id:
        return False
    if sync._is_synced_matrix(obj):
        return False
    if not enqueue_scp_transform_intent(root, scp_id, obj.matrix_world.copy()):
        return False
    changed_ids.add(scp_id)
    scp_prop = sync._get_scp_prop_by_id(root, scp_id)
    if scp_prop is not None and bool(getattr(scp_prop, "parent_id", "")):
        non_source_scp_ids.add(scp_id)
    return True


def _collect_changed_scp_ids(sync, root, scene, depsgraph, vis_col):
    changed = False
    changed_scp_ids = set()
    non_source_scp_ids = set()
    for update in depsgraph.updates:
        obj = update.id
        if not _is_relevant_proxy_update(root, vis_col, obj):
            continue
        consumed, did = _handle_extension_updates(sync, root, scene, vis_col, obj, depsgraph, changed_scp_ids)
        changed |= did
        if consumed:
            continue
        changed |= _handle_proxy_transform_update(sync, root, scene, obj, depsgraph, changed_scp_ids, non_source_scp_ids)
    return changed, changed_scp_ids, non_source_scp_ids


def on_depsgraph_update(sync, scene, depsgraph):
    if sync._syncing:
        return

    root = get_af_root(scene)
    if root is None:
        return

    vis_col = bpy.data.collections.get(sync.collection_name)
    if vis_col is None:
        return

    sync._syncing = True
    try:
        changed, changed_scp_ids, non_source_scp_ids = _collect_changed_scp_ids(sync, root, scene, depsgraph, vis_col)
    finally:
        sync._syncing = False

    if changed and changed_scp_ids:
        from .sync_runner import sync_from_dirty_hints

        sync_from_dirty_hints(
            root=root,
            scene=scene,
            dirty_hints=dirty_hints_for("SCP", changed_scp_ids),
            source="depsgraph",
            event_type="TRANSFORM",
            payload={"non_source_ids_by_type": {"SCP": set(non_source_scp_ids)}},
        )
