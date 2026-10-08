from dataclasses import dataclass, field

from ..deps.dirty_hints import DirtyHints, empty_dirty_hints
from ..id_utils import next_prefixed_id
from ..scp_proxy.signature import mesh_topology_signature
from ..scp_runtime.bound_objects import find_bound_entry_by_object, sync_all_scp_roles
from ..scp_runtime.common import set_prop_raw
from ..scp_runtime.prop_update_guard import set_parent_id_raw, suppress_scp_prop_updates
from ..scp_runtime.object_roles import add_bound_object_to_scp, create_scp, set_geometry_object, set_transform_object
from ..shortcuts import upsert_override
from ..shortcuts.path_codec import make_bound_entity_id, make_shortcut_path, parse_shortcut_path, split_bound_entity_id
from ..vcp.prop_update_guard import suppress_vcp_prop_updates
from ..vcp.attachment_backend import attachment_runtime, surface_binding_topology
from ..vcp.surface_binding_codec import remap_binding_target
from ..vcp.fiber_node_attachment_codec import (node_attachment_target_ids_from_raw,
                                                remap_node_attachment_targets)
from ..visualization.delete_reconcile import cleanup_scp_dependents
from ..visualization.sync_runner import schedule_sync_from_dirty_hints, sync_from_dirty_hints
from .model import ImportResult
from .rna import apply_scalar_dict
from .stage import stage_bound_map


@dataclass
class MergeState:
    root: object
    scene: object
    collection: object
    snapshot: object
    stage_root: object
    stage_map: dict
    warnings: list[str] = field(default_factory=list)
    scps: dict = field(default_factory=dict)
    fibers: dict = field(default_factory=dict)
    fiber_surfaces: dict = field(default_factory=dict)
    muscles: dict = field(default_factory=dict)
    blobs: dict = field(default_factory=dict)
    soft_tissues: dict = field(default_factory=dict)
    imported_scps: set[str] = field(default_factory=set)
    shortcut_count: int = 0
    kept_objects: list[object] = field(default_factory=list)


def _target_collection(context):
    layer = getattr(getattr(context, "view_layer", None), "active_layer_collection", None)
    return context.scene.collection if layer is None else layer.collection


def _stage_object(state, scp_id, bound_id):
    return state.stage_map.get((str(scp_id or ""), str(bound_id or "")))


def _link_object(state, obj):
    if obj is not None and not obj.users_collection:
        state.collection.objects.link(obj)


def _remap(mapping, source_id):
    return str(mapping.get(str(source_id or ""), "") or "")


def _shortcut_owner_id(state, owner_type, owner_id):
    maps = {"SCP": state.scps, "FIBER": state.fibers, "FIBER_SURFACE": state.fiber_surfaces,
            "MUSCLE": state.muscles, "BLOB": state.blobs,
            "SOFT_TISSUE": state.soft_tissues}
    return _remap(maps.get(str(owner_type or "NONE"), {}), owner_id)


def _remap_bound_path(state, kind, entity_id, prop_spec):
    scp_id, bound_id = split_bound_entity_id(entity_id)
    new_id = _remap(state.scps, scp_id)
    entity = make_bound_entity_id(new_id, bound_id)
    return make_shortcut_path(kind, prop_spec, entity_id=entity) if new_id else ""


def _remap_shortcut_path(state, raw):
    kind, entity_id, prop_spec = parse_shortcut_path(raw)
    if kind == "scp_bound_rna":
        return _remap_bound_path(state, kind, entity_id, prop_spec)
    if kind in {"scp_prop", "scp_object"}:
        return make_shortcut_path(kind, prop_spec, entity_id=_remap(state.scps, entity_id))
    return str(raw or "")


def _new_vcp_item(collection, prefix):
    item = collection.add()
    item.id = next_prefixed_id(collection, prefix)
    return item


def _set_bound_entry(entry, bound):
    set_prop_raw(entry, "id", str(bound.bound_id or ""))
    set_prop_raw(entry, "label", str(bound.label or ""))


