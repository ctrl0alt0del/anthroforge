"""Targeted reversible muscle publication, shared by manual and native commands."""
from contextlib import contextmanager
import bpy
from ..vcp.prop_update_guard import suppress_vcp_prop_updates
from .muscle_sync import register_muscle_sync
from .muscle_numeric_runtime import MuscleNumericWork, publish_muscle_work
from .vcp_mirror_runtime import sync_vcp_mirrors


def affected_objects(root, scene, muscle_id):
    return tuple(obj for obj in scene.objects if obj.get("af_root_name") == root.name and
        (obj.get("af_muscle_id") == muscle_id or obj.get("af_source_muscle_id") == muscle_id))


def _snapshots(objects):
    copies = {data: data.copy() for data in {obj.data for obj in objects if obj.data is not None}}
    return tuple((obj.name, copies.get(obj.data), dict(obj.items()), obj.matrix_world.copy(), tuple(obj.users_collection)) for obj in objects)


@contextmanager
def transaction(root, scene, muscle=None):
    values = muscle.id_properties_ensure().to_dict() if muscle is not None else None
    muscle_ids, objects = {item.id for item in root.af_vcp_system.muscles}, set(bpy.data.objects)
    saved = _snapshots(affected_objects(root, scene, muscle.id)) if muscle else ()
    selection, journal = _selection(scene), root.get("af_authoring_journal")
    try:
        with suppress_vcp_prop_updates():
            yield
    except BaseException:
        _rollback(root, muscle, values, muscle_ids, objects, saved)
        _restore_context(root, scene, selection, journal)
        raise
    finally:
        _discard_copies(saved)


def _rollback(root, muscle, values, ids, objects, saved):
    with suppress_vcp_prop_updates():
        if muscle is not None:
            for key in tuple(muscle.keys()):
                del muscle[key]
            for key, value in values.items():
                muscle[key] = value
        for obj in set(bpy.data.objects) - objects:
            if obj.get("af_root_name") == root.name and obj.get("af_muscle_id"):
                _remove_object(obj)
        for index in reversed(range(len(root.af_vcp_system.muscles))):
            if root.af_vcp_system.muscles[index].id not in ids:
                root.af_vcp_system.muscles.remove(index)
        _restore_objects(saved)


def _restore_objects(saved):
    for name, data, props, matrix, collections in saved:
        obj = bpy.data.objects.get(name)
        if obj is None:
            obj = bpy.data.objects.new(name, data)
            for collection in collections:
                collection.objects.link(obj)
        previous, obj.data = obj.data, data
        for key in tuple(obj.keys()):
            del obj[key]
        for key, value in props.items():
            obj[key] = value
        obj.matrix_world = matrix
        _remove_data(previous)


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


def _restore_context(root, scene, selection, journal):
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
    for obj, expected in ((base, result.base_vertices), (inflated, result.inflated_vertices)):
        if not mesh_matches(obj, expected, result.faces):
            raise ValueError("PROFILE_PUBLICATION_FAILED: mesh differs from evaluated geometry")


def refresh(root, scene, muscle_id):
    from .warning_runtime import notify_action
    sync = register_muscle_sync()
    with suppress_vcp_prop_updates():
        sync._sync_target_muscles(sync._get_vis_collection(scene), root, scene, root.af_vcp_system, {muscle_id})
        sync_vcp_mirrors(root, scene, (), {muscle_id}, (), ())
    notify_action(root, scene, {"MUSCLE": {muscle_id}})
