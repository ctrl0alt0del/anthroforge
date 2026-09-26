"""Targeted reversible muscle publication, shared by manual and native commands."""
from contextlib import contextmanager
import bpy
from ..vcp.prop_update_guard import suppress_vcp_prop_updates
from .muscle_sync import register_muscle_sync
from .muscle_numeric_runtime import MuscleNumericWork, publish_muscle_work
from .vcp_mirror_runtime import sync_vcp_mirrors
from .muscle_legacy_profile import related_muscles, related_entities, related_tissues, normal_snapshot

OBJECT_FIELDS = ('empty_display_type', 'empty_display_size', 'display_type', 'display_bounds_type',
    'show_in_front', 'show_wire', 'show_all_edges', 'show_name', 'show_axis', 'show_bounds',
    'hide_render', 'hide_viewport', 'hide_select', 'color', 'lock_location', 'lock_rotation', 'lock_scale')


def affected_objects(root, scene, muscle_id):
    return tuple(obj for obj in scene.objects if obj.get("af_root_name") == root.name and
        (obj.get("af_muscle_id") == muscle_id or obj.get("af_source_muscle_id") == muscle_id))


def transaction_objects(root, scene, muscle):
    affected = related_entities(root, muscle)
    return tuple(obj for obj in scene.objects if obj.get('af_root_name') == root.name and any(
        str(obj.get(key, '')) == identity for kind, identity in affected for key in
        (f'af_{kind.lower()}_id', f'af_source_{kind.lower()}_id')))


def _snapshots(objects, scene):
    copies = {data: data.copy() for data in {obj.data for obj in objects if obj.data is not None}}
    return tuple((obj.name, copies.get(obj.data), obj.id_properties_ensure().to_dict(), obj.matrix_world.copy(), tuple(obj.users_collection),
                  _object_state(obj, scene)) for obj in objects)


def _object_state(obj, scene):
    values = {key: getattr(obj, key) for key in OBJECT_FIELDS}
    values = {key: tuple(value) if hasattr(value, '__len__') and not isinstance(value, str) else value for key, value in values.items()}
    hidden = tuple((layer, obj.hide_get(view_layer=layer)) for layer in scene.view_layers if layer.objects.get(obj.name) == obj)
    relations = tuple(_object_relation(item) for item in (obj, *obj.children))
    return values, hidden, relations


def _object_relation(obj):
    return (obj.name, getattr(obj.parent, 'name', None), obj.parent_type, obj.parent_bone, tuple(obj.parent_vertices),
            obj.matrix_parent_inverse.copy(), obj.matrix_basis.copy(), obj.rotation_mode)


@contextmanager
def transaction(root, scene, muscle=None):
    settings = _settings_snapshots(root, muscle)
    muscle_ids, objects = {item.id for item in root.af_vcp_system.muscles}, set(bpy.data.objects)
    saved = _snapshots(transaction_objects(root, scene, muscle), scene) if muscle else ()
    selection, journal, normal = _selection(scene), root.get("af_authoring_journal"), normal_snapshot(root, muscle)
    try:
        with suppress_vcp_prop_updates():
            yield
    except BaseException:
        _rollback(root, settings, muscle_ids, objects, saved)
        _restore_context(root, scene, selection, journal, normal)
        raise
    finally:
        _discard_copies(saved)


def _settings_snapshots(root, muscle):
    if muscle is None:
        return ()
    from .branch_control import branch_surface
    owners = related_muscles(root, muscle)
    surfaces = tuple(filter(None, (branch_surface(root, owner) for owner in owners)))
    parts = (*owners, *(branch.settings for surface in surfaces for branch in surface.branches), *related_tissues(root, muscle))
    return tuple((part, part.id_properties_ensure().to_dict()) for part in parts)


def _restore_settings(saved):
    for settings, values in saved:
        for key in tuple(settings.keys()):
            del settings[key]
        for key, value in values.items():
            settings[key] = value


def _rollback(root, settings, ids, objects, saved):
    with suppress_vcp_prop_updates():
        _restore_settings(settings)
        for obj in set(bpy.data.objects) - objects:
            if obj.get("af_root_name") == root.name and any(obj.get(k) for k in ('af_muscle_id', 'af_fiber_surface_id', 'af_blob_id', 'af_soft_tissue_id')):
                _remove_object(obj)
        for index in reversed(range(len(root.af_vcp_system.muscles))):
            if root.af_vcp_system.muscles[index].id not in ids:
                root.af_vcp_system.muscles.remove(index)
        _restore_objects(saved)


