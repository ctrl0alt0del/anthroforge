from dataclasses import dataclass, field

from ..deps.dirty_hints import DirtyHints
from ..id_utils import next_prefixed_id
from ..vcp.prop_update_guard import suppress_vcp_prop_updates
from ..vcp.attachment_backend import attachment_runtime, surface_binding_topology
from ..vcp.surface_binding_codec import remap_binding_target
from ..visualization.delete_reconcile import cleanup_scp_dependents
from ..visualization.sync_runner import schedule_sync_from_dirty_hints
from .model import ImportResult
from .rna import apply_scalar_dict


@dataclass
class VcpImportState:
    root: object
    scene: object
    snapshot: object
    compatible_scps: set[str]
    warnings: list[str] = field(default_factory=list)
    fibers: dict[str, str] = field(default_factory=dict)
    fiber_surfaces: dict[str, str] = field(default_factory=dict)
    muscles: dict[str, str] = field(default_factory=dict)
    blobs: dict[str, str] = field(default_factory=dict)
    soft_tissues: dict[str, str] = field(default_factory=dict)
    stage_root: object = None
    kept_objects: list[object] = field(default_factory=list)


def _scp_map(root):
    return {str(scp.id or ""): scp for scp in root.af_scp_system.scps if str(scp.id or "")}


def _snapshot_scp_map(snapshot):
    return {str(scp.source_id or ""): scp for scp in snapshot.scps if str(scp.source_id or "")}


def _mesh_topology(obj):
    mesh = getattr(obj, "data", None)
    if obj is None or getattr(obj, "type", "") != "MESH" or mesh is None:
        return None
    return {
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "faces": len(mesh.polygons),
        "loops": len(mesh.loops),
    }


def _same_topology(source_snap, target_scp):
    source = getattr(source_snap, "topology", None)
    target = _mesh_topology(getattr(target_scp, "geometry_object_ref", None))
    return source is not None and source == target


def _compatible_scp_ids(snapshot, root):
    source, target = _snapshot_scp_map(snapshot), _scp_map(root)
    return {sid for sid, snap in source.items() if sid in target and _same_topology(snap, target[sid])}


def _new_vcp_item(collection, prefix):
    item = collection.add()
    item.id = next_prefixed_id(collection, prefix)
    return item


def _ids_text(values):
    return ", ".join(sorted({str(v) for v in values if str(v or "")})) or "unknown"


def _warn_skip(state, kind, source_id, missing):
    state.warnings.append(f"Skipped {kind} {source_id}: incompatible SCP or dependency {_ids_text(missing)}.")


def _fiber_scp_ids(snap):
    ids = {snap.a_parent_id, snap.b_parent_id}
    ids |= {touch.parent_id for touch in snap.touches}
    ids |= {anchor.parent_id for anchor in getattr(snap, "loop_anchors", ())}
    return {str(sid or "") for sid in ids if str(sid or "")}


def _incompatible_scps(state, scp_ids):
    return set(scp_ids or set()) - set(state.compatible_scps or set())


def _copy_touches(dst, snap):
    for touch in snap.touches:
        item = dst.mid_touches.add()
        apply_scalar_dict(item, touch.props)
        item.parent_id = str(touch.parent_id or "")


def _copy_loop_anchors(dst, snap):
    for anchor in getattr(snap, "loop_anchors", ()):
        item = dst.loop_anchors.add()
        apply_scalar_dict(item, anchor.props)
        item.parent_id = str(anchor.parent_id or "")


def _create_one_fiber(state, snap):
    missing = _incompatible_scps(state, _fiber_scp_ids(snap))
    if missing:
        return _warn_skip(state, "fiber", snap.source_id, missing)
    dst = _new_vcp_item(state.root.af_vcp_system.fibers, "FIBER")
    state.fibers[str(snap.source_id or "")] = str(dst.id or "")
    dst.name, dst.a_parent_id = str(snap.name or dst.id), str(snap.a_parent_id or "")
    dst.b_parent_id, dst.muscle_id = str(snap.b_parent_id or ""), ""
    apply_scalar_dict(dst, snap.props)
    _copy_touches(dst, snap)
    _copy_loop_anchors(dst, snap)


def _create_fibers(state):
    for snap in state.snapshot.fibers:
        _create_one_fiber(state, snap)


def _create_one_fiber_surface(state, snap):
    missing = [source_id for source_id in snap.fiber_ids if str(source_id) not in state.fibers]
    if missing:
        return _warn_skip(state, "fiber surface", snap.source_id, missing)
    dst = _new_vcp_item(state.root.af_vcp_system.fiber_surfaces, "SURFACE")
    state.fiber_surfaces[str(snap.source_id or "")] = str(dst.id or "")
    dst.name = str(snap.name or dst.id)
    apply_scalar_dict(dst, snap.props)
    for source_id in snap.fiber_ids:
        dst.fiber_refs.add().fiber_id = state.fibers[str(source_id)]
    dst.active_fiber_ref_index = 0 if dst.fiber_refs else -1


