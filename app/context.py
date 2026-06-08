from dataclasses import dataclass

import bpy

try:
    from ..core.utils import get_af_root
except ImportError:
    from core.utils import get_af_root


@dataclass(frozen=True)
class AddonContext:
    root: object = None
    scene: object = None
    depsgraph: object = None
    scheduler: object = None


def _active_scene():
    ctx = getattr(bpy, "context", None)
    return None if ctx is None else getattr(ctx, "scene", None)


def addon_context(root=None, scene=None, depsgraph=None, scheduler=None):
    scene = scene or _active_scene()
    root = root or get_af_root(scene)
    return AddonContext(root=root, scene=scene, depsgraph=depsgraph, scheduler=scheduler)


def context_from_blender(context=None, depsgraph=None, scheduler=None):
    scene = None if context is None else getattr(context, "scene", None)
    return addon_context(scene=scene, depsgraph=depsgraph, scheduler=scheduler)
