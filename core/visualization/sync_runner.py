import bpy

from ..utils import get_af_root
from .sync import register_sync
from .fiber_sync import register_fiber_sync
from .muscle_sync import register_muscle_sync
from .blob_sync import register_blob_sync
from .mirror_sync import register_mirror_sync


_RUNNING = False


def _affected_fibers_for_scps(root, scp_ids):
    scp_ids = set(scp_ids or [])
    if not scp_ids:
        return set()

    out = set()
    for f in root.af_vcp_system.fibers:
        if f.a_parent_id in scp_ids or f.b_parent_id in scp_ids:
            out.add(f.id)
            continue
        for tp in f.mid_touches:
            if tp.parent_id in scp_ids:
                out.add(f.id)
                break
    return out


def _affected_muscles_for_fibers(root, fiber_ids):
    fiber_ids = set(fiber_ids or [])
    if not fiber_ids:
        return set()

    out = set()
    for m in root.af_vcp_system.muscles:
        for ref in m.fiber_refs:
            if ref.fiber_id in fiber_ids:
                out.add(m.id)
                break
    return out


def _affected_blobs_for_scps(root, scp_ids):
    scp_ids = set(scp_ids or [])
    out = set()
    for b in root.af_vcp_system.blobs:
        if b.attach_target_type == "SCP" and b.attach_target_id in scp_ids:
            out.add(b.id)
    return out


def _affected_blobs_for_muscles(root, muscle_ids):
    muscle_ids = set(muscle_ids or [])
    out = set()
    for b in root.af_vcp_system.blobs:
        if b.attach_target_type == "MUSCLE" and b.attach_target_id in muscle_ids:
            out.add(b.id)
    return out


def sync_all(root=None, scene=None, bake=False, target_fiber_ids=None):
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
        register_fiber_sync().sync_root_to_scene(root=root, scene=scene, bake=bake, target_fiber_ids=target_fiber_ids)
        register_muscle_sync().sync_root_to_scene(root=root, scene=scene)
        register_blob_sync().sync_root_to_scene(root=root, scene=scene)
        register_mirror_sync().sync_root_to_scene(root=root, scene=scene)
    finally:
        _RUNNING = False


def sync_from_scp_ids(root=None, scene=None, scp_ids=None, bake=False):
    global _RUNNING
    if _RUNNING:
        return

    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if scene is None or root is None:
        return

    scp_ids = set(scp_ids or [])
    if not scp_ids:
        return

    fiber_ids = _affected_fibers_for_scps(root, scp_ids)
    muscle_ids = _affected_muscles_for_fibers(root, fiber_ids)
    blob_ids = _affected_blobs_for_scps(root, scp_ids) | _affected_blobs_for_muscles(root, muscle_ids)

    _RUNNING = True
    try:
        register_sync().sync_root_to_scene(root=root, scene=scene, target_scp_ids=scp_ids)

        if fiber_ids:
            register_fiber_sync().sync_root_to_scene(root=root, scene=scene, bake=bake, target_fiber_ids=fiber_ids)

        if muscle_ids:
            register_muscle_sync().sync_root_to_scene(root=root, scene=scene, target_muscle_ids=muscle_ids)

        if blob_ids:
            register_blob_sync().sync_root_to_scene(root=root, scene=scene, target_blob_ids=blob_ids)

        register_mirror_sync().sync_root_to_scene(root=root, scene=scene)
    finally:
        _RUNNING = False


def sync_from_fiber_ids(root=None, scene=None, fiber_ids=None, bake=False):
    global _RUNNING
    if _RUNNING:
        return

    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if scene is None or root is None:
        return

    fiber_ids = set(fiber_ids or [])
    if not fiber_ids:
        return

    muscle_ids = _affected_muscles_for_fibers(root, fiber_ids)
    blob_ids = _affected_blobs_for_muscles(root, muscle_ids)

    _RUNNING = True
    try:
        register_fiber_sync().sync_root_to_scene(root=root, scene=scene, bake=bake, target_fiber_ids=fiber_ids)

        if muscle_ids:
            register_muscle_sync().sync_root_to_scene(root=root, scene=scene, target_muscle_ids=muscle_ids)

        if blob_ids:
            register_blob_sync().sync_root_to_scene(root=root, scene=scene, target_blob_ids=blob_ids)

        register_mirror_sync().sync_root_to_scene(root=root, scene=scene)
    finally:
        _RUNNING = False


def sync_from_muscle_ids(root=None, scene=None, muscle_ids=None):
    global _RUNNING
    if _RUNNING:
        return

    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if scene is None or root is None:
        return

    muscle_ids = set(muscle_ids or [])
    if not muscle_ids:
        return

    blob_ids = _affected_blobs_for_muscles(root, muscle_ids)

    _RUNNING = True
    try:
        register_muscle_sync().sync_root_to_scene(root=root, scene=scene, target_muscle_ids=muscle_ids)

        if blob_ids:
            register_blob_sync().sync_root_to_scene(root=root, scene=scene, target_blob_ids=blob_ids)

        register_mirror_sync().sync_root_to_scene(root=root, scene=scene)
    finally:
        _RUNNING = False


def sync_from_blob_ids(root=None, scene=None, blob_ids=None):
    global _RUNNING
    if _RUNNING:
        return

    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if scene is None or root is None:
        return

    blob_ids = set(blob_ids or [])
    if not blob_ids:
        return

    _RUNNING = True
    try:
        register_blob_sync().sync_root_to_scene(root=root, scene=scene, target_blob_ids=blob_ids)
        register_mirror_sync().sync_root_to_scene(root=root, scene=scene)
    finally:
        _RUNNING = False
