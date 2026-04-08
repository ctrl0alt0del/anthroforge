import bpy

from ..utils import get_af_root
from ..deps.dirty_hints import empty_dirty_hints
from .mirror_rules import (
    explicit_mirror_rule_for_scp,
    effective_rule_for_scp,
    effective_rule_for_fiber,
    effective_rule_for_muscle,
    axis_index,
    intersects_mirror_plane,
)
from .mirror_objects import (
    get_collection,
    scp_prop_map,
    fiber_prop_map,
    find_source_scp_obj,
    find_source_fiber_obj,
    find_source_muscle_obj,
    find_mirror_scp_obj,
    find_mirror_fiber_obj,
    find_mirror_muscle_obj,
    remove_obj,
    ensure_obj_type,
    create_mirror_from_source,
    copy_data,
    ensure_mirror_material,
)
from .mirror_passes import sync_scp_mirrors, sync_fiber_mirrors, sync_muscle_mirrors


class AFMirrorSync:
    def __init__(self, scp_collection_name="AF_VIS", vcp_collection_name="AF_VCP_VIS"):
        self.scp_collection_name = scp_collection_name
        self.vcp_collection_name = vcp_collection_name
        self._syncing = False

    def _get_collection(self, scene, name):
        return get_collection(scene, name)

    def _scp_prop_map(self, root):
        return scp_prop_map(root)

    def _fiber_prop_map(self, root):
        return fiber_prop_map(root)

    def _explicit_mirror_rule_for_scp(self, scp_prop):
        return explicit_mirror_rule_for_scp(scp_prop)

    def _effective_rule_for_scp(self, scp_id, scp_map):
        return effective_rule_for_scp(scp_id, scp_map)

    def _effective_rule_for_fiber(self, fiber_prop, scp_map):
        return effective_rule_for_fiber(fiber_prop, scp_map)

    def _effective_rule_for_muscle(self, muscle_prop, fibers_by_id, scp_map):
        return effective_rule_for_muscle(muscle_prop, fibers_by_id, scp_map)

    def _axis_index(self, axis):
        return axis_index(axis)

    def _intersects_mirror_plane(self, obj, axis="X", origin=(0.0, 0.0, 0.0), eps=1e-6):
        return intersects_mirror_plane(obj, axis=axis, origin=origin, eps=eps)

    def _find_source_scp_obj(self, scp_col, root_name, scp_id):
        return find_source_scp_obj(scp_col, root_name, scp_id)

    def _find_source_fiber_obj(self, vcp_col, root_name, fiber_id):
        return find_source_fiber_obj(vcp_col, root_name, fiber_id)

    def _find_source_muscle_obj(self, vcp_col, root_name, muscle_id, surface):
        return find_source_muscle_obj(vcp_col, root_name, muscle_id, surface)

    def _find_mirror_scp_obj(self, scp_col, root_name, source_scp_id):
        return find_mirror_scp_obj(scp_col, root_name, source_scp_id)

    def _find_mirror_fiber_obj(self, vcp_col, root_name, source_fiber_id):
        return find_mirror_fiber_obj(vcp_col, root_name, source_fiber_id)

    def _find_mirror_muscle_obj(self, vcp_col, root_name, source_muscle_id, surface):
        return find_mirror_muscle_obj(vcp_col, root_name, source_muscle_id, surface)

    def _remove_obj(self, obj):
        return remove_obj(obj)

    def _ensure_obj_type(self, obj, src_obj):
        return ensure_obj_type(obj, src_obj)

    def _create_mirror_from_source(self, collection, src_obj, name):
        return create_mirror_from_source(collection, src_obj, name)

    def _copy_data(self, src_obj, dst_obj):
        return copy_data(src_obj, dst_obj)

    def _ensure_mirror_material(self, obj, alpha_mult=0.35):
        return ensure_mirror_material(obj, alpha_mult=alpha_mult)

    def _sync_scp_mirrors(self, root, scene, scp_col, scp_map):
        return sync_scp_mirrors(self, root, scene, scp_col, scp_map)

    def _sync_fiber_mirrors(self, root, vcp_col, scp_map, fibers_by_id):
        return sync_fiber_mirrors(self, root, vcp_col, scp_map, fibers_by_id)

    def _sync_muscle_mirrors(self, root, vcp_col, scp_map, fibers_by_id):
        return sync_muscle_mirrors(self, root, vcp_col, scp_map, fibers_by_id)

    def sync_root_to_scene(self, root=None, scene=None):
        if self._syncing:
            return

        scene = scene or bpy.context.scene
        root = root or get_af_root(scene)
        if root is None:
            return

        self._syncing = True
        try:
            scp_col = self._get_collection(scene, self.scp_collection_name)
            vcp_col = self._get_collection(scene, self.vcp_collection_name)

            scp_map = self._scp_prop_map(root)
            fibers_by_id = self._fiber_prop_map(root)

            self._sync_scp_mirrors(root, scene, scp_col, scp_map)
            self._sync_fiber_mirrors(root, vcp_col, scp_map, fibers_by_id)
            self._sync_muscle_mirrors(root, vcp_col, scp_map, fibers_by_id)
        finally:
            self._syncing = False

    def _is_relevant_update_obj(self, root, obj):
        if not isinstance(obj, bpy.types.Object):
            return False
        if obj.get("af_root_name") != root.name:
            return False
        if obj.get("af_proxy") and not obj.get("af_mirror_proxy"):
            return True
        if obj.get("af_fiber_proxy") and not obj.get("af_fiber_mirror_proxy"):
            return True
        if obj.get("af_muscle_proxy") and not obj.get("af_muscle_mirror_proxy"):
            return True
        return bool(obj.get("af_muscle_inflation_ctrl"))

    def _has_relevant_updates(self, root, depsgraph):
        for upd in depsgraph.updates:
            if self._is_relevant_update_obj(root, upd.id):
                return True
        return False

    def _collect_dirty_hints(self, root, depsgraph):
        dirty = empty_dirty_hints()
        unresolved = False

        for upd in depsgraph.updates:
            obj = upd.id
            if not self._is_relevant_update_obj(root, obj):
                continue

            if obj.get("af_proxy") and not obj.get("af_mirror_proxy"):
                sid = obj.get("af_scp_id")
                if sid:
                    dirty["SCP"].add(str(sid))
                else:
                    unresolved = True
                continue

            if obj.get("af_fiber_proxy") and not obj.get("af_fiber_mirror_proxy"):
                fid = obj.get("af_fiber_id")
                if fid:
                    dirty["FIBER"].add(str(fid))
                else:
                    unresolved = True
                continue

            if obj.get("af_muscle_proxy") and not obj.get("af_muscle_mirror_proxy"):
                mid = obj.get("af_muscle_id")
                if mid:
                    dirty["MUSCLE"].add(str(mid))
                else:
                    unresolved = True
                continue

            if obj.get("af_muscle_inflation_ctrl"):
                mid = obj.get("af_muscle_id")
                if mid:
                    dirty["MUSCLE"].add(str(mid))
                else:
                    unresolved = True

        has_any = any(bool(v) for v in dirty.values())
        return dirty if has_any and not unresolved else None

    def on_depsgraph_update(self, scene, depsgraph):
        if self._syncing:
            return

        root = get_af_root(scene)
        if root is None:
            return

        if self._has_relevant_updates(root, depsgraph):
            # Use dependency runtime as the single scheduler for all update paths.
            from .sync_runner import sync_all, sync_from_dirty_hints

            dirty = self._collect_dirty_hints(root, depsgraph)
            if dirty is None:
                sync_all(root=root, scene=scene, bake=False)
            else:
                sync_from_dirty_hints(root=root, scene=scene, dirty_hints=dirty, bake=False)


_MIRROR_SYNC = None


def register_mirror_sync():
    global _MIRROR_SYNC
    if _MIRROR_SYNC is None:
        _MIRROR_SYNC = AFMirrorSync()

    h = _MIRROR_SYNC.on_depsgraph_update
    if h not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(h)

    return _MIRROR_SYNC


def unregister_mirror_sync():
    global _MIRROR_SYNC
    if _MIRROR_SYNC is None:
        return

    h = _MIRROR_SYNC.on_depsgraph_update
    if h in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(h)

    _MIRROR_SYNC = None
