import bpy
from mathutils import Vector

from ..app.runtime_api import sync_scene
from ..core.utils import get_af_root
from ..core.attachment_codec import encode_fiber_mesh_anchor
from ..core.scp_runtime.common import find_geometry_mesh_scp_obj
from ..core.id_utils import next_prefixed_id
from ..core.deps.dirty_hints import dirty_hints_for
from ..core.visualization.fiber_sync_helpers import nearest_parent_mesh_vertex_local_point


def _cancel(operator, message):
    operator.report({"ERROR"}, message)
    return {"CANCELLED"}


class AF_OT_AddFiberVCP(bpy.types.Operator):
    bl_idname = "af.add_fiber_vcp"
    bl_label = "Add Fiber VCP"

    def _endpoint_ids(self, context):
        origin_obj = context.scene.af_new_fiber_origin_obj
        insertion_obj = context.scene.af_new_fiber_insertion_obj
        if not origin_obj or not insertion_obj:
            return None, None
        return origin_obj.get("af_scp_id", ""), insertion_obj.get("af_scp_id", "")

    def _default_attach_raw(self, scene, root, parent_id):
        parent_obj = find_geometry_mesh_scp_obj(scene, root.name, parent_id)
        if parent_obj is None:
            return None
        local_pt = nearest_parent_mesh_vertex_local_point(parent_obj, scene.cursor.location.copy())
        if local_pt is None:
            local_pt = Vector((0.0, 0.0, 0.0))
        return encode_fiber_mesh_anchor(local_pt)

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

    def _resolved_inputs(self, context, root):
        origin_id, insertion_id = self._endpoint_ids(context)
        if not origin_id or not insertion_id:
            return None
        origin_raw = self._default_attach_raw(context.scene, root, origin_id)
        insertion_raw = self._default_attach_raw(context.scene, root, insertion_id)
        if origin_raw is None or insertion_raw is None:
            return None
        return origin_id, insertion_id, origin_raw, insertion_raw

    def _new_fiber(self, root, origin_id, insertion_id, origin_raw, insertion_raw):
        fibers = root.af_vcp_system.fibers
        fiber = fibers.add()
        fiber.id = next_prefixed_id(fibers, "FIBER")
        fiber.name = fiber.id
        fiber.a_parent_id, fiber.a_attach_param = origin_id, origin_raw
        fiber.b_parent_id, fiber.b_attach_param = insertion_id, insertion_raw
        self._init_fiber_defaults(fiber)
        return fiber

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return _cancel(self, "No AF_ROOT found.")
        resolved = self._resolved_inputs(context, root)
        if resolved is None:
            return _cancel(self, "Select valid SCP geometry endpoints.")
        f = self._new_fiber(root, *resolved)
        root.af_vcp_system.active_vcp_type, root.af_vcp_system.active_vcp_id = "FIBER", f.id
        sync_scene(root=root, scene=context.scene, dirty_hints=dirty_hints_for("FIBER", {f.id}))
        self.report({"INFO"}, f"Added {f.id}")
        return {"FINISHED"}