def _role_object(local, bound_id):
    return local.get(str(bound_id or ""), None)


def _warn(state, message):
    state.warnings.append(str(message or "Import warning."))


def _add_bound(state, scp, source_id, bound, local):
    obj = _stage_object(state, source_id, bound.bound_id)
    if obj is None:
        return _warn(state, f"Missing staged object for {source_id}:{bound.bound_id}.")
    _link_object(state, obj)
    add_bound_object_to_scp(state.root, scp, obj)
    _set_bound_entry(find_bound_entry_by_object(scp, obj), bound)
    local[str(bound.bound_id or "")] = obj
    state.kept_objects.append(obj)


def _apply_roles(state, scp, snap, local):
    set_transform_object(state.root, scp, _role_object(local, snap.transform_bound_id))
    set_geometry_object(state.root, scp, _role_object(local, snap.geometry_bound_id))


def _source_id(snap):
    return str(getattr(snap, "source_id", "") or "")


def _set_preserved_scp_id(scp, snap, preserve_id):
    if preserve_id and _source_id(snap):
        set_prop_raw(scp, "id", _source_id(snap))


def _create_one_scp(state, snap, preserve_id=False):
    with suppress_scp_prop_updates():
        scp = create_scp(state.root, snap.name)
        _set_preserved_scp_id(scp, snap, preserve_id)
        state.scps[_source_id(snap)] = str(scp.id or "")
        apply_scalar_dict(scp, snap.props)
        local = {}
        for bound in snap.bound_objects:
            _add_bound(state, scp, snap.source_id, bound, local)
        _apply_roles(state, scp, snap, local)
        state.imported_scps.add(_source_id(snap))


def _create_scps(state):
    for snap in state.snapshot.scps:
        _create_one_scp(state, snap)


def _set_scp_parents(state):
    for snap in state.snapshot.scps:
        scp = next(x for x in state.root.af_scp_system.scps if str(x.id) == _remap(state.scps, snap.source_id))
        set_parent_id_raw(scp, _remap(state.scps, snap.parent_id))


def _scp_by_id(root, scp_id):
    return next((scp for scp in root.af_scp_system.scps if str(scp.id) == str(scp_id)), None)


def _target_scp_ids(root):
    return {str(scp.id or "") for scp in root.af_scp_system.scps if str(scp.id or "")}


def _seed_existing_scps(state):
    existing = _target_scp_ids(state.root)
    for snap in state.snapshot.scps:
        if _source_id(snap) in existing:
            state.scps[_source_id(snap)] = _source_id(snap)


def _create_missing_scps(state):
    for snap in state.snapshot.scps:
        if _source_id(snap) and _source_id(snap) not in state.scps:
            _create_one_scp(state, snap, preserve_id=True)


def _set_imported_scp_parents(state):
    for snap in state.snapshot.scps:
        if _source_id(snap) not in state.imported_scps:
            continue
        scp = _scp_by_id(state.root, _remap(state.scps, snap.source_id))
        if scp is not None:
            set_parent_id_raw(scp, _remap(state.scps, snap.parent_id))


def _copy_touches(dst, snap, state):
    for touch in snap.touches:
        item = dst.mid_touches.add()
        apply_scalar_dict(item, touch.props)
        item.parent_id = _remap(state.scps, touch.parent_id)


def _copy_loop_anchors(dst, snap, state):
    for anchor in getattr(snap, "loop_anchors", ()):
        item = dst.loop_anchors.add()
        apply_scalar_dict(item, anchor.props)
        item.parent_id = _remap(state.scps, anchor.parent_id)


