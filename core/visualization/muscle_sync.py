import bpy

from ..deps.dirty_hints import dirty_hints_for
from ..utils import get_af_root
from ..vcp.muscle_surface import (
    build_surface_data,
    validate_anchor_structure,
    prepare_surface_rows,
)
from .muscle_sync_helpers import (
    get_vis_collection,
    find_muscle_proxy,
    find_inflation_ctrl,
    create_muscle_proxy,
    create_inflation_ctrl,
    ensure_material,
    update_mesh,
    remove_proxy_obj,
    remove_ctrl_obj,
    nearest_on_mesh_surface,
    collect_fiber_props,
)
from .muscle_inflation import apply_inflation_from_ctrl
from .muscle_sync_runtime import collect_fiber_points, ensure_inflation_ctrl


class MuscleSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS"):
        self.collection_name = collection_name
        self._syncing = False

    def _get_vis_collection(self, scene):
        return get_vis_collection(scene, self.collection_name)

    def _find_muscle_proxy(self, vis_col, root_name, muscle_id, surface_type="BASE"):
        return find_muscle_proxy(vis_col, root_name, muscle_id, surface_type=surface_type)

    def _find_inflation_ctrl(self, vis_col, root_name, muscle_id):
        return find_inflation_ctrl(vis_col, root_name, muscle_id)

    def _create_muscle_proxy(self, vis_col, root, muscle_id, surface_type):
        return create_muscle_proxy(vis_col, root, muscle_id, surface_type)

    def _create_inflation_ctrl(self, vis_col, root, muscle_id):
        return create_inflation_ctrl(vis_col, root, muscle_id)

    def _ensure_material(self, obj, active=False):
        ensure_material(obj, active=active)

    def _update_mesh(self, obj, verts, faces):
        update_mesh(obj, verts, faces)

    def _collect_fiber_props(self, root, muscle):
        return collect_fiber_props(root, muscle)

    def _remove_proxy_obj(self, obj):
        remove_proxy_obj(obj)

    def _remove_ctrl_obj(self, obj):
        remove_ctrl_obj(obj)

    def _nearest_on_mesh_surface(self, mesh_obj, world_point):
        snapped = nearest_on_mesh_surface(mesh_obj, world_point)
        if snapped is None:
            return None, None
        return snapped, None

    def _ensure_inflation_ctrl(self, vis_col, root, muscle, base_obj, base_points):
        return ensure_inflation_ctrl(
            vis_col=vis_col,
            root=root,
            muscle=muscle,
            base_obj=base_obj,
            base_points=base_points,
            find_inflation_ctrl_fn=self._find_inflation_ctrl,
            create_inflation_ctrl_fn=self._create_inflation_ctrl,
            nearest_on_mesh_surface_fn=self._nearest_on_mesh_surface,
        )

    def _resolve_root_scene(self, root, scene):
        scene = scene or bpy.context.scene
        root = root or get_af_root(scene)
        if root is None or not hasattr(root, "af_vcp_system"):
            return None, None
        return root, scene

    def _muscle_ids_to_sync(self, vcp, target_muscle_ids):
        all_muscle_ids = {m.id for m in vcp.muscles}
        if target_muscle_ids is None:
            return all_muscle_ids, all_muscle_ids
        return all_muscle_ids, set(target_muscle_ids) & all_muscle_ids

    def _ensure_muscle_meshes(self, vis_col, root, muscle_id):
        base_obj = self._find_muscle_proxy(vis_col, root.name, muscle_id, "BASE")
        if base_obj is None:
            base_obj = self._create_muscle_proxy(vis_col, root, muscle_id, "BASE")
        infl_obj = self._find_muscle_proxy(vis_col, root.name, muscle_id, "INFL")
        if infl_obj is None:
            infl_obj = self._create_muscle_proxy(vis_col, root, muscle_id, "INFL")
        return base_obj, infl_obj

    def _set_muscle_active_materials(self, vcp, muscle_id, base_obj, infl_obj):
        active = (vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle_id)
        self._ensure_material(base_obj, active=active)
        self._ensure_material(infl_obj, active=active)

    def _clear_muscle_meshes(self, vcp, muscle_id, base_obj, infl_obj):
        self._update_mesh(base_obj, [], [])
        self._update_mesh(infl_obj, [], [])
        self._set_muscle_active_materials(vcp, muscle_id, base_obj, infl_obj)

    def _collect_points_with_fallback(self, root, scene, ordered_fibers):
        ordered_points = collect_fiber_points(root, scene, ordered_fibers)
        if ordered_points:
            return ordered_points
        # Route fallback updates through dependency runtime so downstream impacts
        # stay centralized in one scheduler.
        from .sync_runner import sync_from_dirty_hints
        sync_from_dirty_hints(
            root=root,
            scene=scene,
            dirty_hints=dirty_hints_for("FIBER", {f.id for f in ordered_fibers}),
            bake=False,
        )
        return collect_fiber_points(root, scene, ordered_fibers)

    def _build_surface(self, points, closed_v):
        try:
            verts, faces_raw, _n = build_surface_data(ordered_fiber_points=points, closed_v=bool(closed_v))
        except Exception:
            return None, None
        return verts, faces_raw

    def _sync_single_muscle(self, vis_col, root, scene, vcp, muscle):
        base_obj, infl_obj = self._ensure_muscle_meshes(vis_col, root, muscle.id)
        ordered_fibers, missing = self._collect_fiber_props(root, muscle)
        if missing or len(ordered_fibers) < 2:
            self._clear_muscle_meshes(vcp, muscle.id, base_obj, infl_obj)
            return
        ok, _reason, _node_count, _anchors = validate_anchor_structure(ordered_fibers)
        if not ok:
            self._clear_muscle_meshes(vcp, muscle.id, base_obj, infl_obj)
            return
        ordered_points = self._collect_points_with_fallback(root, scene, ordered_fibers)
        if not ordered_points:
            self._clear_muscle_meshes(vcp, muscle.id, base_obj, infl_obj)
            return
        base_points = prepare_surface_rows(ordered_points, int(ordered_fibers[0].node_count), densify_v=True)
        self._apply_muscle_surface(vis_col, root, vcp, muscle, base_obj, infl_obj, base_points)

    def _apply_muscle_surface(self, vis_col, root, vcp, muscle, base_obj, infl_obj, base_points):
        base_verts, faces_raw = self._build_surface(base_points, muscle.closed_v)
        if base_verts is None:
            self._clear_muscle_meshes(vcp, muscle.id, base_obj, infl_obj)
            return
        flip = bool(getattr(muscle, "flip_normals", False))
        faces_final = [(f[0], f[3], f[2], f[1]) for f in faces_raw] if flip else faces_raw
        self._update_mesh(base_obj, base_verts, faces_final)
        self._ensure_inflation_ctrl(vis_col, root, muscle, base_obj, base_points)
        infl_points = apply_inflation_from_ctrl(base_points, muscle)
        infl_verts, _faces_raw = self._build_surface(infl_points, muscle.closed_v)
        self._update_mesh(infl_obj, list(base_verts) if infl_verts is None else infl_verts, faces_final)
        self._set_muscle_active_materials(vcp, muscle.id, base_obj, infl_obj)

    def _cleanup_removed_muscles(self, vis_col, root_name, all_muscle_ids):
        for obj in list(vis_col.objects):
            if obj.get("af_root_name") != root_name:
                continue
            if obj.get("af_muscle_proxy") and obj.get("af_muscle_id") not in all_muscle_ids:
                self._remove_proxy_obj(obj)
            if obj.get("af_muscle_inflation_ctrl") and obj.get("af_muscle_id") not in all_muscle_ids:
                self._remove_ctrl_obj(obj)

    def sync_root_to_scene(self, root=None, scene=None, target_muscle_ids=None):
        if self._syncing:
            return

        root, scene = self._resolve_root_scene(root, scene)
        if root is None:
            return

        self._syncing = True
        try:
            vis_col = self._get_vis_collection(scene)
            vcp = root.af_vcp_system
            all_muscle_ids, muscle_ids_to_sync = self._muscle_ids_to_sync(vcp, target_muscle_ids)

            for muscle in vcp.muscles:
                if muscle.id not in muscle_ids_to_sync:
                    continue
                self._sync_single_muscle(vis_col, root, scene, vcp, muscle)

            self._cleanup_removed_muscles(vis_col, root.name, all_muscle_ids)

        finally:
            self._syncing = False

    def _is_relevant_inflation_update(self, root, vis_col, obj):
        if not isinstance(obj, bpy.types.Object):
            return False
        if not obj.get("af_muscle_inflation_ctrl"):
            return False
        if obj.get("af_root_name") != root.name:
            return False
        return vis_col.objects.get(obj.name) is not None

    def _find_muscle(self, root, muscle_id):
        return next((m for m in root.af_vcp_system.muscles if m.id == muscle_id), None)

    def _process_inflation_ctrl_update(self, root, vis_col, obj, changed_muscle_ids):
        muscle_id = obj.get("af_muscle_id")
        muscle = self._find_muscle(root, muscle_id)
        if muscle is None:
            return False
        base_obj = self._find_muscle_proxy(vis_col, root.name, muscle_id, "BASE")
        if base_obj is None:
            return False
        snapped, _n = self._nearest_on_mesh_surface(base_obj, obj.location.copy())
        if snapped is None:
            return False
        obj.location = snapped
        new_loc = (snapped.x, snapped.y, snapped.z)
        if tuple(muscle.inflation_ctrl_world) == new_loc:
            return False
        muscle.inflation_ctrl_world = new_loc
        changed_muscle_ids.add(muscle_id)
        return True

    def on_depsgraph_update(self, scene, depsgraph):
        if self._syncing:
            return

        root = get_af_root(scene)
        if root is None or not hasattr(root, "af_vcp_system"):
            return

        vis_col = bpy.data.collections.get(self.collection_name)
        if vis_col is None:
            return

        changed_muscle_ids = set()

        self._syncing = True
        try:
            for upd in depsgraph.updates:
                obj = upd.id
                if self._is_relevant_inflation_update(root, vis_col, obj):
                    self._process_inflation_ctrl_update(root, vis_col, obj, changed_muscle_ids)

        finally:
            self._syncing = False

        if changed_muscle_ids:
            from .sync_runner import sync_from_dirty_hints
            sync_from_dirty_hints(
                root=root,
                scene=scene,
                dirty_hints=dirty_hints_for("MUSCLE", changed_muscle_ids),
                source="depsgraph",
                event_type="TRANSFORM",
            )


_MUSCLE_SYNC = None


def register_muscle_sync():
    global _MUSCLE_SYNC
    if _MUSCLE_SYNC is None:
        _MUSCLE_SYNC = MuscleSceneSync()

    h = _MUSCLE_SYNC.on_depsgraph_update
    if h not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(h)

    return _MUSCLE_SYNC


def unregister_muscle_sync():
    global _MUSCLE_SYNC
    if _MUSCLE_SYNC is None:
        return

    h = _MUSCLE_SYNC.on_depsgraph_update
    if h in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(h)

    _MUSCLE_SYNC = None