def _restore_objects(saved):
    for name, data, props, matrix, collections, state in saved:
        obj = bpy.data.objects.get(name)
        if obj is None:
            obj = bpy.data.objects.new(name, data)
        _restore_collections(obj, collections)
        previous, obj.data = obj.data, data
        for key in tuple(obj.keys()):
            del obj[key]
        for key, value in props.items():
            obj[key] = value
        obj.matrix_world = matrix
        _remove_data(previous)
    _restore_object_states(saved)


def _restore_collections(obj, collections):
    for collection in set(obj.users_collection) - set(collections):
        collection.objects.unlink(obj)
    for collection in set(collections) - set(obj.users_collection):
        collection.objects.link(obj)


def _restore_object_states(saved):
    for name, _, _, _, _, (values, hidden, relations) in saved:
        obj = bpy.data.objects[name]
        for key, value in values.items():
            setattr(obj, key, value)
        for layer, value in hidden:
            obj.hide_set(value, view_layer=layer)
        for relation in relations:
            _restore_relation(relation)


def _restore_relation(relation):
    name, parent, kind, bone, vertices, inverse, basis, rotation = relation
    obj = bpy.data.objects.get(name)
    if obj is not None:
        obj.parent = bpy.data.objects.get(parent) if parent else None
        obj.parent_type, obj.parent_bone, obj.parent_vertices = kind, bone, vertices
        obj.rotation_mode, obj.matrix_parent_inverse, obj.matrix_basis = rotation, inverse, basis


def _remove_data(data):
    if data is not None and data.users == 0:
        bpy.data.batch_remove(ids=(data,))


def _remove_object(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    _remove_data(data)


def _discard_copies(saved):
    for data in {row[1] for row in saved}:
        _remove_data(data)


def _selection(scene):
    return tuple((layer, tuple(obj.name for obj in layer.objects if obj.select_get(view_layer=layer)),
                  getattr(layer.objects.active, "name", None)) for layer in scene.view_layers)


def _restore_selection(scene, selection):
    for layer, selected, active in selection:
        for obj in layer.objects:
            obj.select_set(obj.name in selected, view_layer=layer)
        layer.objects.active = bpy.data.objects.get(active) if active else None


def _restore_context(root, scene, selection, journal, normal):
    if normal:
        with suppress_vcp_prop_updates():
            normal[0].flip_normals = normal[1]
    _restore_selection(scene, selection)
    if journal is None:
        if "af_authoring_journal" in root:
            del root["af_authoring_journal"]
    else:
        root["af_authoring_journal"] = journal


def publish(root, scene, muscle, request, batch):
    sync = register_muscle_sync()
    collection = sync._get_vis_collection(scene)
    base, inflated = sync._ensure_muscle_meshes(collection, root, muscle.id)
    work = MuscleNumericWork(muscle, base, inflated, request)
    publish_muscle_work(sync, collection, root, scene, root.af_vcp_system, (work,), batch)
    sync_vcp_mirrors(root, scene, (), {muscle.id}, (), ())
    if any(obj.get("af_muscle_output_state") != "CURRENT" for obj in (base, inflated)):
        raise ValueError("PROFILE_PUBLICATION_FAILED")
    _verify_output(base, inflated, batch.results[0])


def _verify_output(base, inflated, result):
    from .muscle_numeric_runtime import mesh_matches
    from ..vcp.muscle_envelope import faces_for
    for obj, expected in ((base, result.base_vertices), (inflated, result.inflated_vertices)):
        if not mesh_matches(obj, expected, faces_for(result, obj == inflated)):
            raise ValueError("PROFILE_PUBLICATION_FAILED: mesh differs from evaluated geometry")


def refresh(root, scene, muscle_id):
    from .warning_runtime import notify_action
    sync = register_muscle_sync()
    with suppress_vcp_prop_updates():
        sync._sync_target_muscles(sync._get_vis_collection(scene), root, scene, root.af_vcp_system, {muscle_id})
        sync_vcp_mirrors(root, scene, (), {muscle_id}, (), ())
    notify_action(root, scene, {"MUSCLE": {muscle_id}})
