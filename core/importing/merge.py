from dataclasses import dataclass, field

from ..deps.dirty_hints import empty_dirty_hints
from ..id_utils import next_prefixed_id
from ..scp_runtime.bound_objects import find_bound_entry_by_object, sync_all_scp_roles
from ..scp_runtime.common import set_prop_raw
from ..scp_runtime.prop_update_guard import set_parent_id_raw
from ..scp_runtime.object_roles import add_bound_object_to_scp, create_scp, set_geometry_object, set_transform_object
from ..shortcuts import upsert_override
from ..shortcuts.path_codec import make_bound_entity_id, make_shortcut_path, parse_shortcut_path, split_bound_entity_id
from ..visualization.delete_reconcile import cleanup_scp_dependents
from ..visualization.sync_runner import sync_from_dirty_hints
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
    muscles: dict = field(default_factory=dict)
    blobs: dict = field(default_factory=dict)
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
    maps = {"SCP": state.scps, "FIBER": state.fibers, "MUSCLE": state.muscles, "BLOB": state.blobs}
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


def _create_one_scp(state, snap):
    scp = create_scp(state.root, snap.name)
    state.scps[str(snap.source_id or "")] = str(scp.id or "")
    apply_scalar_dict(scp, snap.props)
    local = {}
    for bound in snap.bound_objects:
        _add_bound(state, scp, snap.source_id, bound, local)
    _apply_roles(state, scp, snap, local)


def _create_scps(state):
    for snap in state.snapshot.scps:
        _create_one_scp(state, snap)


def _set_scp_parents(state):
    for snap in state.snapshot.scps:
        scp = next(x for x in state.root.af_scp_system.scps if str(x.id) == _remap(state.scps, snap.source_id))
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
    _copy_touches(dst, snap, state)
    _copy_loop_anchors(dst, snap, state)


def _create_fibers(state):
    for snap in state.snapshot.fibers:
        _create_one_fiber(state, snap)


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
    dst = _new_vcp_item(state.root.af_vcp_system.muscles, "MUSCLE")
    state.muscles[str(snap.source_id or "")] = str(dst.id or "")
    dst.name = str(snap.name or dst.id)
    apply_scalar_dict(dst, snap.props)
    _copy_refs(dst, snap, state)
    _assign_fiber_muscles(state, dst.id, snap)


def _create_muscles(state):
    for snap in state.snapshot.muscles:
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


def _copy_shortcut_overrides(state, item, snap):
    for override in getattr(snap, "overrides", ()):
        mapped = _remap(state.scps, getattr(override, "target_scp_id", ""))
        if mapped:
            upsert_override(item, mapped, getattr(override, "parent_anchor_mode", "KEEP"), getattr(override, "child_anchor_mode", "KEEP"), getattr(override, "follow_rotation_mode", "KEEP"), getattr(override, "rotation_strategy", "KEEP"))


def _create_shortcuts(state):
    for snap in state.snapshot.shortcuts:
        _add_shortcut(state, snap)


def _result(state):
    return ImportResult(len(state.snapshot.scps), len(state.snapshot.fibers), len(state.snapshot.muscles), len(state.snapshot.blobs), len(state.snapshot.shortcuts), state.warnings, state.kept_objects)


def apply_snapshot(snapshot, stage_root, root, context):
    state = MergeState(root, context.scene, _target_collection(context), snapshot, stage_root, stage_bound_map(stage_root))
    _create_scps(state)
    _set_scp_parents(state)
    _create_fibers(state)
    _create_muscles(state)
    _create_blobs(state)
    _create_shortcuts(state)
    sync_all_scp_roles(root)
    cleanup_scp_dependents(root)
    sync_from_dirty_hints(root=root, scene=context.scene, dirty_hints=empty_dirty_hints(), source="operator", event_type="IMPORT")
    return _result(state)
