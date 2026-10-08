"""Rollback geometry, controls and bindings together if publication fails."""
from contextlib import contextmanager
import bpy
from ..vcp.prop_update_guard import suppress_vcp_prop_updates


FIELDS = ("base_domain", "inflation_mode", "boundary_mode", "tolerance", "base_closed", "base_signature",
          "attachment_topology_signature", "control_bindings_json", "base_bindings_json", "evaluation_revision")


@contextmanager
def evaluation_transaction(collection, root, tissue):
    values = {key: getattr(tissue, key) for key in FIELDS}
    bindings = [row.bindings_json for row in tissue.attachments]
    proxies = _proxies(collection, root, tissue)
    objects = [(obj, False) for obj in proxies] + ([(tissue.base_object_ref, True)] if tissue.base_object_ref is not None else [])
    snapshots = []
    try:
        yield lambda: snapshots.extend(_snapshot(obj, source) for obj, source in objects)
    except Exception:
        _restore(tissue, values, bindings, snapshots)
        for obj in set(_proxies(collection, root, tissue)) - set(proxies):
            _remove_object(obj)
        raise
    finally:
        _discard(snapshots)


def _proxies(collection, root, tissue):
    return tuple(obj for obj in collection.objects if obj.get("af_root_name") == root.name
                 and obj.get("af_soft_tissue_id") == tissue.id
                 and (obj.get("af_soft_tissue_proxy") or obj.get("af_soft_tissue_rest_proxy")))


def _snapshot(obj, source):
    data = obj.data.copy() if obj.data is not None else None
    return obj, data, obj.matrix_world.copy(), (obj.hide_viewport, obj.hide_render), source


def _restore(tissue, values, bindings, snapshots):
    with suppress_vcp_prop_updates():
        for key, value in values.items():
            if getattr(tissue, key) != value:
                setattr(tissue, key, value)
        for row, raw in zip(tissue.attachments, bindings):
            if row.bindings_json != raw:
                row.bindings_json = raw
        for snapshot in snapshots:
            _restore_object(*snapshot)


def _restore_object(obj, data, matrix, hidden, source):
    old = obj.data
    if data is not None:
        if source:
            _restore_source_data(obj, data)
        else:
            obj.data = data
    obj.matrix_world = matrix
    obj.hide_viewport, obj.hide_render = hidden
    _remove_unused(old)


def _restore_source_data(obj, data):
    if obj.type == "MESH":
        for point, saved in zip(obj.data.vertices, data.vertices):
            point.co = saved.co
        obj.data.update()
    elif obj.type == "CURVE":
        for spline, saved in zip(obj.data.splines, data.splines):
            for point, prior in zip(spline.points, saved.points):
                point.co = prior.co
            for point, prior in zip(spline.bezier_points, saved.bezier_points):
                point.co, point.handle_left, point.handle_right = prior.co, prior.handle_left, prior.handle_right


def _discard(snapshots):
    for _obj, data, _matrix, _hidden, _source in snapshots:
        _remove_unused(data)


def _remove_unused(data):
    if data is not None and data.users == 0:
        bpy.data.batch_remove(ids=(data,))


def _remove_object(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    _remove_unused(data)
