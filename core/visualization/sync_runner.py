import bpy

from ..utils import get_af_root
from ..deps import run_dependency_runtime
from ..deps.dirty_hints import dirty_hints_for


_RUNNING = False


def _run(root=None, scene=None, dirty_hints=None, bake=False):
    global _RUNNING
    if _RUNNING:
        return

    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if scene is None or root is None:
        return

    _RUNNING = True
    try:
        run_dependency_runtime(root=root, scene=scene, dirty_hints=dirty_hints, bake=bake)
    finally:
        _RUNNING = False


def sync_all(root=None, scene=None, bake=False, target_fiber_ids=None):
    dirty = None
    if target_fiber_ids:
        dirty = dirty_hints_for("FIBER", target_fiber_ids)
    _run(root=root, scene=scene, dirty_hints=dirty, bake=bake)


def sync_from_dirty_hints(root=None, scene=None, dirty_hints=None, bake=False):
    _run(root=root, scene=scene, dirty_hints=dirty_hints, bake=bake)
