"""Preserve the exact shared Free graph when duplicating native SCP subtrees."""
from types import SimpleNamespace
from ..vcp.free_path import is_free
from ..vcp.prop_update_guard import suppress_vcp_prop_updates
from ..importing.branching import capture_graph, restore_graph
from ..importing.rna import scalar_dict, apply_scalar_dict


def copy_if_free(root, scene, action):
    if not any(is_free(f) for f in root.af_vcp_system.fibers): return action()
    from ..importing.free_fibers import transaction
    with suppress_vcp_prop_updates(): return transaction(root, scene, action)


def _surfaces(root, maps):
    from .copy import _new_item, _copy_fiber_refs
    for source in tuple(root.af_vcp_system.fiber_surfaces):
        if not source.fiber_refs or any(r.fiber_id not in maps['fibers'] for r in source.fiber_refs): continue
        target = _new_item(root.af_vcp_system.fiber_surfaces, 'SURFACE')
        apply_scalar_dict(target, scalar_dict(source, {'id', 'main_surface_id'}))
        _copy_fiber_refs(source, target, maps['fibers']); maps['fiber_surfaces'][source.id] = target.id


def _muscles(root, maps):
    from .copy import _new_item
    for source in tuple(root.af_vcp_system.muscles):
        if source.fiber_surface_id not in maps['fiber_surfaces']: continue
        target = _new_item(root.af_vcp_system.muscles, 'MUSCLE')
        apply_scalar_dict(target, scalar_dict(source, {'id', 'fiber_surface_id'}))
        target.fiber_surface_id = maps['fiber_surfaces'][source.fiber_surface_id]; maps['muscles'][source.id] = target.id


def finish_graph(root, scene, maps):
    if not any(is_free(f) and f.id in maps['fibers'] for f in root.af_vcp_system.fibers): return
    graph = capture_graph(root); maps['fiber_surfaces'] = {}
    _surfaces(root, maps); _muscles(root, maps)
    state = SimpleNamespace(root=root, scene=scene, snapshot=SimpleNamespace(branching=graph), **maps)
    restore_graph(state)