def _create_one_fiber(state, snap):
    dst = _new_vcp_item(state.root.af_vcp_system.fibers, "FIBER")
    state.fibers[str(snap.source_id or "")] = str(dst.id or "")
    dst.name, dst.a_parent_id = str(snap.name or dst.id), _remap(state.scps, snap.a_parent_id)
    dst.b_parent_id, dst.muscle_id = _remap(state.scps, snap.b_parent_id), ""
    apply_scalar_dict(dst, snap.props)
    _remap_fiber_node_attachments(dst, state.scps)
    _copy_touches(dst, snap, state)
    _copy_loop_anchors(dst, snap, state)


def _create_fibers(state):
    for snap in state.snapshot.fibers:
        _create_one_fiber(state, snap)


def _remap_fiber_node_attachments(fiber, scp_map):
    raw = str(getattr(fiber, "node_attachments_json", "") or "")
    if raw: fiber.node_attachments_json = remap_node_attachment_targets(raw, scp_map)


def _fiber_scp_ids(snap):
    ids = {snap.a_parent_id, snap.b_parent_id}
    ids |= {touch.parent_id for touch in snap.touches}
    ids |= {anchor.parent_id for anchor in getattr(snap, "loop_anchors", ())}
    ids |= set(node_attachment_target_ids_from_raw(snap.props.get("node_attachments_json", "")))
    return {str(sid or "") for sid in ids if str(sid or "")}


def _all_scps_mapped(state, ids):
    return all(_remap(state.scps, sid) for sid in set(ids or ()))


def _diff_fiber_snap(state, snap):
    ids = _fiber_scp_ids(snap)
    return bool(ids & state.imported_scps) and _all_scps_mapped(state, ids)


def _create_diff_fibers(state):
    for snap in state.snapshot.fibers:
        if _diff_fiber_snap(state, snap):
            _create_one_fiber(state, snap)


def _create_one_fiber_surface(state, snap):
    dst = _new_vcp_item(state.root.af_vcp_system.fiber_surfaces, "SURFACE")
    state.fiber_surfaces[str(snap.source_id or "")] = str(dst.id or "")
    dst.name = str(snap.name or dst.id)
    apply_scalar_dict(dst, snap.props)
    for source_id in snap.fiber_ids:
        dst.fiber_refs.add().fiber_id = _remap(state.fibers, source_id)
    dst.active_fiber_ref_index = 0 if dst.fiber_refs else -1


def _surface_refs_mapped(state, snap):
    return bool(snap.fiber_ids) and all(_remap(state.fibers, source_id) for source_id in snap.fiber_ids)


def _create_fiber_surfaces(state):
    for snap in getattr(state.snapshot, "fiber_surfaces", ()):
        _create_one_fiber_surface(state, snap)


def _create_diff_fiber_surfaces(state):
    for snap in getattr(state.snapshot, "fiber_surfaces", ()):
        if _surface_refs_mapped(state, snap):
            _create_one_fiber_surface(state, snap)


def _fiber_by_id(root, fiber_id):
    return next((item for item in root.af_vcp_system.fibers if str(item.id) == str(fiber_id)), None)


def _copy_refs(dst, snap, state):
    for source_id in snap.fiber_ids:
        ref = dst.fiber_refs.add()
        ref.fiber_id = _remap(state.fibers, source_id)


def _assign_fiber_muscles(state, muscle_id, snap):
    for source_id in snap.fiber_ids:
        fiber = _fiber_by_id(state.root, _remap(state.fibers, source_id))
        if fiber is not None:
            fiber.muscle_id = muscle_id


def _create_one_muscle(state, snap):
    surface_id = str(getattr(snap, "fiber_surface_id", "") or "")
    dst = _new_vcp_item(state.root.af_vcp_system.muscles, "MUSCLE")
    state.muscles[str(snap.source_id or "")] = str(dst.id or "")
    dst.name = str(snap.name or dst.id)
    apply_scalar_dict(dst, snap.props)
    dst.fiber_surface_id = _remap(state.fiber_surfaces, surface_id)
    if not surface_id:
        _copy_refs(dst, snap, state)
        _assign_fiber_muscles(state, dst.id, snap)


def _create_muscles(state):
    for snap in state.snapshot.muscles:
        _create_one_muscle(state, snap)


