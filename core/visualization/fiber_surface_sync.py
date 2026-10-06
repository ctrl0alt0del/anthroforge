import time

import bpy

from ..vcp.fiber_modes import is_loop_fiber
from ..vcp.fiber_surface import FiberSurfaceSpec, evaluate_fiber_surface
from ..vcp.runtime_state import set_fiber_surface_runtime
from .muscle_sync_helpers import get_vis_collection, remove_proxy_obj, update_mesh
from .muscle_sync_runtime import collect_surface_rows
from .vcp_object_index import build_vcp_object_index
from ..vcp.free_path import is_free, fiber_geometry_point_count


class FiberSurfaceSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS"):
        self.collection_name = collection_name
        self._syncing = False

    def sync_root_to_scene(self, root, scene, target_surface_ids=None):
        if self._syncing:
            return
        self._syncing = True
        try:
            self._sync_pass(root, scene, target_surface_ids)
        finally:
            self._syncing = False

    def _sync_pass(self, root, scene, target_ids):
        collection = get_vis_collection(scene, self.collection_name)
        index = build_vcp_object_index(scene, root.name)
        surfaces = tuple(root.af_vcp_system.fiber_surfaces)
        for surface in _target_surfaces(surfaces, target_ids):
            self._sync_surface(root, scene, collection, index, surface)
        _cleanup_removed(collection, root.name, {surface.id for surface in surfaces})

    def _sync_surface(self, root, scene, collection, index, surface):
        started = time.perf_counter()
        try:
            result = evaluate_surface_record(root, scene, surface, index=index)
            proxy = _ensure_proxy(collection, root, surface, index)
            update_mesh(proxy, result.vertices, result.faces)
            _mark_surface_current(proxy)
            _finish_surface(surface, started, "CLEAN")
        except Exception as exc:
            _mark_surface_stale(index, surface)
            _finish_surface(surface, started, "ERROR", str(exc))


def _target_surfaces(surfaces, target_ids):
    allowed = None if target_ids is None else set(target_ids)
    return [surface for surface in surfaces if allowed is None or surface.id in allowed]


def evaluate_surface_record(root, scene, surface, index=None):
    if surface.construction_mode == "BRANCHED_LOFT":
        return _evaluate_branched(root, scene, surface)
    fibers = _source_fibers(root, surface)
    _validate_sources(surface, fibers)
    rows = collect_surface_rows(root, scene, surface, fibers, index=index)
    if not rows:
        raise ValueError("Fiber Surface source geometry is unavailable.")
    return evaluate_fiber_surface(rows, _surface_spec(surface, fibers))


def _evaluate_branched(root, scene, surface):
    from .branched_surface_capture import capture_assembly
    from ..vcp.branched_surface import assemble
    from ..vcp.fiber_surface import FiberSurfaceResult
    vertices, faces = assemble(capture_assembly(root, scene, surface))
    return FiberSurfaceResult(tuple(map(tuple, vertices)), tuple(map(tuple, faces)))


def find_fiber_surface_proxy(scene, root_name, surface_id):
    return next((obj for obj in scene.objects if obj.get("af_fiber_surface_proxy")
                 and obj.get("af_root_name") == root_name
                 and obj.get("af_fiber_surface_id") == surface_id), None)


def _mark_surface_current(proxy):
    proxy["af_fiber_surface_output_state"] = "CURRENT"
    key = "af_fiber_surface_output_generation"
    proxy[key] = int(proxy.get(key, 0)) + 1


def _mark_surface_stale(index, surface):
    proxy = dict(index.get("fiber_surface", {})).get(str(surface.id))
    if proxy is not None:
        proxy["af_fiber_surface_output_state"] = "STALE"


def _source_fibers(root, surface):
    by_id = {fiber.id: fiber for fiber in root.af_vcp_system.fibers}
    fibers = [by_id.get(ref.fiber_id) for ref in surface.fiber_refs]
    if any(fiber is None for fiber in fibers):
        raise ValueError("Fiber Surface references a missing Fiber.")
    return fibers


def _validate_sources(surface, fibers):
    mode = str(surface.construction_mode or "LOFT")
    if mode == "LOOP_PATCH" and (len(fibers) != 1 or not is_loop_fiber(fibers[0])):
        raise ValueError("LOOP_PATCH requires exactly one LOOP Fiber.")
    if mode == "LOFT":
        _validate_loft_fibers(surface, fibers)


def _validate_loft_fibers(surface, fibers):
    minimum = 1 if bool(getattr(surface, "use_mirrored_rows", False)) else 2
    if len(fibers) < minimum:
        raise ValueError("LOFT requires at least two Fibers.")
    modes = {bool(is_loop_fiber(fiber)) for fiber in fibers}
    counts = {int(fiber.node_count) for fiber in fibers}
    if len(modes) != 1 or (not any(is_free(f) for f in fibers) and len(counts) != 1):
        raise ValueError("LOFT Fibers must share topology and node count.")


def _surface_spec(surface, fibers):
    from ..vcp.free_surface_stations import resolve
    loop = bool(fibers and is_loop_fiber(fibers[0]))
    count = fiber_geometry_point_count(fibers[0]) if fibers else 0
    return FiberSurfaceSpec(str(surface.construction_mode), bool(surface.close_across_fibers), loop,
                            bool(surface.flip_normals), int(surface.patch_resolution), count, any(is_free(f) for f in fibers), resolve(surface, fibers))


def _ensure_proxy(collection, root, surface, index):
    proxy = index.get("fiber_surface", {}).get(str(surface.id))
    if proxy is not None:
        return proxy
    mesh = bpy.data.meshes.new(f"AF_{surface.id}_mesh")
    proxy = bpy.data.objects.new(f"AF_{surface.id}", mesh)
    _mark_proxy(proxy, root, surface)
    collection.objects.link(proxy)
    return proxy


def _mark_proxy(proxy, root, surface):
    proxy["af_fiber_surface_proxy"] = True
    proxy["af_fiber_surface_id"] = str(surface.id)
    proxy["af_root_name"] = str(root.name)
    proxy.lock_location = proxy.lock_rotation = proxy.lock_scale = (True, True, True)
    proxy.hide_render = True


def _finish_surface(surface, started, status, error=""):
    elapsed = (time.perf_counter() - started) * 1000.0
    set_fiber_surface_runtime(surface, status, elapsed, error)


def _cleanup_removed(collection, root_name, live_ids):
    for obj in tuple(collection.objects):
        owned = obj.get("af_fiber_surface_proxy") and obj.get("af_root_name") == root_name
        if owned and str(obj.get("af_fiber_surface_id")) not in live_ids:
            remove_proxy_obj(obj)


_FIBER_SURFACE_SYNC = None


def register_fiber_surface_sync():
    global _FIBER_SURFACE_SYNC
    if _FIBER_SURFACE_SYNC is None:
        _FIBER_SURFACE_SYNC = FiberSurfaceSceneSync()
    return _FIBER_SURFACE_SYNC


def unregister_fiber_surface_sync():
    global _FIBER_SURFACE_SYNC
    _FIBER_SURFACE_SYNC = None
