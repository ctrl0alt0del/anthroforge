"""Refresh geometry consumers without re-evaluating intrinsic muscle inflation."""
from contextlib import contextmanager


def affected(root, muscles):
    from ..deps.adapters import build_runtime_graph
    from ..deps.runtime_graph import RuntimeGraph
    graph = RuntimeGraph(); build_runtime_graph(root, graph)
    return graph.downstream_entities({('MUSCLE', key) for key in muscles})


def refresh(scene, root, entities):
    from ..visualization.blob_sync import register_blob_sync
    from ..visualization.soft_tissue_sync import register_soft_tissue_sync
    from ..visualization.vcp_mirror_runtime import sync_vcp_mirrors
    blobs = {key for kind, key in entities if kind == 'BLOB'}
    tissues = {key for kind, key in entities if kind == 'SOFT_TISSUE'}
    if blobs: register_blob_sync().sync_root_to_scene(root, scene, blobs)
    if tissues: register_soft_tissue_sync().sync_root_to_scene(root, scene, tissues, force=True)
    if blobs or tissues: sync_vcp_mirrors(root, scene, (), (), blobs, tissues)


@contextmanager
def transaction(scene, root, muscles):
    import bpy
    from ..visualization.muscle_profile_publish import _snapshots, _restore_objects, _discard_copies, _remove_object
    entities = affected(root, muscles)
    objects = tuple(o for o in scene.objects if o.get('af_root_name') == root.name and any(
        o.get(tag) == key for kind, key in entities if kind in ('BLOB', 'SOFT_TISSUE')
        for tag in (f'af_{kind.lower()}_id', f'af_source_{kind.lower()}_id')))
    before = set(bpy.data.objects); saved = _snapshots(objects, scene)
    try: yield entities
    except BaseException:
        for obj in set(bpy.data.objects)-before:
            if obj.get('af_root_name') == root.name and (obj.get('af_blob_id') or obj.get('af_soft_tissue_id')): _remove_object(obj)
        _restore_objects(saved); raise
    finally: _discard_copies(saved)
