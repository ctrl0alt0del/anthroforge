import bpy

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

    def sync_root_to_scene(self, root=None, scene=None, target_muscle_ids=None):
        if self._syncing:
            return

        scene = scene or bpy.context.scene
        root = root or get_af_root(scene)
        if root is None or not hasattr(root, "af_vcp_system"):
            return

        self._syncing = True
        try:
            vis_col = self._get_vis_collection(scene)
            vcp = root.af_vcp_system

            all_muscle_ids = {m.id for m in vcp.muscles}
            if target_muscle_ids is None:
                muscle_ids_to_sync = all_muscle_ids
            else:
                muscle_ids_to_sync = set(target_muscle_ids) & all_muscle_ids

            for muscle in vcp.muscles:
                if muscle.id not in muscle_ids_to_sync:
                    continue

                base_obj = self._find_muscle_proxy(vis_col, root.name, muscle.id, "BASE")
                if base_obj is None:
                    base_obj = self._create_muscle_proxy(vis_col, root, muscle.id, "BASE")

                infl_obj = self._find_muscle_proxy(vis_col, root.name, muscle.id, "INFL")
                if infl_obj is None:
                    infl_obj = self._create_muscle_proxy(vis_col, root, muscle.id, "INFL")

                ordered_fibers, missing = self._collect_fiber_props(root, muscle)
                if missing or len(ordered_fibers) < 2:
                    self._update_mesh(base_obj, [], [])
                    self._update_mesh(infl_obj, [], [])
                    active = (vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id)
                    self._ensure_material(base_obj, active=active)
                    self._ensure_material(infl_obj, active=active)
                    continue

                ok, _reason, _node_count, _anchors = validate_anchor_structure(ordered_fibers)
                if not ok:
                    self._update_mesh(base_obj, [], [])
                    self._update_mesh(infl_obj, [], [])
                    active = (vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id)
                    self._ensure_material(base_obj, active=active)
                    self._ensure_material(infl_obj, active=active)
                    continue

                ordered_points = collect_fiber_points(root, scene, ordered_fibers)
                if not ordered_points:
                    from .fiber_sync import register_fiber_sync
                    register_fiber_sync().sync_root_to_scene(
                        root=root,
                        scene=scene,
                        bake=False,
                        target_fiber_ids={f.id for f in ordered_fibers},
                    )
                    ordered_points = collect_fiber_points(root, scene, ordered_fibers)

                if not ordered_points:
                    self._update_mesh(base_obj, [], [])
                    self._update_mesh(infl_obj, [], [])
                    active = (vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id)
                    self._ensure_material(base_obj, active=active)
                    self._ensure_material(infl_obj, active=active)
                    continue

                base_points = prepare_surface_rows(
                    ordered_fiber_points=ordered_points,
                    target_n=int(ordered_fibers[0].node_count),
                    densify_v=True,
                )

                try:
                    base_verts, faces_raw, _n = build_surface_data(
                        ordered_fiber_points=base_points,
                        closed_v=bool(muscle.closed_v),
                    )
                except Exception:
                    self._update_mesh(base_obj, [], [])
                    self._update_mesh(infl_obj, [], [])
                    active = (vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id)
                    self._ensure_material(base_obj, active=active)
                    self._ensure_material(infl_obj, active=active)
                    continue

                flip = bool(getattr(muscle, "flip_normals", False))
                faces_final = [(f[0], f[3], f[2], f[1]) for f in faces_raw] if flip else faces_raw

                self._update_mesh(base_obj, base_verts, faces_final)
                self._ensure_inflation_ctrl(vis_col, root, muscle, base_obj, base_points)
                infl_points = apply_inflation_from_ctrl(base_points, muscle)

                try:
                    infl_verts, _faces_raw2, _n2 = build_surface_data(
                        ordered_fiber_points=infl_points,
                        closed_v=bool(muscle.closed_v),
                    )
                except Exception:
                    infl_verts = list(base_verts)

                self._update_mesh(infl_obj, infl_verts, faces_final)

                active = (vcp.active_vcp_type == "MUSCLE" and vcp.active_vcp_id == muscle.id)
                self._ensure_material(base_obj, active=active)
                self._ensure_material(infl_obj, active=active)

            if target_muscle_ids is None:
                for obj in list(vis_col.objects):
                    if obj.get("af_root_name") != root.name:
                        continue

                    if obj.get("af_muscle_proxy") and obj.get("af_muscle_id") not in all_muscle_ids:
                        self._remove_proxy_obj(obj)
                        continue

                    if obj.get("af_muscle_inflation_ctrl") and obj.get("af_muscle_id") not in all_muscle_ids:
                        self._remove_ctrl_obj(obj)
                        continue

        finally:
            self._syncing = False

    def on_depsgraph_update(self, scene, depsgraph):
        if self._syncing:
            return

        root = get_af_root(scene)
        if root is None or not hasattr(root, "af_vcp_system"):
            return

        vis_col = bpy.data.collections.get(self.collection_name)
        if vis_col is None:
            return

        changed = False
        changed_muscle_ids = set()

        self._syncing = True
        try:
            for upd in depsgraph.updates:
                obj = upd.id
                if not isinstance(obj, bpy.types.Object):
                    continue
                if not obj.get("af_muscle_inflation_ctrl"):
                    continue
                if obj.get("af_root_name") != root.name:
                    continue
                if vis_col.objects.get(obj.name) is None:
                    continue

                muscle_id = obj.get("af_muscle_id")
                muscle = next((m for m in root.af_vcp_system.muscles if m.id == muscle_id), None)
                if muscle is None:
                    continue

                base_obj = self._find_muscle_proxy(vis_col, root.name, muscle_id, "BASE")
                if base_obj is None:
                    continue

                snapped, _n = self._nearest_on_mesh_surface(base_obj, obj.location.copy())
                if snapped is None:
                    continue

                obj.location = snapped
                new_loc = (snapped.x, snapped.y, snapped.z)
                if tuple(muscle.inflation_ctrl_world) != new_loc:
                    muscle.inflation_ctrl_world = new_loc
                    changed = True
                    changed_muscle_ids.add(muscle_id)

        finally:
            self._syncing = False

        if changed and changed_muscle_ids:
            from .sync_runner import sync_from_muscle_ids
            sync_from_muscle_ids(root=root, scene=scene, muscle_ids=changed_muscle_ids)


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
