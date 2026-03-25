import bpy

from ..utils import get_af_root
from ..deps import run_dependency_runtime


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
        dirty = {"SCP": set(), "FIBER": set(target_fiber_ids), "MUSCLE": set(), "BLOB": set()}
    _run(root=root, scene=scene, dirty_hints=dirty, bake=bake)


def sync_from_scp_ids(root=None, scene=None, scp_ids=None, bake=False):
    _run(
        root=root,
        scene=scene,
        dirty_hints={"SCP": set(scp_ids or []), "FIBER": set(), "MUSCLE": set(), "BLOB": set()},
        bake=bake,
    )


def sync_from_fiber_ids(root=None, scene=None, fiber_ids=None, bake=False):
    _run(
        root=root,
        scene=scene,
        dirty_hints={"SCP": set(), "FIBER": set(fiber_ids or []), "MUSCLE": set(), "BLOB": set()},
        bake=bake,
    )


def sync_from_muscle_ids(root=None, scene=None, muscle_ids=None):
    _run(
        root=root,
        scene=scene,
        dirty_hints={"SCP": set(), "FIBER": set(), "MUSCLE": set(muscle_ids or []), "BLOB": set()},
        bake=False,
    )


def sync_from_blob_ids(root=None, scene=None, blob_ids=None):
    _run(
        root=root,
        scene=scene,
        dirty_hints={"SCP": set(), "FIBER": set(), "MUSCLE": set(), "BLOB": set(blob_ids or [])},
        bake=False,
    )