def _muscle_refs_mapped(state, snap):
    surface_id = str(getattr(snap, "fiber_surface_id", "") or "")
    ids = [str(fid or "") for fid in snap.fiber_ids if str(fid or "")]
    if surface_id:
        return bool(_remap(state.fiber_surfaces, surface_id))
    return bool(ids) and all(_remap(state.fibers, sid) for sid in ids)


def _create_diff_muscles(state):
    for snap in state.snapshot.muscles:
        if _muscle_refs_mapped(state, snap):
            _create_one_muscle(state, snap)


def _blob_target_name(state, snap):
    if str(snap.attach_target_type) != "OBJECT" or not snap.attach_object_entity:
        return str(snap.attach_target_object_name or "")
    scp_id, bound_id = split_bound_entity_id(snap.attach_object_entity)
    obj = _stage_object(state, scp_id, bound_id)
    return "" if obj is None else str(obj.name or "")


def _blob_target_id(state, snap):
    if str(snap.attach_target_type) == "SCP":
        return _remap(state.scps, snap.attach_target_id)
    if str(snap.attach_target_type) == "MUSCLE":
        return _remap(state.muscles, snap.attach_target_id)
    return ""


def _create_one_blob(state, snap):
    dst = _new_vcp_item(state.root.af_vcp_system.blobs, "BLOB")
    state.blobs[str(snap.source_id or "")] = str(dst.id or "")
    dst.name = str(snap.name or dst.id)
    apply_scalar_dict(dst, snap.props)
    dst.attach_target_type = str(snap.attach_target_type or "NONE")
    dst.attach_target_id = _blob_target_id(state, snap)
    dst.attach_target_object_name = _blob_target_name(state, snap)


def _create_blobs(state):
    for snap in state.snapshot.blobs:
        _create_one_blob(state, snap)


def _stage_tissue_base(state, snap):
    source_id = str(snap.source_id or "")
    items = getattr(state.stage_root.af_vcp_system, "soft_tissues", ())
    source = next((item for item in items if str(item.id or "") == source_id), None)
    return None if source is None else getattr(source, "base_object_ref", None)


def _create_one_soft_tissue(state, snap):
    host = _remap(state.scps, snap.host_scp_id) if snap.host_scp_id else ""
    target_type, target_id = _mapped_soft_target(state, snap)
    source_type = str(getattr(snap, "base_source_type", "OBJECT") or "OBJECT")
    base = _stage_tissue_base(state, snap) if source_type == "OBJECT" else None
    source_id = _mapped_soft_source(state, source_type, getattr(snap, "base_source_id", ""))
    error = _soft_tissue_import_error(state, snap, host, target_type, target_id, source_type, base, source_id)
    if error:
        return _warn(state, error)
    _add_soft_tissue_record(state, snap, host, target_type, target_id, source_type, source_id, base)


def _add_soft_tissue_record(state, snap, host, target_type, target_id, source_type, source_id, base):
    from .soft_tissue_cache import preserve_legacy_cache
    dst = _new_vcp_item(state.root.af_vcp_system.soft_tissues, "TISSUE")
    state.soft_tissues[str(snap.source_id or "")] = str(dst.id or "")
    dst.name = str(snap.name or dst.id)
    apply_scalar_dict(dst, snap.props)
    dst.base_source_type, dst.base_source_id = source_type, source_id
    dst.host_scp_id, dst.base_object_ref = host, base
    dst.attachment_target_type, dst.attachment_target_id = target_type, target_id
    dst.attachment_target_surface = str(getattr(snap, "attachment_target_surface", "AUTO"))
    _copy_soft_attachments(dst, snap)
    _remap_soft_payloads(dst, snap, target_type, target_id)
    preserve_legacy_cache(state, snap, dst)
    if base is not None:
        _keep_tissue_base(state, base, dst)