def _create_fiber_surfaces(state):
    for snap in getattr(state.snapshot, "fiber_surfaces", ()):
        _create_one_fiber_surface(state, snap)


def _missing_fiber_refs(state, snap):
    return [fid for fid in snap.fiber_ids if str(fid or "") not in state.fibers]


def _copy_refs(dst, snap, state):
    for source_id in snap.fiber_ids:
        ref = dst.fiber_refs.add()
        ref.fiber_id = state.fibers[str(source_id or "")]


def _assign_fiber_muscles(state, muscle_id, snap):
    for source_id in snap.fiber_ids:
        fiber = _fiber_by_id(state.root, state.fibers[str(source_id or "")])
        if fiber is not None:
            fiber.muscle_id = muscle_id


def _fiber_by_id(root, fiber_id):
    return next((item for item in root.af_vcp_system.fibers if str(item.id) == str(fiber_id)), None)


def _create_one_muscle(state, snap):
    surface_source = str(getattr(snap, "fiber_surface_id", "") or "")
    missing = _missing_fiber_refs(state, snap) if not surface_source else _missing_surface_ref(state, surface_source)
    if missing:
        return _warn_skip(state, "muscle", snap.source_id, missing)
    dst = _new_vcp_item(state.root.af_vcp_system.muscles, "MUSCLE")
    state.muscles[str(snap.source_id or "")] = str(dst.id or "")
    dst.name = str(snap.name or dst.id)
    apply_scalar_dict(dst, snap.props)
    dst.fiber_surface_id = state.fiber_surfaces.get(surface_source, "")
    if not surface_source:
        _copy_refs(dst, snap, state)
        _assign_fiber_muscles(state, dst.id, snap)


def _missing_surface_ref(state, source_id):
    return [] if source_id in state.fiber_surfaces else [source_id]


def _create_muscles(state):
    for snap in state.snapshot.muscles:
        _create_one_muscle(state, snap)


def _blob_missing(state, snap):
    target = str(snap.attach_target_type or "NONE")
    if target == "SCP":
        return _incompatible_scps(state, {snap.attach_target_id})
    if target == "MUSCLE":
        return set() if str(snap.attach_target_id or "") in state.muscles else {snap.attach_target_id}
    return set() if target == "NONE" else {target}


def _blob_target_id(state, snap):
    if str(snap.attach_target_type) == "SCP":
        return str(snap.attach_target_id or "")
    if str(snap.attach_target_type) == "MUSCLE":
        return state.muscles[str(snap.attach_target_id or "")]
    return ""


def _create_one_blob(state, snap):
    missing = _blob_missing(state, snap)
    if missing:
        return _warn_skip(state, "blob", snap.source_id, missing)
    dst = _new_vcp_item(state.root.af_vcp_system.blobs, "BLOB")
    state.blobs[str(snap.source_id or "")] = str(dst.id or "")
    dst.name = str(snap.name or dst.id)
    apply_scalar_dict(dst, snap.props)
    dst.attach_target_type = str(snap.attach_target_type or "NONE")
    dst.attach_target_id = _blob_target_id(state, snap)
    dst.attach_target_object_name = ""


def _create_blobs(state):
    for snap in state.snapshot.blobs:
        _create_one_blob(state, snap)


def _stage_tissue_base(state, source_id):
    if state.stage_root is None:
        return None
    items = getattr(state.stage_root.af_vcp_system, "soft_tissues", ())
    source = next((item for item in items if str(item.id or "") == str(source_id)), None)
    return None if source is None else getattr(source, "base_object_ref", None)


def _create_one_soft_tissue(state, snap):
    values = _soft_tissue_import_values(state, snap)
    error = _soft_tissue_import_missing(*values)
    if error:
        return _warn_skip(state, "soft tissue", snap.source_id, error)
    dst = _new_vcp_item(state.root.af_vcp_system.soft_tissues, "TISSUE")
    state.soft_tissues[str(snap.source_id or "")] = str(dst.id or "")
    _populate_soft_tissue(dst, snap, values)
    base = values[4]
    if base is not None:
        _keep_base(state, base, dst)


def _soft_tissue_import_values(state, snap):
    missing = _incompatible_scps(state, {snap.host_scp_id}) if snap.host_scp_id else set()
    target_type, target_id = _mapped_soft_target(state, snap)
    source_type = str(getattr(snap, "base_source_type", "OBJECT") or "OBJECT")
    base = _stage_tissue_base(state, snap.source_id) if source_type == "OBJECT" else None
    source_id = _mapped_soft_source(state, source_type, getattr(snap, "base_source_id", ""))
    return missing, target_type, target_id, source_type, base, source_id


def _soft_tissue_import_missing(missing, target_type, target_id, source_type, base, source_id):
    if missing:
        return missing
    if target_type != "NONE" and not target_id:
        return {"attachment target"}
    invalid_source = (source_type == "OBJECT" and base is None) or (source_type != "OBJECT" and not source_id)
    return {"base source"} if invalid_source else set()


