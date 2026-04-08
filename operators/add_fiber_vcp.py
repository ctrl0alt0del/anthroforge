import bpy

from ..core.utils import get_af_root
from ..core.attachment import Attachment
from ..core.attachment_codec import encode_fiber_shape_param
from ..core.registry import SCPRegistry
from ..core.id_utils import next_prefixed_id
from ..core.deps.dirty_hints import dirty_hints_for
from ..core.visualization.sync_runner import sync_from_dirty_hints


class AF_OT_AddFiberVCP(bpy.types.Operator):
    bl_idname = "af.add_fiber_vcp"
    bl_label = "Add Fiber VCP"

    def _endpoint_ids(self, context):
        origin_obj = context.scene.af_new_fiber_origin_obj
        insertion_obj = context.scene.af_new_fiber_insertion_obj
        if not origin_obj or not insertion_obj:
            return None, None
        return origin_obj.get("af_scp_id", ""), insertion_obj.get("af_scp_id", "")

    def _first_param(self, runtime, parent_id):
        parent = runtime.registry.get(parent_id)
        if parent is None:
            return 0.0
        params = parent.shape.get_attach_params()
        return params[0] if params else 0.0

    def _init_fiber_defaults(self, fiber):
        fiber.node_count = 64
        fiber.iterations_interactive = 12
        fiber.iterations_bake = 180
        fiber.stretch_stiffness = 0.9
        fiber.bend_stiffness = 0.02
        fiber.collision_margin = 0.002
        fiber.damping = 0.01
        fiber.not_converged = False
        fiber.thickness = 0.01

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            self.report({"ERROR"}, "No AF_ROOT found.")
            return {"CANCELLED"}
        origin_id, insertion_id = self._endpoint_ids(context)
        if not origin_id or not insertion_id:
            self.report({"ERROR"}, "Select Origin/Insertion SCP proxy objects.")
            return {"CANCELLED"}
        runtime = SCPRegistry(root)
        runtime.build()
        fibers = root.af_vcp_system.fibers
        f = fibers.add()
        f.id = next_prefixed_id(fibers, "FIBER")
        f.name = f.id
        origin = Attachment(parent_id=origin_id, param=self._first_param(runtime, origin_id))
        insertion = Attachment(parent_id=insertion_id, param=self._first_param(runtime, insertion_id))
        f.a_parent_id, f.a_attach_param = origin.parent_id, encode_fiber_shape_param(origin.param)
        f.b_parent_id, f.b_attach_param = insertion.parent_id, encode_fiber_shape_param(insertion.param)
        self._init_fiber_defaults(f)
        root.af_vcp_system.active_vcp_type, root.af_vcp_system.active_vcp_id = "FIBER", f.id
        sync_from_dirty_hints(
            root=root,
            scene=context.scene,
            dirty_hints=dirty_hints_for("FIBER", {f.id}),
        )
        self.report({"INFO"}, f"Added {f.id}")
        return {"FINISHED"}