def _soft_tissue_import_error(state, snap, host, target_type, target_id, source_type, base, source_id):
    if snap.host_scp_id and not host:
        return f"Skipped soft tissue {snap.source_id}: host SCP was not imported."
    if target_type != "NONE" and not target_id:
        return f"Skipped soft tissue {snap.source_id}: attachment target was not imported."
    if target_type == "SCP" and not _soft_target_compatible(state, target_id, snap):
        return f"Skipped soft tissue {snap.source_id}: attachment target topology is incompatible."
    if source_type == "OBJECT" and base is None:
        return f"Skipped soft tissue {snap.source_id}: base object is missing."
    if source_type != "OBJECT" and not source_id:
        return f"Skipped soft tissue {snap.source_id}: base source is missing."
    if host and not _soft_host_compatible(state, host, snap):
        return f"Skipped soft tissue {snap.source_id}: host topology is incompatible."
    return ""


def _soft_target_compatible(state, target_id, snap):
    expected = str(dict(snap.props or {}).get("attachment_topology_signature", "") or "")
    scp = _scp_by_id(state.root, target_id)
    obj = None if scp is None else getattr(scp, "geometry_object_ref", None)
    current = surface_binding_topology(obj, attachment_runtime(state.scene), state.scene)
    return bool(current and (not expected or current == expected))


def _mapped_soft_target(state, snap):
    kind = str(getattr(snap, "attachment_target_type", "NONE") or "NONE")
    source_id = str(getattr(snap, "attachment_target_id", "") or "")
    if kind == "SCP":
        return kind, _remap(state.scps, source_id)
    if kind == "MUSCLE":
        return kind, _remap(state.muscles, source_id)
    return "NONE", ""


def _remap_soft_payloads(dst, snap, target_type, target_id):
    source_id = str(getattr(snap, "attachment_target_id", "") or "")
    if target_type == "NONE" or not source_id or not target_id:
        return
    dst.control_bindings_json = remap_binding_target(dst.control_bindings_json, target_type, source_id, target_id)
    dst.base_bindings_json = remap_binding_target(dst.base_bindings_json, target_type, source_id, target_id)
    for row in dst.attachments:
        row.bindings_json = remap_binding_target(row.bindings_json, target_type, source_id, target_id)


def _mapped_soft_source(state, source_type, source_id):
    if source_type == "FIBER":
        return _remap(state.fibers, source_id)
    if source_type == "FIBER_SURFACE":
        return _remap(state.fiber_surfaces, source_id)
    return ""


def _soft_host_compatible(state, host_id, snap):
    expected = str(dict(snap.props or {}).get("host_topology_signature", "") or "")
    scp = _scp_by_id(state.root, host_id)
    obj = None if scp is None else getattr(scp, "geometry_object_ref", None)
    current = "" if obj is None or getattr(obj, "type", "") != "MESH" else mesh_topology_signature(obj.data)
    return bool(current and (not expected or current == expected))


def _copy_soft_attachments(dst, snap):
    for source in snap.attachments:
        row = dst.attachments.add()
        apply_scalar_dict(row, source.props)


def _keep_tissue_base(state, base, tissue):
    _link_object(state, base)
    base["af_soft_tissue_base"] = True
    base["af_soft_tissue_id"] = str(tissue.id)
    base["af_root_name"] = str(state.root.name)
    if base not in state.kept_objects:
        state.kept_objects.append(base)


def _create_soft_tissues(state):
    for snap in state.snapshot.soft_tissues:
        _create_one_soft_tissue(state, snap)


def _create_diff_soft_tissues(state):
    for snap in state.snapshot.soft_tissues:
        if _soft_target_was_imported(state, snap):
            _create_one_soft_tissue(state, snap)


def _soft_target_was_imported(state, snap):
    kind = str(getattr(snap, "attachment_target_type", "NONE") or "NONE")
    source_id = str(getattr(snap, "attachment_target_id", "") or "")
    if kind == "SCP":
        return source_id in state.imported_scps
    if kind == "MUSCLE":
        return source_id in state.muscles
    return not snap.host_scp_id or str(snap.host_scp_id) in state.imported_scps


