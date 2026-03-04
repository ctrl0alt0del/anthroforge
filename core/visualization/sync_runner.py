import bpy

from ..utils import get_af_root
from .sync import register_sync
from .fiber_sync import register_fiber_sync
from .muscle_sync import register_muscle_sync
from .mirror_sync import register_mirror_sync


_RUNNING = False


def sync_all(root=None, scene=None, bake=False, target_fiber_ids=None):
    """
    Single orchestration point for all visual sync.
    Order matters:
    1) SCP proxies
    2) Fiber proxies
    3) Muscle proxies
    4) Mirror pass (depends on all source proxies)
    """
    global _RUNNING
    if _RUNNING:
        return

    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if scene is None or root is None:
        return

    _RUNNING = True
    try:
        register_sync().sync_root_to_scene(root=root, scene=scene)
        register_fiber_sync().sync_root_to_scene(
            root=root,
            scene=scene,
            bake=bake,
            target_fiber_ids=target_fiber_ids,
        )
        register_muscle_sync().sync_root_to_scene(root=root, scene=scene)
        register_mirror_sync().sync_root_to_scene(root=root, scene=scene)
    finally:
        _RUNNING = False
