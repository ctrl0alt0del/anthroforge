import json
import bpy
import time

from ..core.utils import get_af_root
from ..core.registry import SCPRegistry
from ..core.visualization.fiber_sync import register_fiber_sync


class AF_OT_ResetFiberRestLength(bpy.types.Operator):
    bl_idname = "af.reset_fiber_rest_length"
    bl_label = "Reset Rest Length"
    bl_options = {"REGISTER", "UNDO"}

    fiber_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        vcp = root.af_vcp_system
        fiber = None
        for f in vcp.fibers:
            if f.id == self.fiber_id:
                fiber = f
                break
        if fiber is None:
            self.report({"ERROR"}, "Fiber not found.")
            return {"CANCELLED"}

        runtime = SCPRegistry(root)
        runtime.build()

        def endpoint_world(parent_id, attach_param_raw):
            parent = runtime.registry.get(parent_id)
            if parent is None:
                return None

            try:
                param = json.loads(attach_param_raw) if attach_param_raw else 0.0
            except Exception:
                param = 0.0

            local = parent.shape.compute_local_point(param)

            proxy = None
            for obj in context.scene.objects:
                if (
                    obj.get("af_proxy")
                    and obj.get("af_root_name") == root.name
                    and obj.get("af_scp_id") == parent_id
                ):
                    proxy = obj
                    break
            if proxy is None:
                return None

            return proxy.matrix_world @ local

        p0 = endpoint_world(fiber.a_parent_id, fiber.a_attach_param)
        p1 = endpoint_world(fiber.b_parent_id, fiber.b_attach_param)
        if p0 is None or p1 is None:
            self.report({"ERROR"}, "Cannot resolve fiber endpoints.")
            return {"CANCELLED"}

        fiber.rest_length = (p1 - p0).length
        register_fiber_sync().sync_root_to_scene(root=root, scene=context.scene, target_fiber_ids={fiber.id})
        self.report({"INFO"}, f"Rest length reset for {fiber.id}")
        return {"FINISHED"}


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

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        fiber.last_recompute_ms = elapsed_ms
        fiber.last_recompute_status = "CONVERGED" if converged else "NOT_CONVERGED"

        if converged:
            self.report({"INFO"}, f"Fiber {fiber.id} converged")
        else:
            self.report({"WARNING"}, f"Fiber {fiber.id} not converged after {max_passes} passes")

        return {"FINISHED"}
