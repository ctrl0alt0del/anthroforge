import bpy

from ..app.use_cases.fiber_create import create_fiber_from_proxy_vertices


def _finish(op, result):
    if result.ok:
        return {"FINISHED"}
    op.report({result.level}, result.message)
    return {"CANCELLED"}


class AF_OT_ConnectProxyVerticesWithFiber(bpy.types.Operator):
    bl_idname = "af.connect_proxy_vertices_with_fiber"
    bl_label = "Connect Vertices with Fiber"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, create_fiber_from_proxy_vertices(context))
