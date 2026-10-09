"""Preserve the exact shared Free graph when duplicating native SCP subtrees."""
from types import SimpleNamespace
from ..vcp.free_path import is_free
from ..vcp.prop_update_guard import suppress_vcp_prop_updates
from ..importing.branching import capture_graph, restore_graph
from ..importing.rna import scalar_dict, apply_scalar_dict


def copy_if_free(root, scene, action):
    from ..vcp.attachment_surface import muscle_backed
    if not any(is_free(f) or muscle_backed(f) for f in root.af_vcp_system.fibers): return action()
    from ..importing.free_fibers import transaction
    from .prop_update_guard import suppress_scp_prop_updates
    with suppress_vcp_prop_updates(), suppress_scp_prop_updates(): return transaction(root, scene, action)


def _surfaces(root, maps):
    from .copy import _new_item, _copy_fiber_refs, _item_by_id
    for identity in tuple(source.id for source in root.af_vcp_system.fiber_surfaces):
        source = _item_by_id(root.af_vcp_system.fiber_surfaces, identity)
        if source.id in maps['fiber_surfaces']: continue
        if not _surface_ready(source, maps): continue
        target = _new_item(root.af_vcp_system.fiber_surfaces, 'SURFACE')
        source = _item_by_id(root.af_vcp_system.fiber_surfaces, identity)
        apply_scalar_dict(target, scalar_dict(source, {'id', 'main_surface_id'}))
        _copy_fiber_refs(source, target, maps['fibers']); maps['fiber_surfaces'][source.id] = target.id


def _surface_ready(source, maps):
    if source.construction_mode == 'BRANCHED_LOFT':
        return all(key in maps['fiber_surfaces'] for key in (source.main_surface_id, *(b.surface_id for b in source.branches)))
    return bool(source.fiber_refs) and all(r.fiber_id in maps['fibers'] for r in source.fiber_refs)


def _muscles(root, maps):
    from .copy import _new_item, _item_by_id
    for identity in tuple(source.id for source in root.af_vcp_system.muscles):
        source = _item_by_id(root.af_vcp_system.muscles, identity)
        if source.id in maps['muscles']: continue
        if source.fiber_surface_id not in maps['fiber_surfaces']: continue
        target = _new_item(root.af_vcp_system.muscles, 'MUSCLE')
        source = _item_by_id(root.af_vcp_system.muscles, identity)
        apply_scalar_dict(target, scalar_dict(source, {'id', 'fiber_surface_id'}))
        target.fiber_surface_id = maps['fiber_surfaces'][source.fiber_surface_id]; maps['muscles'][source.id] = target.id


def finish_graph(root, scene, maps):
    from ..importing.extract import root_snapshot
    snapshot = root_snapshot(root); maps['fiber_surfaces'] = {}
    _copy_dependency_chain(root, maps)
    state = SimpleNamespace(root=root, scene=scene, snapshot=snapshot, **maps)
    restore_graph(state)
    _copy_tissues(state)


def _copy_tissues(state):
    from ..importing.merge import _create_one_soft_tissue, _mapped_soft_source
    state.soft_tissues, state.warnings, state.kept_objects, state.stage_root = {}, [], [], None
    for tissue in state.snapshot.soft_tissues:
        if tissue.base_source_type == 'OBJECT': continue
        if _mapped_soft_source(state, tissue.base_source_type, tissue.base_source_id): _create_one_soft_tissue(state, tissue)


def _copy_dependency_chain(root, maps):
    from .copy import _copy_fibers, _copy_muscles
    previous = None
    while previous != (len(maps['fibers']), len(maps['muscles']), len(maps['fiber_surfaces'])):
        previous = len(maps['fibers']), len(maps['muscles']), len(maps['fiber_surfaces'])
        _surfaces(root, maps); _muscles(root, maps)
        _copy_fibers(root, set(maps['scps']), maps); _copy_muscles(root, maps)