def _blob_object_scp_id(snap):
    scp_id, _bound_id = split_bound_entity_id(getattr(snap, "attach_object_entity", ""))
    return scp_id


def _diff_blob_snap(state, snap):
    kind = str(snap.attach_target_type or "NONE")
    if kind == "SCP":
        return str(snap.attach_target_id or "") in state.imported_scps
    if kind == "MUSCLE":
        return bool(_remap(state.muscles, snap.attach_target_id))
    return kind == "OBJECT" and _blob_object_scp_id(snap) in state.imported_scps


def _create_diff_blobs(state):
    for snap in state.snapshot.blobs:
        if _diff_blob_snap(state, snap):
            _create_one_blob(state, snap)


def _add_shortcut(state, snap):
    item = state.root.af_shortcut_system.shortcuts.add()
    item.id = next_prefixed_id(state.root.af_shortcut_system.shortcuts, "SHORTCUT")
    item.name = str(snap.name or item.id)
    item.owner_type = str(snap.owner_type or "NONE")
    item.owner_id = _shortcut_owner_id(state, snap.owner_type, snap.owner_id)
    item.data_path = _remap_shortcut_path(state, snap.data_path)
    item.vector_mode = str(getattr(snap, "vector_mode", "DEFAULT") or "DEFAULT")
    item.owner_backsolve = bool(getattr(snap, "owner_backsolve", True))
    _copy_shortcut_overrides(state, item, snap)
    state.shortcut_count += 1


def _copy_shortcut_overrides(state, item, snap):
    for override in getattr(snap, "overrides", ()):
        mapped = _remap(state.scps, getattr(override, "target_scp_id", ""))
        if mapped:
            upsert_override(item, mapped, getattr(override, "parent_anchor_mode", "KEEP"), getattr(override, "child_anchor_mode", "KEEP"), getattr(override, "follow_rotation_mode", "KEEP"), getattr(override, "rotation_strategy", "KEEP"))


def _create_shortcuts(state):
    for snap in state.snapshot.shortcuts:
        _add_shortcut(state, snap)


def _shortcut_owner_imported(state, snap):
    kind = str(snap.owner_type or "NONE")
    oid = str(snap.owner_id or "")
    if kind == "SCP":
        return oid in state.imported_scps
    maps = {"FIBER": state.fibers, "FIBER_SURFACE": state.fiber_surfaces,
            "MUSCLE": state.muscles, "BLOB": state.blobs,
            "SOFT_TISSUE": state.soft_tissues}
    return bool(_remap(maps.get(kind, {}), oid))


def _shortcut_path_scp_id(raw):
    kind, entity_id, _prop_spec = parse_shortcut_path(raw)
    if kind == "scp_bound_rna":
        return split_bound_entity_id(entity_id)[0]
    return entity_id if kind in {"scp_prop", "scp_object"} else ""


def _shortcut_override_imported(state, snap):
    ids = [str(item.target_scp_id or "") for item in getattr(snap, "overrides", ())]
    return any(sid in state.imported_scps for sid in ids)


def _shortcut_diff_snap(state, snap):
    if _shortcut_owner_imported(state, snap):
        return True
    if _shortcut_path_scp_id(snap.data_path) in state.imported_scps:
        return True
    return _shortcut_override_imported(state, snap)


def _create_diff_shortcuts(state):
    for snap in state.snapshot.shortcuts:
        if _shortcut_diff_snap(state, snap):
            _add_shortcut(state, snap)


def _create_vcps(state):
    from .branching import restore_graph
    with suppress_vcp_prop_updates():
        _create_fibers(state)
        _create_fiber_surfaces(state)
        _create_muscles(state)
        restore_graph(state)
        _create_blobs(state)
        _create_soft_tissues(state)


