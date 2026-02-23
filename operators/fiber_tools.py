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
        register_fiber_sync().sync_root_to_scene(root=root, scene=context.scene)
        self.report({"INFO"}, f"Rest length reset for {fiber.id}")
        return {"FINISHED"}


class AF_OT_RecomputeFiber(bpy.types.Operator):
    bl_idname = "af.recompute_fiber"
    bl_label = "Recompute Fiber"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        t0 = time.perf_counter()
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        sync = register_fiber_sync()

        # One-click converge loop (bake mode)
        max_passes = 40
        for _ in range(max_passes):
            sync.sync_root_to_scene(root=root, scene=context.scene, bake=True)

            # stop when all fibers converged
            any_not_converged = False
            for f in root.af_vcp_system.fibers:
                if f.not_converged:
                    any_not_converged = True
                    break

            if not any_not_converged:
                self.report({"WARNING"}, "Reached recompute cap before full convergence")
                break
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        status = "CONVERGED"
        for f in root.af_vcp_system.fibers:
            if f.not_converged:
                status = "NOT_CONVERGED"
                break

        for f in root.af_vcp_system.fibers:
            f.last_recompute_ms = elapsed_ms
            f.last_recompute_status = status
        self.report({"INFO"}, "Fiber recompute finished")
        return {"FINISHED"}
