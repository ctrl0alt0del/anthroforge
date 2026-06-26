import bpy

from ..deps.dirty_hints import dirty_hints_for
from ..deps.controls import classify_control_object, enqueue_control_intent
from ..deps.conflict_resolver import resolve_conflict
from ..utils import get_af_root, scene_for_id
from ..vcp.runtime_state import muscle_inflation_ctrl_world, set_muscle_inflation_ctrl_world
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
from .muscle_inflation_modes import muscle_inflation_behavior, uses_inflation_control
from .muscle_sync_runtime import collect_fiber_points, ensure_inflation_ctrl
from .control_runtime import active_entity_id


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

    def _remove_inflation_ctrl_for_muscle(self, vis_col, root_name, muscle_id):
        ctrl = self._find_inflation_ctrl(vis_col, root_name, muscle_id)
        if ctrl is not None:
            self._remove_ctrl_obj(ctrl)

    def _inflation_behavior(self, muscle):
        return muscle_inflation_behavior(muscle)

    def _uses_inflation_control(self, muscle):
        return uses_inflation_control(muscle)

    def _resolve_root_scene(self, root, scene):
        scene = scene or scene_for_id(root)
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

    def _surface_base_points(self, root, scene, ordered_fibers, missing):
        if missing or len(ordered_fibers) < 2:
            return None
        ok, _reason, _count, _anchors = validate_anchor_structure(ordered_fibers)
        if not ok:
            return None
        points = self._collect_points_with_fallback(root, scene, ordered_fibers)
        if not points:
            return None
        return prepare_surface_rows(points, int(ordered_fibers[0].node_count), densify_v=True)

    def _surface_mesh_data(self, base_points, muscle):
        base_verts, faces_raw = self._build_surface(base_points, muscle.closed_v)
        if base_verts is None:
            return None
        flip = bool(getattr(muscle, "flip_normals", False))
        faces = [(f[0], f[3], f[2], f[1]) for f in faces_raw] if flip else faces_raw
        return base_verts, faces

    def _inflated_surface_verts(self, base_points, muscle):
        infl_points = self._inflation_behavior(muscle).field.inflate(base_points, muscle)
        infl_verts, _faces_raw = self._build_surface(infl_points, muscle.closed_v)
        return infl_verts

    def _sync_inflation_control(self, vis_col, root, muscle, base_obj, base_points, ensure_control):
        control = self._inflation_behavior(muscle).control
        if ensure_control:
            return control.ensure_control(self, vis_col, root, muscle, base_obj, base_points)
        return control.cleanup_controls(self, vis_col, root, muscle)

    def _sync_single_muscle(self, vis_col, root, scene, vcp, muscle):
        base_obj, infl_obj = self._ensure_muscle_meshes(vis_col, root, muscle.id)
        ordered_fibers, missing = self._collect_fiber_props(root, muscle)
        base_points = self._surface_base_points(root, scene, ordered_fibers, missing)
        if base_points is None:
            self._clear_muscle_meshes(vcp, muscle.id, base_obj, infl_obj)
            return
        self._apply_synced_surface(vis_col, root, scene, vcp, muscle, base_obj, infl_obj, base_points)

    def _apply_synced_surface(self, vis_col, root, scene, vcp, muscle, base_obj, infl_obj, base_points):
        ensure = self._selected_muscle_id(vcp, root, scene) == muscle.id
        self._apply_muscle_surface(vis_col, root, vcp, muscle, base_obj, infl_obj, base_points, ensure)

    def _apply_muscle_surface(self, vis_col, root, vcp, muscle, base_obj, infl_obj, base_points, ensure_control):
        surface = self._surface_mesh_data(base_points, muscle)
        if surface is None:
            self._clear_muscle_meshes(vcp, muscle.id, base_obj, infl_obj)
            return
        base_verts, faces_final = surface
        self._update_mesh(base_obj, base_verts, faces_final)
        self._sync_inflation_control(vis_col, root, muscle, base_obj, base_points, ensure_control)
        infl_verts = self._inflated_surface_verts(base_points, muscle)
        self._update_mesh(infl_obj, list(base_verts) if infl_verts is None else infl_verts, faces_final)
        self._set_muscle_active_materials(vcp, muscle.id, base_obj, infl_obj)

    def _active_muscle_id(self, root, scene=None, active_object=None):
        return active_entity_id(root, "MUSCLE", scene, active_object)

    def _selected_muscle_id(self, vcp, root, scene):
        active_id = self._active_muscle_id(root, scene)
        if active_id:
            return active_id
        is_muscle = str(getattr(vcp, "active_vcp_type", "NONE") or "NONE") == "MUSCLE"
        return str(getattr(vcp, "active_vcp_id", "") or "") if is_muscle else ""

    def _cleanup_inactive_muscle_controls(self, vis_col, root_name, active_muscle_id, control_muscle_ids):
        for obj in list(vis_col.objects):
            if not obj.get("af_muscle_inflation_ctrl"):
                continue
            if obj.get("af_root_name") != root_name:
                continue
            muscle_id = obj.get("af_muscle_id")
            if muscle_id not in control_muscle_ids:
                self._remove_ctrl_obj(obj)
                continue
            if active_muscle_id and muscle_id == active_muscle_id:
                continue
            self._remove_ctrl_obj(obj)

    def _control_muscle_ids(self, vcp):
        return {muscle.id for muscle in vcp.muscles if self._uses_inflation_control(muscle)}

    def _sync_target_muscles(self, vis_col, root, scene, vcp, muscle_ids_to_sync):
        for muscle in vcp.muscles:
            if muscle.id in muscle_ids_to_sync:
                self._sync_single_muscle(vis_col, root, scene, vcp, muscle)

    def _cleanup_after_sync(self, vis_col, root, all_muscle_ids, active_muscle_id, control_muscle_ids):
        self._cleanup_removed_muscles(vis_col, root.name, all_muscle_ids)
        self._cleanup_inactive_muscle_controls(vis_col, root.name, active_muscle_id, control_muscle_ids)

    def _sync_root_pass(self, root, scene, target_muscle_ids):
        vis_col = self._get_vis_collection(scene)
        vcp = root.af_vcp_system
        all_ids, target_ids = self._muscle_ids_to_sync(vcp, target_muscle_ids)
        active_id = self._selected_muscle_id(vcp, root, scene)
        control_ids = self._control_muscle_ids(vcp)
        self._sync_target_muscles(vis_col, root, scene, vcp, target_ids)
        self._cleanup_after_sync(vis_col, root, all_ids, active_id, control_ids)

    def _cleanup_removed_muscles(self, vis_col, root_name, all_muscle_ids):
        for obj in list(vis_col.objects):
            obj_root, muscle_id, is_proxy, is_ctrl = self._cleanup_tags(obj)
            if obj_root != root_name:
                continue
            if is_proxy and muscle_id not in all_muscle_ids:
                self._remove_proxy_obj(obj)
            if is_ctrl and muscle_id not in all_muscle_ids:
                self._remove_ctrl_obj(obj)

    def _cleanup_tags(self, obj):
        return (
            self._ctrl_prop(obj, "af_root_name"),
            self._ctrl_prop(obj, "af_muscle_id"),
            bool(self._ctrl_prop(obj, "af_muscle_proxy")),
            bool(self._ctrl_prop(obj, "af_muscle_inflation_ctrl")),
        )

    def sync_root_to_scene(self, root=None, scene=None, target_muscle_ids=None):
        if self._syncing:
            return

        root, scene = self._resolve_root_scene(root, scene)
        if root is None:
            return

        self._syncing = True
        try:
            self._sync_root_pass(root, scene, target_muscle_ids)
        finally:
            self._syncing = False

    def _is_relevant_inflation_update(self, root, vis_col, obj):
        if not isinstance(obj, bpy.types.Object):
            return False
        if not self._ctrl_prop(obj, "af_muscle_inflation_ctrl"):
            return False
        if self._ctrl_prop(obj, "af_root_name") != root.name:
            return False
        return vis_col.objects.get(obj.name) is not None

    def _find_muscle(self, root, muscle_id):
        return next((m for m in root.af_vcp_system.muscles if m.id == muscle_id), None)

    def _ctrl_prop(self, obj, key):
        try:
            return obj.get(key)
        except ReferenceError:
            return None

    def _ctrl_location(self, obj):
        try:
            return obj.location.copy()
        except ReferenceError:
            return None

    def _set_ctrl_location(self, obj, value):
        try:
            obj.location = value
        except ReferenceError:
            return False
        return True

    def _inflation_target(self, root, vis_col, obj):
        muscle_id = self._ctrl_prop(obj, "af_muscle_id")
        muscle = self._find_muscle(root, muscle_id)
        if muscle is None:
            return None, None, None
        base_obj = self._find_muscle_proxy(vis_col, root.name, muscle_id, "BASE")
        return muscle_id, muscle, base_obj

    def _snapped_ctrl_location(self, base_obj, obj):
        target = self._ctrl_location(obj)
        if target is None:
            return None
        snapped, _n = self._nearest_on_mesh_surface(base_obj, target)
        if snapped is None or not self._set_ctrl_location(obj, snapped):
            return None
        return snapped

    def _resolved_ctrl_world(self, muscle_id, muscle, incoming):
        resolved = resolve_conflict(entity_type="MUSCLE", entity_id=str(muscle_id or ""), aspect="inflation.ctrl_world", source="blender_control", current=muscle_inflation_ctrl_world(muscle), incoming=incoming, payload={"control": "inflation"})
        try:
            return float(resolved[0]), float(resolved[1]), float(resolved[2])
        except Exception:
            return incoming

    def _process_ctrl_point_update(self, root, vis_col, obj, changed_muscle_ids):
        muscle_id, muscle, base_obj = self._inflation_target(root, vis_col, obj)
        if base_obj is None:
            return False
        snapped = self._snapped_ctrl_location(base_obj, obj)
        if snapped is None:
            return False
        new_loc = self._resolved_ctrl_world(muscle_id, muscle, (snapped.x, snapped.y, snapped.z))
        if muscle_inflation_ctrl_world(muscle) == tuple(new_loc):
            return False
        set_muscle_inflation_ctrl_world(muscle, tuple(new_loc))
        changed_muscle_ids.add(muscle_id)
        return True

    def _process_inflation_ctrl_update(self, root, vis_col, obj, changed_muscle_ids):
        muscle_id = self._ctrl_prop(obj, "af_muscle_id")
        muscle = self._find_muscle(root, muscle_id)
        if muscle is None:
            return False
        control = self._inflation_behavior(muscle).control
        return control.process_control_update(self, root, vis_col, obj, changed_muscle_ids)

    def _depsgraph_ready(self, scene):
        root = get_af_root(scene)
        vis_col = bpy.data.collections.get(self.collection_name)
        if root is None or not hasattr(root, "af_vcp_system") or vis_col is None:
            return None, None
        return root, vis_col

    def _sync_depsgraph_changes(self, root, scene, changed_muscle_ids):
        from .sync_runner import sync_from_dirty_hints
        sync_from_dirty_hints(
            root=root,
            scene=scene,
            dirty_hints=dirty_hints_for("MUSCLE", changed_muscle_ids),
            source="depsgraph",
            event_type="TRANSFORM",
        )

    def _collect_one_depsgraph_update(self, root, vis_col, obj, changed_muscle_ids):
        if not self._is_relevant_inflation_update(root, vis_col, obj):
            return
        classified = classify_control_object(obj)
        if not classified or str(classified["control_type"]) != "MUSCLE_INFLATION":
            return
        payload = dict(classified["payload"])
        payload["binding"] = classified.get("binding")
        if enqueue_control_intent(root, classified["control_type"], payload):
            changed_muscle_ids |= set(classified["dirty_hints"].get("MUSCLE", set()) or set())

    def _collect_depsgraph_updates(self, root, vis_col, depsgraph):
        changed = set()
        self._syncing = True
        try:
            for upd in depsgraph.updates:
                self._collect_one_depsgraph_update(root, vis_col, upd.id, changed)
        finally:
            self._syncing = False
        return changed

    def on_depsgraph_update(self, scene, depsgraph):
        if self._syncing:
            return
        root, vis_col = self._depsgraph_ready(scene)
        if root is None:
            return
        changed_muscle_ids = self._collect_depsgraph_updates(root, vis_col, depsgraph)
        if changed_muscle_ids:
            self._sync_depsgraph_changes(root, scene, changed_muscle_ids)


def apply_muscle_control_update(sync, root, scene, obj):
    vis_col = bpy.data.collections.get(sync.collection_name)
    if vis_col is None:
        return None
    changed = set()
    sync._process_inflation_ctrl_update(root, vis_col, obj, changed)
    return next(iter(changed), None)


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