def _create_diff_vcps(state):
    from .branching import restore_graph
    with suppress_vcp_prop_updates():
        _create_diff_fibers(state)
        _create_diff_fiber_surfaces(state)
        _create_diff_muscles(state)
        restore_graph(state)
        _create_diff_blobs(state)
        _create_diff_soft_tissues(state)


def _result(state):
    return ImportResult(scp_count=len(state.imported_scps), fiber_count=len(state.fibers),
                        muscle_count=len(state.muscles), blob_count=len(state.blobs),
                        soft_tissue_count=len(state.soft_tissues), shortcut_count=state.shortcut_count,
                        fiber_surface_count=len(state.fiber_surfaces), warnings=state.warnings,
                        kept_objects=state.kept_objects)


def _dirty_for_diff(state):
    dirty = DirtyHints(full=False)
    dirty["SCP"] = {sid for sid in state.imported_scps if sid}
    dirty["FIBER"] = set(state.fibers.values())
    dirty["FIBER_SURFACE"] = set(state.fiber_surfaces.values())
    dirty["MUSCLE"] = set(state.muscles.values())
    dirty["BLOB"] = set(state.blobs.values())
    dirty["SOFT_TISSUE"] = set(state.soft_tissues.values())
    return dirty


def _has_dirty(dirty):
    return any(bool(values) for values in dict(dirty or {}).values())


def _schedule_diff_sync(state):
    from ..visualization.warning_runtime import structural_change, notify_action
    structural_change(state.root)
    notify_action(state.root, state.scene, full=True, event_type="IMPORT")
    dirty = _dirty_for_diff(state)
    if _has_dirty(dirty):
        payload = {"soft_tissue_force": True} if state.soft_tissues else None
        schedule_sync_from_dirty_hints(root=state.root, scene=state.scene, dirty_hints=dirty,
                                       source="operator", event_type="IMPORT", payload=payload)


def _apply_draft_skin_settings(state):
    apply_scalar_dict(state.root.af_draft_skin_settings, state.snapshot.draft_skin_settings)


def _apply_topology_settings(state):
    apply_scalar_dict(state.root.af_topology_settings, state.snapshot.topology_settings)


def apply_snapshot(snapshot, stage_root, root, context):
    from .free_fibers import atomic_import
    return atomic_import(root, context.scene, snapshot, {s.source_id for s in snapshot.scps},
                         lambda: _apply_snapshot(snapshot, stage_root, root, context))


def _apply_snapshot(snapshot, stage_root, root, context):
    from ..muscle_relationships.importing import merge
    state = MergeState(root, context.scene, _target_collection(context), snapshot, stage_root, stage_bound_map(stage_root))
    _apply_draft_skin_settings(state)
    _apply_topology_settings(state)
    _create_scps(state)
    _set_scp_parents(state)
    _create_vcps(state)
    merge(state)
    _create_shortcuts(state)
    sync_all_scp_roles(root)
    cleanup_scp_dependents(root)
    sync_from_dirty_hints(root=root, scene=context.scene, dirty_hints=empty_dirty_hints(), source="operator", event_type="IMPORT")
    return _result(state)


def apply_scp_diff_snapshot(snapshot, stage_root, root, context):
    from .free_fibers import atomic_import
    return atomic_import(root, context.scene, snapshot, {s.source_id for s in snapshot.scps},
                         lambda: _apply_scp_diff_snapshot(snapshot, stage_root, root, context))


def _apply_scp_diff_snapshot(snapshot, stage_root, root, context):
    from ..muscle_relationships.importing import merge
    state = MergeState(root, context.scene, _target_collection(context), snapshot, stage_root, stage_bound_map(stage_root))
    _seed_existing_scps(state)
    _create_missing_scps(state)
    _set_imported_scp_parents(state)
    _create_diff_vcps(state)
    merge(state)
    _create_diff_shortcuts(state)
    sync_all_scp_roles(root)
    cleanup_scp_dependents(root)
    _schedule_diff_sync(state)
    return _result(state)
