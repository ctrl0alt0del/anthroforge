import bpy

def create_root_if_missing(scene, objects, create_root_fn, sync_fn, dirty_hints_fn):
    if "AF_ROOT" in objects:
        return None
    root = create_root_fn(scene)
    sync_fn(root=root, scene=scene, dirty_hints=dirty_hints_fn())
    return root


def run_create_root(scene):
    return create_root_if_missing(scene, bpy.data.objects, _create_root(), _sync_scene(), _empty_dirty_hints())


def _create_root():
    try:
        from ...core.utils import create_af_root
    except ImportError:
        from core.utils import create_af_root
    return create_af_root


def _sync_scene():
    try:
        from ...app.runtime_api import sync_scene
    except ImportError:
        from app.runtime_api import sync_scene
    return sync_scene


def _empty_dirty_hints():
    try:
        from ...core.deps.dirty_hints import empty_dirty_hints
    except ImportError:
        from core.deps.dirty_hints import empty_dirty_hints
    return empty_dirty_hints
