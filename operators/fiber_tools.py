import json
import bpy
import time

from ..core.utils import get_af_root
from ..core.registry import SCPRegistry
from ..core.deps.dirty_hints import dirty_hints_for
from ..core.visualization.fiber_sync import register_fiber_sync
from ..core.visualization.sync_runner import sync_from_dirty_hints


class AF_OT_ClearFiberWarmStart(bpy.types.Operator):
    bl_idname = "af.clear_fiber_warm_start"
    bl_label = "Clear Warm Start"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        vcp = root.af_vcp_system
        target_id = self.fiber_id or vcp.active_vcp_id
        if not target_id:
            self.report({"ERROR"}, "No active fiber.")
            return {"CANCELLED"}

        fiber = None
        for f in vcp.fibers:
            if f.id == target_id:
                fiber = f
                break
        if fiber is None:
            self.report({"ERROR"}, "Fiber not found.")
            return {"CANCELLED"}

        sync = register_fiber_sync()
        sync.clear_solver_cache(fiber.id)

        fiber.last_recompute_status = "UNKNOWN"
        fiber.last_recompute_ms = 0.0
        fiber.last_eps_disp = 0.0
        fiber.last_eps_pen = 0.0

        self.report({"INFO"}, f"Warm-start cache cleared for {fiber.id}")
        return {"FINISHED"}


class AF_OT_RecomputeFiber(bpy.types.Operator):
    bl_idname = "af.recompute_fiber"
    bl_label = "Recompute Fiber"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def _find_target_fiber(self, root):
        vcp = root.af_vcp_system
        target_id = self.fiber_id or vcp.active_vcp_id
        if not target_id:
            return None
        for f in vcp.fibers:
            if f.id == target_id:
                return f
        return None

    def _run_bake_passes(self, root, scene, fiber, max_passes):
        for _ in range(max_passes):
            sync_from_dirty_hints(
                root=root,
                scene=scene,
                dirty_hints=dirty_hints_for("FIBER", {fiber.id}),
                bake=True,
            )
            if not fiber.not_converged:
                return True
        return False

    def _set_prefer_bake(self, fiber):
        try:
            fiber["af_prefer_bake"] = True
        except Exception:
            pass

    def _update_recompute_stats(self, fiber, elapsed_ms, converged):
        fiber.last_recompute_ms = elapsed_ms
        fiber.last_recompute_status = "CONVERGED" if converged else "NOT_CONVERGED"

    def execute(self, context):
        t0 = time.perf_counter()

        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        fiber = self._find_target_fiber(root)
        if fiber is None:
            self.report({"ERROR"}, "Target fiber not found.")
            return {"CANCELLED"}

        max_passes = 60
        converged = self._run_bake_passes(root, context.scene, fiber, max_passes)
        self._set_prefer_bake(fiber)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self._update_recompute_stats(fiber, elapsed_ms, converged)
        if converged:
            self.report({"INFO"}, f"Fiber {fiber.id} converged")
        else:
            self.report({"WARNING"}, f"Fiber {fiber.id} not converged after {max_passes} passes")
        return {"FINISHED"}


class AF_OT_AddFiberTouchPoint(bpy.types.Operator):
    bl_idname = "af.add_fiber_touch_point"
    bl_label = "Add Mid Touch Point"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def _resolve_touch_parent_id(self, context, root):
        obj = context.active_object
        if obj and obj.get("af_proxy") and obj.get("af_root_name") == root.name:
            return obj.get("af_scp_id", "")
        idx = root.af_scp_system.active_scp_index
        if 0 <= idx < len(root.af_scp_system.scps):
            return root.af_scp_system.scps[idx].id
        return ""

    def _first_attach_param(self, root, scp_id):
        runtime = SCPRegistry(root)
        runtime.build()
        parent = runtime.registry.get(scp_id)
        if parent is None:
            return None
        params = parent.shape.get_attach_params()
        return params[0] if params else 0.0

    def _mark_interactive_preferred(self, fiber):
        try:
            fiber["af_prefer_bake"] = False
        except Exception:
            pass

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        vcp = root.af_vcp_system
        target_id = self.fiber_id or vcp.active_vcp_id
        fiber = next((f for f in vcp.fibers if f.id == target_id), None)
        if fiber is None:
            self.report({"ERROR"}, "Fiber not found.")
            return {"CANCELLED"}
        scp_id = self._resolve_touch_parent_id(context, root)
        if not scp_id:
            self.report({"ERROR"}, "Select an SCP in viewport or SCP tree first.")
            return {"CANCELLED"}
        p = self._first_attach_param(root, scp_id)
        if p is None:
            self.report({"ERROR"}, "Selected SCP not found in runtime registry.")
            return {"CANCELLED"}

        tp = fiber.mid_touches.add()
        tp.parent_id = scp_id
        tp.attach_param = json.dumps(p)
        self._mark_interactive_preferred(fiber)
        sync = register_fiber_sync()
        sync.clear_solver_cache(fiber.id)
        sync_from_dirty_hints(
            root=root,
            scene=context.scene,
            dirty_hints=dirty_hints_for("FIBER", {fiber.id}),
            bake=False,
        )
        return {"FINISHED"}


class AF_OT_RemoveFiberTouchPoint(bpy.types.Operator):
    bl_idname = "af.remove_fiber_touch_point"
    bl_label = "Remove Mid Touch Point"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")
    touch_index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        vcp = root.af_vcp_system
        target_id = self.fiber_id or vcp.active_vcp_id
        fiber = next((f for f in vcp.fibers if f.id == target_id), None)
        if fiber is None:
            self.report({"ERROR"}, "Fiber not found.")
            return {"CANCELLED"}

        idx = int(self.touch_index)
        if idx < 0 or idx >= len(fiber.mid_touches):
            self.report({"ERROR"}, "Invalid touch index.")
            return {"CANCELLED"}

        fiber.mid_touches.remove(idx)

        try:
            fiber["af_prefer_bake"] = False
        except Exception:
            pass

        sync = register_fiber_sync()
        sync.clear_solver_cache(fiber.id)
        sync_from_dirty_hints(
            root=root,
            scene=context.scene,
            dirty_hints=dirty_hints_for("FIBER", {fiber.id}),
            bake=False,
        )
        return {"FINISHED"}
