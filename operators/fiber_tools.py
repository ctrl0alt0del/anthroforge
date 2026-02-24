import json
import bpy
import time

from ..core.utils import get_af_root
from ..core.registry import SCPRegistry
from ..core.visualization.fiber_sync import register_fiber_sync
from ..core.visualization.muscle_sync import register_muscle_sync

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

        # Optional: reset UI status so user sees fresh state before next recompute
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

    def execute(self, context):
        t0 = time.perf_counter()

        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        fiber = self._find_target_fiber(root)
        if fiber is None:
            self.report({"ERROR"}, "Target fiber not found.")
            return {"CANCELLED"}

        sync = register_fiber_sync()

        max_passes = 40
        converged = False

        for _ in range(max_passes):
            sync.sync_root_to_scene(
                root=root,
                scene=context.scene,
                bake=True,
                target_fiber_ids={fiber.id},
            )
            if not fiber.not_converged:
                converged = True
                break
        register_muscle_sync().sync_root_to_scene(root=root, scene=context.scene)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        fiber.last_recompute_ms = elapsed_ms
        fiber.last_recompute_status = "CONVERGED" if converged else "NOT_CONVERGED"

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

        scp_id = ""
        obj = context.active_object
        if obj and obj.get("af_proxy") and obj.get("af_root_name") == root.name:
            scp_id = obj.get("af_scp_id", "")
        if not scp_id:
            idx = root.af_scp_system.active_scp_index
            if 0 <= idx < len(root.af_scp_system.scps):
                scp_id = root.af_scp_system.scps[idx].id

        if not scp_id:
            self.report({"ERROR"}, "Select an SCP in viewport or SCP tree first.")
            return {"CANCELLED"}

        runtime = SCPRegistry(root)
        runtime.build()
        parent = runtime.registry.get(scp_id)
        if parent is None:
            self.report({"ERROR"}, "Selected SCP not found in runtime registry.")
            return {"CANCELLED"}

        params = parent.shape.get_attach_params()
        p = params[0] if params else 0.0

        tp = fiber.mid_touches.add()
        tp.parent_id = scp_id
        tp.attach_param = json.dumps(p)

        sync = register_fiber_sync()
        sync.clear_solver_cache(fiber.id)
        sync.sync_root_to_scene(root=root, scene=context.scene, target_fiber_ids={fiber.id})
        register_muscle_sync().sync_root_to_scene(root=root, scene=context.scene)
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

        sync = register_fiber_sync()
        sync.clear_solver_cache(fiber.id)
        sync.sync_root_to_scene(root=root, scene=context.scene, target_fiber_ids={fiber.id})
        register_muscle_sync().sync_root_to_scene(root=root, scene=context.scene)
        return {"FINISHED"}