def _populate_soft_tissue(dst, snap, values):
    _missing, target_type, target_id, source_type, base, source_id = values
    dst.name = str(snap.name or dst.id)
    apply_scalar_dict(dst, snap.props)
    dst.base_source_type, dst.base_source_id = source_type, source_id
    dst.host_scp_id, dst.base_object_ref = str(snap.host_scp_id or ""), base
    dst.attachment_target_type, dst.attachment_target_id = target_type, target_id
    dst.attachment_target_surface = str(getattr(snap, "attachment_target_surface", "AUTO"))
    _copy_soft_attachments(dst, snap)
    _remap_soft_payloads(dst, snap, target_type, target_id)


def _mapped_soft_source(state, source_type, source_id):
    if source_type == "FIBER":
        return state.fibers.get(str(source_id or ""), "")
    if source_type == "FIBER_SURFACE":
        return state.fiber_surfaces.get(str(source_id or ""), "")
    return ""


def _mapped_soft_target(state, snap):
    kind = str(getattr(snap, "attachment_target_type", "NONE") or "NONE")
    source_id = str(getattr(snap, "attachment_target_id", "") or "")
    if kind == "SCP":
        valid = source_id in state.compatible_scps and _stored_target_topology_matches(state, snap, source_id)
        return kind, source_id if valid else ""
    if kind == "MUSCLE":
        return kind, state.muscles.get(source_id, "")
    return "NONE", ""


def _stored_target_topology_matches(state, snap, target_id):
    expected = str(dict(snap.props or {}).get("attachment_topology_signature", "") or "")
    scp = _scp_map(state.root).get(str(target_id))
    obj = None if scp is None else getattr(scp, "geometry_object_ref", None)
    current = surface_binding_topology(obj, attachment_runtime(state.scene), state.scene)
    return bool(current and (not expected or current == expected))


def _remap_soft_payloads(dst, snap, target_type, target_id):
    source_id = str(getattr(snap, "attachment_target_id", "") or "")
    if target_type == "NONE" or not source_id or not target_id:
        return
    dst.control_bindings_json = remap_binding_target(dst.control_bindings_json, target_type, source_id, target_id)
    dst.base_bindings_json = remap_binding_target(dst.base_bindings_json, target_type, source_id, target_id)
    for row in dst.attachments:
        row.bindings_json = remap_binding_target(row.bindings_json, target_type, source_id, target_id)


def _copy_soft_attachments(dst, snap):
    for source in snap.attachments:
        row = dst.attachments.add()
        apply_scalar_dict(row, source.props)


def _keep_base(state, base, tissue):
    if not base.users_collection:
        state.scene.collection.objects.link(base)
    base["af_soft_tissue_base"] = True
    base["af_soft_tissue_id"] = str(tissue.id)
    base["af_root_name"] = str(state.root.name)
    if base not in state.kept_objects:
        state.kept_objects.append(base)


def _create_soft_tissues(state):
    for snap in state.snapshot.soft_tissues:
        _create_one_soft_tissue(state, snap)


def _result(state):
    return ImportResult(scp_count=0, fiber_count=len(state.fibers), muscle_count=len(state.muscles),
                        blob_count=len(state.blobs), soft_tissue_count=len(state.soft_tissues),
                        shortcut_count=0, fiber_surface_count=len(state.fiber_surfaces),
                        warnings=state.warnings, kept_objects=state.kept_objects)


def _dirty_for_imported(state):
    dirty = DirtyHints(full=False)
    dirty["FIBER"] = set(state.fibers.values())
    dirty["FIBER_SURFACE"] = set(state.fiber_surfaces.values())
    dirty["MUSCLE"] = set(state.muscles.values())
    dirty["BLOB"] = set(state.blobs.values())
    dirty["SOFT_TISSUE"] = set(state.soft_tissues.values())
    return dirty


def _has_dirty(dirty):
    return any(bool(values) for values in dict(dirty or {}).values())


def _schedule_imported_sync(state):
    from ..visualization.warning_runtime import structural_change, notify_action
    structural_change(state.root)
    notify_action(state.root, state.scene, full=True, event_type="IMPORT")
    dirty = _dirty_for_imported(state)
    if _has_dirty(dirty):
        payload = {"soft_tissue_force": True} if state.soft_tissues else None
        schedule_sync_from_dirty_hints(root=state.root, scene=state.scene, dirty_hints=dirty,
                                       source="operator", event_type="IMPORT", payload=payload)


def apply_vcp_snapshot(snapshot, root, context, stage_root=None):
    from .branching import restore_graph
    state = VcpImportState(root, context.scene, snapshot, _compatible_scp_ids(snapshot, root), stage_root=stage_root)
    with suppress_vcp_prop_updates():
        _create_fibers(state)
        _create_fiber_surfaces(state)
        _create_muscles(state)
        restore_graph(state)
        _create_blobs(state)
        _create_soft_tissues(state)
    cleanup_scp_dependents(root)
    _schedule_imported_sync(state)
    return _result(state)
